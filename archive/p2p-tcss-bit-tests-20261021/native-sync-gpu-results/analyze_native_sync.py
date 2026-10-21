#!/usr/bin/env python3
"""Analisi riproducibile dei log locali; nessun accesso hardware."""
from pathlib import Path
import hashlib
import json
import re
import statistics

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
result = (HERE / 'result.log').read_text()
kernel = (HERE / 'kernel.log').read_text()
manifest = json.loads((ROOT / 'native-sync-probe-package/build-manifest.json').read_text())
state = json.loads((HERE / 'native-sync-gpu-state.json').read_text())

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()

def fields(line):
    return dict(re.findall(r'(\w+)=([^ ]+)', line))

snapshots = []
owners = []
operations = []
phases = []
previous = ''
for number, line in enumerate(result.splitlines(), 1):
    if line.startswith('PCIE_SNAPSHOT '):
        item = fields(line)
        item['line'] = number
        snapshots.append(item)
    elif line.startswith('OWNER_CHECK '):
        item = fields(line)
        item['line'] = number
        owners.append(item)
    elif line.startswith(('REMOTE_READ ', 'REMOTE_WRITE ')):
        item = fields(line)
        item.update(operation=line.split()[0], line=number)
        if previous.startswith('CORRUPTION '):
            item['corruption_line'] = previous
        operations.append(item)
    elif line.startswith('CaskLogicPeer '):
        item = fields(line)
        item['line'] = number
        phases.append(item)
    previous = line

assert len(snapshots) == 54
assert len(owners) == 4 and all(x['valid'] == '1' for x in owners)
assert len(operations) == 4
assert [x['valid'] for x in operations] == ['0', '1', '0', '0']
assert all(x['CONFIG_BYTES'] == '4096' and x['READ_ERRNO'] == '0' and x['clock_ok'] == '1' for x in snapshots)
by_phase = {}
for item in snapshots:
    by_phase.setdefault(item['phase'], {})[item['bdf']] = item
assert len(by_phase) == 9 and all(len(x) == 6 for x in by_phase.values())
skip = {'phase', 'monotonic', 'line'}
deltas = []
for operation in ('read_0_to_1', 'write_1_to_0', 'read_1_to_0', 'write_0_to_1'):
    before = by_phase[operation + '_before']
    after = by_phase[operation + '_after']
    differences = []
    for bdf, a in after.items():
        b = before[bdf]
        for key in set(a) | set(b):
            if key not in skip and a.get(key) != b.get(key):
                differences.append({'bdf': bdf, 'field': key, 'before': b.get(key), 'after': a.get(key)})
    deltas.append({'operation': operation, 'differences': sorted(differences, key=lambda x: (x['bdf'], x['field']))})
assert [len(x['differences']) for x in deltas] == [2, 0, 2, 0]
assert all(d['field'] == 'PCI_STATUS' and d['before'] == '0010' and d['after'] == '2010'
           for x in deltas for d in x['differences'])

offsets = []
for m in re.finditer(r'\[\s*([\d.]+)\] CaskLogicPeer phase=\w+ monotonic=([\d.]+)', kernel):
    offsets.append(float(m[1]) - float(m[2]))
assert len(offsets) == 10
offset = statistics.median(offsets)
data_done = next(float(x['monotonic']) for x in phases if x['phase'] == 'data_done')
context_exit = next(float(x['monotonic']) for x in phases if x['phase'] == 'context_exit_begin')
free_times = [float(x['monotonic']) for x in phases if x['phase'] == 'allocation_free_begin']
assert len(free_times) == 4 and min(free_times) > data_done
errors = []
for number, line in enumerate(kernel.splitlines(), 1):
    if 'left-over mappings' in line or 'Assertion failed:' in line:
        ts = float(re.search(r'\[\s*([\d.]+)\]', line)[1])
        errors.append({'line': number, 'kernel_time': ts, 'text': line,
                       'after_context_exit_seconds_estimate': ts - offset - context_exit})
assert len(errors) == 9 and all(x['after_context_exit_seconds_estimate'] > 0.28 for x in errors)

hash_files = [HERE / 'result.log', HERE / 'kernel.log', HERE / 'native-sync-gpu-state.json',
              ROOT / 'native-sync-probe-package/build-manifest.json',
              ROOT / 'native-sync-probe-package/probe-kernel.efi',
              ROOT / 'native-sync-probe-package/probe-initrd.img',
              ROOT / 'native-sync-probe-package/IDENTITY.txt',
              ROOT / 'native-sync-probe/peer_vmm_word_sync.cu',
              ROOT / 'native-sync-probe/peer_vmm_word_sync_native',
              ROOT / 'native-sync-probe/pcie_diag.h', ROOT / 'native-sync-probe/init-tcss-native.sh',
              ROOT / 'driver/nvidia-dynamic.ko', ROOT / 'firmware-sync-trial-registers.json']
