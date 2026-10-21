"""Decoder with GQA, tied embeddings and optional recomputed output loss."""
import math
import copy

import torch
from torch import nn
from torch.nn import functional as F
from torch.utils.checkpoint import checkpoint


class RMSNorm(nn.Module):
    def __init__(self, dim, eps):
        super().__init__()
        self.weight = nn.Parameter(torch.ones(dim))
        self.eps = eps

    def forward(self, x):
        y = x.float()
        y = y * torch.rsqrt(y.square().mean(-1, keepdim=True) + self.eps)
        return (y * self.weight).to(x.dtype)


def rope(x, cos, sin):
    a, b = x.float().chunk(2, dim=-1)
    return torch.cat((a * cos - b * sin, b * cos + a * sin), dim=-1).to(x.dtype)


class Attention(nn.Module):
    def __init__(self, c):
        super().__init__()
        d, self.h, self.kv, self.hd = c["dim"], c["n_heads"], c["n_kv_heads"], c["head_dim"]
        self.q = nn.Linear(d, self.h * self.hd, bias=False)
        self.k = nn.Linear(d, self.kv * self.hd, bias=False)
        self.v = nn.Linear(d, self.kv * self.hd, bias=False)
        self.out = nn.Linear(self.h * self.hd, d, bias=False)

    def forward(self, x, cos, sin):
        b, t, _ = x.shape
        q = rope(self.q(x).view(b, t, self.h, self.hd).transpose(1, 2), cos, sin)
        k = rope(self.k(x).view(b, t, self.kv, self.hd).transpose(1, 2), cos, sin)
        v = self.v(x).view(b, t, self.kv, self.hd).transpose(1, 2)
        y = F.scaled_dot_product_attention(q, k, v, is_causal=True, dropout_p=0.0, enable_gqa=True)
        return self.out(y.transpose(1, 2).contiguous().view(b, t, -1))


class FFN(nn.Module):
    def __init__(self, c):
        super().__init__()
        self.gate = nn.Linear(c["dim"], c["hidden_dim"], bias=False)
        self.up = nn.Linear(c["dim"], c["hidden_dim"], bias=False)
        self.down = nn.Linear(c["hidden_dim"], c["dim"], bias=False)

    def forward(self, x):
        return self.down(F.silu(self.gate(x)) * self.up(x))


class Block(nn.Module):
    def __init__(self, c):
        super().__init__()
        self.attn_norm = RMSNorm(c["dim"], c["norm_eps"])
        self.ffn_norm = RMSNorm(c["dim"], c["norm_eps"])
        self.attention = Attention(c)
        self.ffn = FFN(c)

    def forward(self, x, cos, sin):
        x = x + self.attention(self.attn_norm(x), cos, sin)
        return x + self.ffn(self.ffn_norm(x))


