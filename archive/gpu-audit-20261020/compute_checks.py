"""Prove sintetiche indipendenti: non legge né aggiorna checkpoint Riscrivo."""
import argparse
import gc
import json
import math
import statistics
import time
from pathlib import Path

import torch
import torch.nn.functional as F
from torch.nn.attention import SDPBackend, sdpa_kernel


def clean():
    gc.collect()
    for i in range(torch.cuda.device_count()):
        torch.cuda.synchronize(i)
        with torch.cuda.device(i):
            torch.cuda.empty_cache()


def timing(fn, device, target_ms=100, samples=5):
    for _ in range(3):
        fn()
    torch.cuda.synchronize(device)
    start = torch.cuda.Event(enable_timing=True)
    end = torch.cuda.Event(enable_timing=True)
    start.record()
    fn()
    end.record()
    end.synchronize()
    initial = max(start.elapsed_time(end), 0.005)
    repetitions = max(1, min(1000, int(target_ms / initial)))
    values = []
    for _ in range(samples):
        start.record()
        for _ in range(repetitions):
            fn()
        end.record()
        end.synchronize()
        values.append(start.elapsed_time(end) / repetitions)
    return {'median_ms': statistics.median(values), 'min_ms': min(values),
            'max_ms': max(values), 'samples_ms': values, 'repetitions': repetitions}


def fp32_mode(mode):
    torch.backends.cuda.matmul.fp32_precision = mode


def gemm(device, precision, size):
    torch.cuda.set_device(device)
    torch.manual_seed(20261020)
    fp32_mode('tf32' if precision == 'tf32' else 'ieee')
    raw_a = torch.randn(size, size, device=device) / math.sqrt(size)
    raw_b = torch.randn(size, size, device=device)
    if precision == 'fp8_e4m3':
        a = raw_a.to(torch.float8_e4m3fn)
        b = raw_b.to(torch.float8_e4m3fn)
        one = torch.ones((), device=device)
        def fn():
            value = torch._scaled_mm(a, b.t(), scale_a=one, scale_b=one,
                                    out_dtype=torch.bfloat16, use_fast_accum=False)
            return value[0] if isinstance(value, tuple) else value
    else:
        dtype = {'fp32': torch.float32, 'tf32': torch.float32,
                 'fp16': torch.float16, 'bf16': torch.bfloat16}[precision]
        a, b = raw_a.to(dtype), raw_b.to(dtype)
        output = torch.empty(size, size, dtype=dtype, device=device)
        def fn():
            return torch.mm(a, b.t(), out=output)
    result = fn()
    rows = torch.linspace(0, size - 1, 16, device=device).long()
    reference = a[rows].float().cpu().double() @ b[rows].float().cpu().double().t()
    original = raw_a[rows].cpu().double() @ raw_b[rows].cpu().double().t()
    observed = result[rows][:, rows].float().cpu().double()
    kernel_error = float(torch.linalg.vector_norm(observed - reference) /
                         torch.linalg.vector_norm(reference).clamp_min(1e-12))
    raw_error = float(torch.linalg.vector_norm(observed - original) /
                      torch.linalg.vector_norm(original).clamp_min(1e-12))
    tolerance = {'fp32': 0.00005, 'tf32': 0.006, 'fp16': 0.006,
                 'bf16': 0.025, 'fp8_e4m3': 0.025}[precision]
    assert torch.isfinite(observed).all() and kernel_error < tolerance, (precision, kernel_error)
    measured = timing(fn, device)
    measured.update({'precision': precision, 'size': size,
                     'tflops': (2 * size ** 3) / (measured['median_ms'] * 1e9),
                     'relative_l2_vs_quantized_input_fp64': kernel_error,
                     'relative_l2_vs_original_input_fp64': raw_error,
                     'checked_output_elements': 256, 'correct': True})
    return measured


