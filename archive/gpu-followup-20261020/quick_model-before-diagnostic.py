"""Benchmark breve isolato: pesi casuali, dati sintetici, nessun checkpoint."""
import argparse,contextlib,json,os,statistics,sys,time
from pathlib import Path
import torch
import torch.distributed as dist
import torch.multiprocessing as mp
import torch.nn.functional as F
import yaml
sys.path.insert(0,'/audit/source_snapshot')
from riscrivo.model import Model,optimizer,rope

def config():return yaml.safe_load(Path('/audit/snapshot_config.yaml').read_text())
def save(p,x):Path(p).write_text(json.dumps(x,indent=2))
def worker(rank,world,args):
 torch.set_num_threads(2);torch.cuda.set_device(rank);torch.manual_seed(12345)
 if world>1:
  os.environ['MASTER_ADDR']='127.0.0.1';os.environ['MASTER_PORT']='29678'
  dist.init_process_group('nccl',rank=rank,world_size=world)
 c=config();m=Model(c['model'],activation_checkpointing=args.recompute,depth=args.depth).cuda(rank);opt=optimizer(m,c['training'])
 params=m.parameter_count()
 model=torch.nn.parallel.DistributedDataParallel(m,device_ids=[rank],gradient_as_bucket_view=True,bucket_cap_mb=64) if world>1 else m
 g=torch.Generator(device=rank).manual_seed(555+rank)
 # The same global examples in all modes; distribute contiguous sequence ranges.
 data_gen=torch.Generator(device=rank).manual_seed(555)
 all_data=torch.randint(0,c['model']['vocab_size'],(args.global_sequences,2048),generator=data_gen,device=rank)
 counts=[args.global_sequences] if world==1 else ([args.global_sequences//2]*2 if not args.balanced else [18,14])
 local_sequences=counts[rank];offset=sum(counts[:rank]);micro=args.microbatch
 assert local_sequences%micro==0
 times=[];losses=[]
 for step in range(args.warmup+args.samples):
  if world>1:dist.barrier()
  torch.cuda.synchronize(rank);start=time.perf_counter();opt.zero_grad(set_to_none=True);total=torch.zeros((),device=rank)
  micros=local_sequences//micro
  for k in range(micros):
   ctx=model.no_sync() if world>1 and k<micros-1 else contextlib.nullcontext()
   with ctx,torch.autocast('cuda',dtype=torch.bfloat16):
    x=all_data[offset+k*micro:offset+(k+1)*micro];y=x.roll(-1,1)
    loss=model(x,y);(loss*(world*micro/args.global_sequences)).backward();total+=loss.detach()*micro/args.global_sequences
  norm=torch.nn.utils.clip_grad_norm_(m.parameters(),1.0);opt.step();torch.cuda.synchronize(rank)
  elapsed=torch.tensor(time.perf_counter()-start,device=rank,dtype=torch.float64)
  if world>1:dist.all_reduce(elapsed,op=dist.ReduceOp.MAX);dist.all_reduce(total)
  assert torch.isfinite(total) and torch.isfinite(norm)
  if step>=args.warmup:times.append(elapsed.item());losses.append(total.item())
  if rank==0:print(json.dumps({'event':'training_step','world':world,'step':step,'seconds':elapsed.item(),'loss':total.item()}),flush=True)
 # Verify equal parameter samples on both replicas after actual optimizer updates.
 sample=torch.cat([p.detach().flatten()[::max(1,p.numel()//8)][:8] for p in m.parameters()]).float()
 difference=0.
 if world>1:
  ref=sample.clone();dist.broadcast(ref,src=0);difference=float((sample-ref).abs().max());delta=torch.tensor(difference,device=rank);dist.all_reduce(delta,op=dist.ReduceOp.MAX);difference=delta.item();assert difference==0.
 if rank==0:save(args.output,{'kind':'training','parameters':params,'layers':args.depth,'context':2048,'global_batch_sequences':args.global_sequences,
  'global_batch_tokens':2048*args.global_sequences,'microbatch':micro,'sequences_per_rank':counts,'world_size':world,
  'activation_checkpointing':args.recompute,'mixed_precision':'BF16, FP32 parameters and Adam states','warmup_updates':args.warmup,'measured_updates':args.samples,
  'seconds':times,'median_seconds':statistics.median(times),'tokens_per_second':2048*args.global_sequences/statistics.median(times),
  'losses':losses,'replica_sample_max_difference':difference,'peak_reserved_bytes_rank0':torch.cuda.max_memory_reserved(rank),
  'scope':'Synthetic data and random weights. No production checkpoint, no compilation, no linguistic quality evaluation.'})
 if world>1:dist.destroy_process_group()

def infer(m,tokens,cache=None):
 offset=0 if cache is None else cache[0][0].shape[2];t=tokens.shape[1];x=m.embedding(tokens);new=[]
 for i,block in enumerate(m.layers):
  device=block.attention.q.weight.device
  x=x.to(device);cr,sr=m._bench_rope[device.index];cos=cr[:,:,offset:offset+t];sin=sr[:,:,offset:offset+t]
  a=block.attention;z=block.attn_norm(x);b=z.shape[0]
  q=rope(a.q(z).view(b,t,a.h,a.hd).transpose(1,2),cos,sin)
  k=rope(a.k(z).view(b,t,a.kv,a.hd).transpose(1,2),cos,sin)
  v=a.v(z).view(b,t,a.kv,a.hd).transpose(1,2)
  if cache is not None:k=torch.cat((cache[i][0],k),2);v=torch.cat((cache[i][1],v),2)
  new.append((k,v));out=F.scaled_dot_product_attention(q,k,v,is_causal=not bool(offset),enable_gqa=True)
  x=x+a.out(out.transpose(1,2).contiguous().view(b,t,-1));x=x+block.ffn(block.ffn_norm(x))
 x=x.to(m.embedding.weight.device);return m.output(m.norm(x[:,-1:])),new

@torch.inference_mode()
def inference(args):
 torch.set_num_threads(2);torch.cuda.set_device(0);torch.manual_seed(12345);c=config()
 m=Model(c['model']).to(device='cuda:0',dtype=torch.bfloat16).eval();prompt=torch.randint(0,c['model']['vocab_size'],(1,256),device=0)
 m._bench_rope={i:(m.rope_cos.to(i),m.rope_sin.to(i)) for i in [0,1]}
 results=[];reference=None
 for mode in ['single_ada','split_16_16']:
  if mode.startswith('split'):
   for block in m.layers[16:]:block.to('cuda:1')
  times=[];prefills=[];decode=[]
  for repeat in range(3):
   torch.cuda.synchronize(0);torch.cuda.synchronize(1);start=time.perf_counter();logits,cache=infer(m,prompt)
   torch.cuda.synchronize(0);torch.cuda.synchronize(1);middle=time.perf_counter()
   if repeat==0:
    observed=logits.float().cpu()
    if reference is None:reference=observed;error=0.
    else:error=float(torch.linalg.vector_norm(observed-reference)/torch.linalg.vector_norm(reference));assert error<0.03,error
   for _ in range(32):
    # Identical forced token path; no EOS shortcut and the same cache lengths.
    token=torch.full((1,1),42,device=0,dtype=torch.long);logits,cache=infer(m,token,cache)
   torch.cuda.synchronize(0);torch.cuda.synchronize(1);end=time.perf_counter()
   assert torch.isfinite(logits).all()
   if repeat:times.append(end-start);prefills.append(middle-start);decode.append(end-middle)
   del cache
  results.append({'mode':mode,'prefill_seconds':prefills,'decode_32_seconds':decode,'total_seconds':times,
     'prefill_median_ms':1000*statistics.median(prefills),'decode_tokens_per_second':32/statistics.median(decode),
     'split_relative_l2_vs_single':error})
 save(args.output,{'kind':'inference','parameters':m.parameter_count(),'layers':32,'dtype':'BF16','batch':1,
  'prompt_tokens':256,'decode_tokens':32,'warmup_repetitions':1,'measured_repetitions':2,'results':results,
  'scope':'Random weights, KV cache; same eager implementation and inputs; performance only, no language quality.'})

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--mode',choices=['train','infer'],required=True);p.add_argument('--world',type=int,default=1);p.add_argument('--output',required=True)
 p.add_argument('--depth',type=int,default=32);p.add_argument('--global-sequences',type=int,default=32);p.add_argument('--microbatch',type=int,default=1);p.add_argument('--recompute',action='store_true');p.add_argument('--balanced',action='store_true');p.add_argument('--warmup',type=int,default=2);p.add_argument('--samples',type=int,default=5);args=p.parse_args()
 if args.mode=='infer':inference(args)
 elif args.world==1:worker(0,1,args)
 else:mp.spawn(worker,args=(2,args),nprocs=2,join=True)