class Model(nn.Module):
    def __init__(self, c, activation_checkpointing=False, loss_chunk_tokens=0, depth=None):
        super().__init__()
        self.config = c
        self.activation_checkpointing = activation_checkpointing
        self.loss_chunk_tokens = loss_chunk_tokens
        self.embedding = nn.Embedding(c["vocab_size"], c["dim"])
        self.layers = nn.ModuleList([Block(c) for _ in range(depth or c["n_layers"])])
        self.norm = RMSNorm(c["dim"], c["norm_eps"])
        self.output = nn.Linear(c["dim"], c["vocab_size"], bias=False)
        self.output.weight = self.embedding.weight
        # named_parameters removes aliases: shared embedding is initialized exactly once.
        for name, p in self.named_parameters():
            if p.ndim >= 2:
                std = 0.02 / math.sqrt(2 * c["n_layers"]) if name.endswith(("attention.out.weight", "ffn.down.weight")) else 0.02
                nn.init.normal_(p, mean=0.0, std=std)
        positions = torch.arange(c["max_seq_len"], dtype=torch.float32)
        inv_freq = 1.0 / (c["rope_theta"] ** (torch.arange(0, c["head_dim"], 2, dtype=torch.float32) / c["head_dim"]))
        angle = torch.outer(positions, inv_freq)
        self.register_buffer("rope_cos", angle.cos()[None, None], persistent=False)
        self.register_buffer("rope_sin", angle.sin()[None, None], persistent=False)

    def forward(self, tokens, targets=None):
        t = tokens.shape[1]
        cos, sin = self.rope_cos[:, :, :t], self.rope_sin[:, :, :t]
        x = self.embedding(tokens)
        if x.is_cuda and torch.is_autocast_enabled('cuda'):
            x = x.to(torch.get_autocast_dtype('cuda'))
        for block in self.layers:
            if self.activation_checkpointing and self.training:
                x = checkpoint(block, x, cos, sin, use_reentrant=False)
            else:
                x = block(x, cos, sin)
        x = self.norm(x)
        if targets is not None and self.loss_chunk_tokens:
            # Recompute each output projection during backward instead of retaining
            # a full sequence x vocabulary tensor in FP32 cross entropy.
            def chunk_loss(hidden, labels):
                logits = self.output(hidden)
                return F.cross_entropy(logits.reshape(-1, logits.shape[-1]), labels.reshape(-1), reduction="sum")
            total = x.new_zeros((), dtype=torch.float32)
            for start in range(0, t, self.loss_chunk_tokens):
                end = start + self.loss_chunk_tokens
                hidden, labels = x[:, start:end], targets[:, start:end]
                if self.training and torch.is_grad_enabled():
                    total = total + checkpoint(chunk_loss, hidden, labels, use_reentrant=False)
                else:
                    total = total + chunk_loss(hidden, labels)
            return total / targets.ne(-100).sum().clamp_min(1)
        if targets is None:
            return self.output(x)
        # Select BEFORE the vocabulary projection, avoiding prompt/padding logits.
        valid = targets.ne(-100)
        hidden = x[valid]
        labels = targets[valid]
        return F.cross_entropy(self.output(hidden).float(), labels)

    def grow(self, depth, opt=None):
        """Append trainable identity blocks; retain old Parameter identities and Adam states."""
        previous = len(self.layers)
        if not previous < depth <= self.config['n_layers']:
            raise ValueError('Invalid growth depth')
        for index in range(previous, depth):
            block = copy.deepcopy(self.layers[(index - previous) % previous])
            block.zero_grad(set_to_none=True)
            with torch.no_grad():
                block.attention.out.weight.zero_()
                block.ffn.down.weight.zero_()
            self.layers.append(block)
        if opt is not None:
            # Match a freshly constructed model's order, including the final norm.
            # State is keyed by Parameter identity and therefore remains intact.
            opt.param_groups[0]['params'] = [p for p in self.parameters() if p.ndim >= 2]
            opt.param_groups[1]['params'] = [p for p in self.parameters() if p.ndim < 2]
        return previous, depth

    def parameter_count(self):
        return sum(p.numel() for p in self.parameters())

    @torch.inference_mode()
    def infer(self,tokens,cache=None):
        """Full prompt then single-token decode, retaining all previous KV states."""
        offset=0 if cache is None else cache[0][0].shape[2]
        t=tokens.shape[1]
        if offset+t>self.config['max_seq_len']:raise ValueError('Context including output exceeds configured maximum')
        if offset and t!=1:raise ValueError('Cached decode expects one new token')
        cos=self.rope_cos[:,:,offset:offset+t];sin=self.rope_sin[:,:,offset:offset+t]
        x=self.embedding(tokens);new=[]
        if x.is_cuda and torch.is_autocast_enabled('cuda'):x=x.to(torch.get_autocast_dtype('cuda'))
        for i,block in enumerate(self.layers):
            attn=block.attention;z=block.attn_norm(x);b=z.shape[0]
            q=rope(attn.q(z).view(b,t,attn.h,attn.hd).transpose(1,2),cos,sin)
            k=rope(attn.k(z).view(b,t,attn.kv,attn.hd).transpose(1,2),cos,sin)
            v=attn.v(z).view(b,t,attn.kv,attn.hd).transpose(1,2)
            if cache is not None:
                k=torch.cat((cache[i][0],k),dim=2);v=torch.cat((cache[i][1],v),dim=2)
            new.append((k,v))
            out=F.scaled_dot_product_attention(q,k,v,is_causal=not bool(offset),dropout_p=0.,enable_gqa=True)
            x=x+attn.out(out.transpose(1,2).contiguous().view(b,t,-1))
            x=x+block.ffn(block.ffn_norm(x))
        return self.output(self.norm(x[:,-1:])),new


def optimizer(model, c, fused=True):
    params = list(model.parameters())
    assert len({id(p) for p in params}) == len(params)
    return torch.optim.AdamW([
        {"params": [p for p in params if p.ndim >= 2], "weight_decay": c["weight_decay"]},
        {"params": [p for p in params if p.ndim < 2], "weight_decay": 0.0},
    ], lr=c["learning_rate"], betas=c["betas"], eps=c["eps"], fused=fused)