hashes = {str(p.relative_to(ROOT)): {'sha256': sha(p), 'bytes': p.stat().st_size} for p in hash_files}
checks = {
    'kernel_sha256': 'native-sync-probe-package/probe-kernel.efi',
    'initrd_sha256': 'native-sync-probe-package/probe-initrd.img',
    'native_program_sha256': 'native-sync-probe/peer_vmm_word_sync_native',
    'native_source_sha256': 'native-sync-probe/peer_vmm_word_sync.cu',
    'native_header_sha256': 'native-sync-probe/pcie_diag.h',
    'module_sha256': 'driver/nvidia-dynamic.ko',
    'init_sha256': 'native-sync-probe/init-tcss-native.sh',
}
assert all(manifest[k] == hashes[p]['sha256'] for k, p in checks.items())
assert state['files']['probe-kernel.efi'] == manifest['kernel_sha256']
assert state['files']['probe-initrd.img'] == manifest['initrd_sha256']
assert state['files']['IDENTITY.txt'] == hashes['native-sync-probe-package/IDENTITY.txt']['sha256']
assert result.count('PEG_CCFG 00:01.0 00008077') == 3
assert result.count('TCSS_CCFG 00:07.0 00009077') == 3
assert result.count('TCSS_CCFG 00:07.2 00009077') == 3
assert 'DMAR: IOMMU disabled' in kernel
assert 'NATIVE_TEST_RC=5' in result and 'PROBE_COMPLETED' in result and 'SCRIPT_RC=5' in result

output = {
    'status': 'COMPLETED_3_OF_4_DATA_COMPARISONS_FAILED_WITH_OWNER_SYNCHRONIZATION',
    'analysis_scope': 'Local evidence only; no hardware operations',
    'hardware': {
        'cpu': 'Intel Core i9-12900H, family6 model0x9a stepping3',
        'bios': 'Micro Computer (HK) Tech Limited Venus Series/AHWSA 1.26 10/14/2024; combined trial patch active',
        'cuda_device_order': 'PCI_BUS_ID (init source)',
        'cuda_0': {'name': 'RTX 2000 Ada Generation', 'bdf': '0000:01:00.0', 'pci_id': '10de:28b0', 'root': '0000:00:01.0', 'root_id': '8086:460d'},
        'cuda_1': {'name': 'RTX A2000 12GB', 'bdf': '0000:06:00.0', 'pci_id': '10de:2571', 'root': '0000:00:07.0', 'root_id': '8086:466e'},
        'bridges': {'0000:04:00.0': '1b21:2461', '0000:05:00.0': '1b21:2461'},
        'native_iommu_disabled': True,
        'ccfg_before_module_after_module_after_test': {'00:01.0': '00008077', '00:07.0': '00009077', '00:07.2': '00009077'}
    },
    'payload_bytes': 4,
    'owners': owners,
    'operations': operations,
    'snapshots_count': len(snapshots),
    'phase_count': len(by_phase),
    'snapshots': snapshots,
    'operation_deltas': deltas,
    'new_error_interpretation': {
        'pci_status_bit13': 'Received Master Abort: Intel D1/D7 root receives Unsupported Request completion from backbone.',
        'read_0_to_1': 'A2000 reads Ada; new RMA on requester A2000 and D7.',
        'read_1_to_0': 'Ada reads A2000; new RMA on requester Ada and D1.',
        'aer': 'No observed changes in UES/CES/HeaderLog/RootStatus; existing bridge CES/DevSta not newly caused by trial.',
        'write_fail': 'Ada to A2000 remains zero with no new captured PCI status/AER change; sticky read errors already present.',
        'limit': 'No packet capture or runtime PTE proof; RMA does not identify whether UR was generated for unsupported peer routing or a wrong target address.'
    },
    'timing': {'data_done_monotonic': data_done, 'context_exit_monotonic': context_exit,
               'all_allocation_frees_after_data': True,
               'kernel_minus_userspace_seconds_median': offset,
               'kernel_minus_userspace_seconds_min': min(offsets),
               'kernel_minus_userspace_seconds_max': max(offsets),
               'clock_pairs': len(offsets), 'kernel_marker_lines_rate_limited': 19,
               'errors': errors},
    'source_reference': {'url': 'https://cdrdv2-public.intel.com/710723/710723-003.pdf', 'd1': '5.4 PSTS page439 bit13', 'd7': '12.5.4 PSTS page964 bit13'},
    'full_sha256_locally_recomputed': hashes,
    'manifest_hash_matches': checks,
    'libcuda_sha256_from_build_manifest_not_rehashed_in_this_review': manifest['libcuda_sha256'],
    'conclusion': 'The corrected test reproduces the failure, excluding the missing owner synchronization as sole explanation. Bidirectional write-only transport still lacks Ada-to-A2000 write. No claim of hardware impossibility.'
}
(HERE / 'verified-result.json').write_text(json.dumps(output, indent=2) + '\n')
print(json.dumps({'status': output['status'], 'operation_deltas': deltas, 'offset': offset,
                  'earliest_cleanup_error_after_context_ms': errors[0]['after_context_exit_seconds_estimate'] * 1000,
                  'hash_files_verified': len(hashes)}, indent=2))