def vram_patterns(device):
    torch.cuda.set_device(device)
    free, total = torch.cuda.mem_get_info(device)
    block_bytes = 256 * 1024 ** 2
    blocks = max(1, int(free * 0.80) // block_bytes)
    memory = [torch.empty(block_bytes // 4, dtype=torch.int32, device=device)
              for _ in range(blocks)]
    start = time.monotonic()
    passes = []
    for repeat in range(3):
        for pattern in [0, -1, 0x55555555, -1431655766]:
            for tensor in memory:
                tensor.fill_(pattern)
            for tensor in memory:
                assert bool(torch.all(tensor == pattern)), ('VRAM', device, repeat, pattern)
        for i, tensor in enumerate(memory):
            expected = torch.arange(tensor.numel(), dtype=torch.int32, device=device)
            expected.bitwise_xor_(i * 104729 + repeat * 65537)
            tensor.copy_(expected)
        for i, tensor in enumerate(memory):
            expected = torch.arange(tensor.numel(), dtype=torch.int32, device=device)
            expected.bitwise_xor_(i * 104729 + repeat * 65537)
            assert torch.equal(tensor, expected), ('VRAM_ADDRESS', device, repeat, i)
        passes.append({'pass': repeat + 1, 'errors': 0})
        print(json.dumps({'event': 'vram_pass', 'device': device, 'pass': repeat + 1,
                          'tested_bytes': blocks * block_bytes}), flush=True)
    return {'tested_bytes': blocks * block_bytes, 'free_at_start': free, 'total': total,
            'patterns_per_pass': 5, 'passes': passes, 'errors': 0,
            'elapsed_seconds': time.monotonic() - start}


def memory_bandwidth(device):
    torch.cuda.set_device(device)
    count = 1024 ** 3
    source = torch.empty(count, dtype=torch.uint8, device=device).fill_(73)
    dest = torch.empty_like(source)
    measured = timing(lambda: dest.copy_(source), device)
    assert torch.equal(dest, source)
    seconds = measured['median_ms'] / 1000
    return {**measured, 'bytes_per_copy': count,
            'payload_GBps': count / seconds / 1e9,
            'read_plus_write_GBps': 2 * count / seconds / 1e9, 'correct': True}


def attention(device, dtype):
    torch.cuda.set_device(device)
    torch.manual_seed(1528)
    q = torch.randn(2, 16, 2048, 64, dtype=dtype, device=device, requires_grad=True)
    k = torch.randn(2, 4, 2048, 64, dtype=dtype, device=device, requires_grad=True)
    v = torch.randn_like(k, requires_grad=True)
    def fn():
        q.grad = k.grad = v.grad = None
        out = F.scaled_dot_product_attention(q, k, v, is_causal=True, enable_gqa=True)
        out.float().square().mean().backward()
        return out
    with sdpa_kernel(SDPBackend.FLASH_ATTENTION):
        measured = timing(fn, device, target_ms=150)
    assert all(bool(torch.isfinite(x.grad).all()) for x in [q, k, v])
    # Riscontro indipendente sulla formula dell'attenzione, su una sequenza breve.
    qs, ks, vs = [x.detach()[:1, :, :128] for x in [q, k, v]]
    with sdpa_kernel(SDPBackend.FLASH_ATTENTION):
        actual = F.scaled_dot_product_attention(qs, ks, vs, is_causal=True,
                                               enable_gqa=True).float().cpu().double()
    qd, kd, vd = [x.float().cpu().double() for x in [qs, ks, vs]]
    kd, vd = kd.repeat_interleave(4, 1), vd.repeat_interleave(4, 1)
    logits = (qd @ kd.transpose(-1, -2)) / 8
    mask = torch.ones(128, 128, dtype=torch.bool).triu(1)
    expected = logits.masked_fill(mask, -float('inf')).softmax(-1) @ vd
    error = float(torch.linalg.vector_norm(actual - expected) / torch.linalg.vector_norm(expected))
    assert error < (0.025 if dtype == torch.bfloat16 else 0.006), error
    return {**measured, 'dtype': str(dtype), 'batch': 2, 'sequence': 2048,
            'query_heads': 16, 'kv_heads': 4, 'head_dim': 64,
            'forward_backward_block_tokens_per_second': 4096 / (measured['median_ms'] / 1000),
            'reference_relative_l2': error, 'gradients_finite': True,
            'scope': 'one attention operation, not a complete model or training run'}


def staged_transfers():
    size = 512 * 1024 ** 2
    result = []
    for src, dst in [(0, 1), (1, 0)]:
        torch.cuda.set_device(src)
        source = torch.empty(size, dtype=torch.uint8, device=src).fill_(src + 31)
        target = torch.empty(size, dtype=torch.uint8, device=dst)
        host = torch.empty(size, dtype=torch.uint8, pin_memory=True)
        def copy():
            with torch.cuda.device(src):
                host.copy_(source, non_blocking=True)
                torch.cuda.synchronize(src)
            with torch.cuda.device(dst):
                target.copy_(host, non_blocking=True)
                torch.cuda.synchronize(dst)
        copy()
        times = []
        for _ in range(5):
            start = time.perf_counter()
            for _ in range(3):
                copy()
            times.append((time.perf_counter() - start) / 3)
        assert bool(torch.all(target == src + 31)), 'host staged corruption'
        result.append({'source': src, 'destination': dst, 'bytes': size,
                       'seconds_per_copy': times, 'median_GBps': size / statistics.median(times) / 1e9,
                       'route': 'GPU to pinned host RAM to GPU, serialized', 'correct': True})
        del source, target, host
        clean()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--mode', choices=['compute', 'memory', 'staged'], required=True)
    parser.add_argument('--device', type=int, default=0)
    args = parser.parse_args()
    torch.set_num_threads(2)
    result = {'torch': torch.__version__, 'cuda': torch.version.cuda, 'mode': args.mode,
              'device': args.device, 'started_epoch': time.time(), 'cases': []}
    if args.mode == 'staged':
        result['transfers'] = staged_transfers()
    else:
        props = torch.cuda.get_device_properties(args.device)
        result['gpu'] = {'name': props.name, 'uuid': str(props.uuid),
                         'total_memory': props.total_memory}
        if args.mode == 'memory':
            result['vram'] = vram_patterns(args.device)
            clean()
            result['memory_bandwidth'] = memory_bandwidth(args.device)
        else:
            for precision in ['fp32', 'tf32', 'fp16', 'bf16', 'fp8_e4m3']:
                if precision == 'fp8_e4m3' and (props.major, props.minor) < (8, 9):
                    result['cases'].append({'precision': precision, 'status': 'unsupported_hardware'})
                    continue
                for size in [2048, 4096, 8192]:
                    try:
                        measured = gemm(args.device, precision, size)
                        result['cases'].append(measured)
                        print(json.dumps({'event': 'gemm', 'gpu': props.name, **measured}), flush=True)
                    except Exception as exc:
                        if precision != 'fp8_e4m3':
                            raise
                        result['cases'].append({'precision': precision, 'size': size,
                                                'status': 'unavailable', 'reason': str(exc)})
                        break
                    finally:
                        clean()
            result['attention'] = [attention(args.device, dtype)
                                   for dtype in [torch.float16, torch.bfloat16]]
    result['finished_epoch'] = time.time()
    Path(args.output).write_text(json.dumps(result, indent=2))
    print('CHECKS_COMPLETE', args.output, flush=True)


if __name__ == '__main__':
    main()
