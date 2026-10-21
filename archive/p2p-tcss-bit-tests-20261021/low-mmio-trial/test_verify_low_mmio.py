#!/usr/bin/env python3
"""Offline fixtures only. The verifier must never modify any fixture file."""
import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

IDS = [
    ('0000:00:00.0', 0x8086, 0x4641),
    ('0000:00:01.0', 0x8086, 0x460d),
    ('0000:00:07.0', 0x8086, 0x466e),
    ('0000:04:00.0', 0x1b21, 0x2461),
    ('0000:05:00.0', 0x1b21, 0x2461),
    ('0000:06:00.0', 0x10de, 0x2571),
    ('0000:06:00.1', 0x10de, 0x228e),
    ('0000:01:00.0', 0x10de, 0x28b0),
    ('0000:01:00.1', 0x10de, 0x22be),
]


def dev(root, bdf):
    return root / 'sys/bus/pci/devices' / bdf


def dword(root, bdf, offset, value):
    p = dev(root, bdf) / 'config'
    data = bytearray(p.read_bytes())
    struct.pack_into('<I', data, offset, value)
    p.write_bytes(data)


def resource(root, bdf, index, start, end, flags):
    p = dev(root, bdf) / 'resource'
    lines = p.read_text().splitlines()
    lines[index] = '0x%016x 0x%016x 0x%016x' % (start, end, flags)
    p.write_text('\n'.join(lines) + '\n')


def fixture(root):
    root.mkdir()
    (root / 'cpu.identity').write_text('000906a3 00000000\n')
    for i, (bdf, vendor, device) in enumerate(IDS):
        d = dev(root, bdf)
        d.mkdir(parents=True)
        c = bytearray(64)
        struct.pack_into('<I', c, 0, device << 16 | vendor)
        if 2 <= i <= 4:
            c[0x0e] = 1
            c[0x18] = 0 if i == 2 else i + 1
            c[0x19] = i + 2
            c[0x1a] = 6
            struct.pack_into('<III', c, 0x24, 0x91f18001, 0, 0)
        if i == 5:
            struct.pack_into('<IIII', c, 0x14, 0x8000000c, 0, 0x9000000c, 0)
        (d / 'config').write_bytes(c)
        (d / 'resource').write_text('0x0 0x0 0x0\n' * (17 if 2 <= i <= 4 else 13))
        if 2 <= i <= 4:
            resource(root, bdf, 15, 0x80000000, 0x91ffffff, 0x102201)
        if i == 5:
            resource(root, bdf, 1, 0x80000000, 0x8fffffff, 0x14220c)
            resource(root, bdf, 3, 0x90000000, 0x91ffffff, 0x14220c)


def hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('binary', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    binary = str(args.binary.resolve())
    cases = [('valid', None, True)]
    cases.extend([
        ('cpu_wrong_signature', lambda r: (r / 'cpu.identity').write_text('906a2 0\n'), False),
        ('cpu_hypervisor', lambda r: (r / 'cpu.identity').write_text('906a3 80000000\n'), False),
        ('cpu_missing', lambda r: (r / 'cpu.identity').unlink(), False),
        ('cpu_extra_token', lambda r: (r / 'cpu.identity').write_text('906a3 0 x\n'), False),
        ('cpu_extra_line', lambda r: (r / 'cpu.identity').write_text('906a3 0\nx\n'), False),
        ('cpu_overflow', lambda r: (r / 'cpu.identity').write_text('1000906a3 0\n'), False),
        ('cpu_negative', lambda r: (r / 'cpu.identity').write_text('-906a3 0\n'), False),
    ])
    for bdf, _, _ in IDS:
        cases.append(('wrong_identity_' + bdf,
                      lambda r, b=bdf: dword(r, b, 0, 0xffffffff), False))
        cases.append(('missing_config_' + bdf,
                      lambda r, b=bdf: (dev(r, b) / 'config').unlink(), False))
    for bdf, _, _ in IDS[2:5]:
        for off, value in [(0x24, 0x92f18001), (0x28, 0x46), (0x2c, 0x46),
                           (0x18, 0), (0x0c, 0)]:
            cases.append(('bridge_config_%s_%x' % (bdf, off),
                          lambda r, b=bdf, o=off, v=value: dword(r, b, o, v), False))
        for start, end, flags, label in [
                (0x81000000, 0x91ffffff, 0x102201, 'start'),
                (0x80000000, 0x92ffffff, 0x102201, 'end'),
                (0x80000000, 0x91ffffff, 0x100201, 'flags')]:
            cases.append(('bridge_resource_%s_%s' % (bdf, label),
                          lambda r, b=bdf, s=start, e=end, f=flags:
                          resource(r, b, 15, s, e, f), False))
    bdf = '0000:06:00.0'
    for off, value in [(0x14, 0x80000004), (0x18, 0x46), (0x1c, 0x9200000c), (0x20, 0x46)]:
        cases.append(('gpu_config_%x' % off,
                      lambda r, o=off, v=value: dword(r, '0000:06:00.0', o, v), False))
    for index, start, end in [(1, 0x80000000, 0x8fffffff), (3, 0x90000000, 0x91ffffff)]:
        for s, e, flags, label in [
                (start + 0x100000, end, 0x14220c, 'start'),
                (start, end + 0x100000, 0x14220c, 'size'),
                (start, end, 0x14020c, 'no_prefetch'),
                (start, end, 0x4210c, 'wrong_type'),
                (start, end, 0x2014220c, 'unset'),
                (start, end, 0x8014220c, 'busy')]:
            cases.append(('gpu_resource_%d_%s' % (index, label),
                          lambda r, idx=index, a=s, z=e, f=flags:
                          resource(r, '0000:06:00.0', idx, a, z, f), False))
    cases.extend([
        ('truncated_config', lambda r: (dev(r, bdf) / 'config').write_bytes(b'\0' * 63), False),
        ('missing_resource', lambda r: (dev(r, bdf) / 'resource').unlink(), False),
        ('malformed_resource', lambda r: (dev(r, bdf) / 'resource').write_text('garbage\n'), False),
        ('negative_resource', lambda r: (dev(r, bdf) / 'resource').write_text('-1 0 0\n'), False),
        ('overflow_resource', lambda r: (dev(r, bdf) / 'resource').write_text('10000000000000000 0 0\n'), False),
        ('extra_resource_token', lambda r: (dev(r, bdf) / 'resource').write_text('0 0 0 x\n'), False),
        ('truncated_resource_line', lambda r: (dev(r, bdf) / 'resource').write_text('0 0 0'), False),
        ('too_many_resource_lines', lambda r: (dev(r, bdf) / 'resource').write_text('0 0 0\n' * 33), False),
        ('too_few_resource_lines', lambda r: (dev(r, bdf) / 'resource').write_text('0 0 0\n' * 4), False),
    ])
    results = []
    with tempfile.TemporaryDirectory(prefix='cask-low-mmio-fixtures-') as temp:
        base = Path(temp) / 'base'
        fixture(base)
        for number, (name, mutate, expected) in enumerate(cases):
            case = Path(temp) / str(number)
            shutil.copytree(base, case)
            if mutate:
                mutate(case)
            before = hashes(case)
            p = subprocess.run([binary, '--fixture', str(case)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            output = p.stdout.decode() + p.stderr.decode()
            actual = p.returncode == 0
            immutable = hashes(case) == before
            passed = (actual == expected and immutable and
                      'LOW_MMIO_NATIVE_PASS' not in output and
                      (not expected or 'LOW_MMIO_FIXTURE_PASS' in output))
            results.append({'case': name, 'passed': passed, 'returncode': p.returncode,
                            'fixture_unchanged': immutable})
            if not passed:
                print(name, output)
    report = {'status': 'PASS' if all(x['passed'] for x in results) else 'FAIL',
              'cases': len(results), 'passed': sum(x['passed'] for x in results),
              'binary_sha256': hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
              'source_sha256': hashlib.sha256(Path(__file__).with_name('verify_low_mmio.c').read_bytes()).hexdigest(),
              'scope': 'synthetic offline fixtures, no hardware access or static Linux build certification',
              'results': results}
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + '\n')
    print('%s: %d/%d offline fixture cases' % (report['status'], report['passed'], report['cases']))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
