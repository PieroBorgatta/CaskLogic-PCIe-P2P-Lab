#!/usr/bin/env python3
"""Ricalcolo locale dei campioni NVML e audit mapping/PCI/durata allocazioni."""
from pathlib import Path
import hashlib
import importlib.util
import json
import re
import statistics
import sys

HERE = Path(__file__).resolve().parent
OLD = HERE.parent / 'p2p-tcss-bit-tests-20261021'


def main():
    result = HERE / (sys.argv[1] if len(sys.argv) > 1 else 'native-traffic-results')
    parser = OLD / 'driver-instrumented/analyze_p2ptrc.py'
    spec = importlib.util.spec_from_file_location('mapping_math', parser)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    collected = json.loads((result / 'collected-sha256.json').read_text())
    assert len(collected) == 17 and all(sha(result / n) == digest for n, digest in collected.items())
    raw = (result / 'result.log').read_text()
    kernel = (result / 'kernel.log').read_text()
    rows = raw.splitlines()
    records = lambda prefix: [dict(line=n, **m.fields(x)) for n, x in enumerate(rows, 1) if x.startswith(prefix + ' ')]
    mapping = m.analyze(kernel, raw)
    assert len(mapping['chains']) == 2 and all(x['ok'] is True for x in mapping['checks'])
    assert all(x['aligned'] for x in mapping['page_alignment'])
    allocations = records('TRAFFIC_ALLOCATION')
    assert len(allocations) == 4 and len({x['nonce'] for x in allocations}) == 4
    markers = [dict(line=n, **m.fields(x)) for n, x in enumerate(kernel.splitlines(), 1) if 'CaskLogicTrafficAllocation ' in x]
    chains = []
    for c in mapping['chains']:
        w = mapping['events'][c['window_index']]
        p = mapping['events'][c['rm_pte_index']]
        u = mapping['events'][c['uvm_pte_index']]
        a, = [x for x in allocations if x['va'] == c['gpu_va']]
        begin, = [x for x in markers if x['nonce'] == a['nonce'] and x['stage'] == 'begin']
        end, = [x for x in markers if x['nonce'] == a['nonce'] and x['stage'] == 'end']
        assert a['role'] == 'receive'
        assert all(begin[k] == end[k] == a[k] for k in ['owner', 'role', 'va'])
        assert begin['line'] < w['line'] < p['line'] < u['line'] < end['line']
        # L'ordine RM non è l'ordine CUDA: NVML può inizializzare le GPU
        # nell'ordine opposto. Legare i ruoli a BDF/GPU-ID e nonce+VA.
        bdfs = ['0000:01:00.0', '0000:06:00.0']
        gpuids = ['100', '600']
        owner = int(a['owner'])
        assert c['owner_bdf'] == bdfs[owner] and c['source_bdf'] == bdfs[1 - owner]
        assert w['fields']['dst_gpu_id'] == gpuids[owner] and w['fields']['src_gpu_id'] == gpuids[1 - owner]
        chains.append({'allocation': a, 'window': w, 'rm_pte': p, 'uvm_pte': u,
                       'owner_bdf': c['owner_bdf'], 'requester_bdf': c['source_bdf'],
                       'begin_line': begin['line'], 'end_line': end['line']})
    windows = records('TRAFFIC_WINDOW')
    sampler = records('NVML_SAMPLER_END')
    samples = records('NVML_SAMPLE')
    logged_stats = records('NVML_STATS')
    data = records('TRAFFIC_DATA_RESULT')
    assert len(windows) == len(sampler) == len(data) == 4
    all_stats, computed_qualified = [], 0
    for window, end, datum in zip(windows, sampler, data):
        phase = window['id']
        assert phase == end['phase'] == datum['id']
        start, finish = int(window['begin_ns']), int(window['end_ns'])
        began = int(end['started_ns'])
        ss = [x for x in samples if x['phase'] == phase]
        assert len(ss) == int(end['samples'])
        groups = {(stage, str(device), counter): [] for stage in ['BASELINE_QUIET', 'ACTIVE_INTERIOR', 'TAIL'] for device in range(2) for counter in ['TX', 'RX']}
        for x in ss:
            b, e = int(x['begin_ns']), int(x['end_ns'])
            assert b <= e and int(x['valid']) == int(x['rc'] == '0')
            interior = x['stage'] == 'ACTIVE' and b >= start + 40000000 and e <= finish
            quiet = x['stage'] == 'BASELINE' and b >= began + 40000000 and e <= start
            assert int(x['interior']) == interior and int(x['baseline_quiet']) == quiet
            stage = 'ACTIVE_INTERIOR' if interior else 'BASELINE_QUIET' if quiet else 'TAIL' if x['stage'] == 'TAIL' else None
            if stage:
                groups[(stage, x['device'], x['counter'])].append(x)
        valid = end['overflow'] == end['exception'] == '0' and all(x['rc'] == '0' for x in ss)
        for (stage, device, counter), group in groups.items():
            values = [int(x['value_kBps']) for x in group if x['rc'] == '0']
            invalid = len(group) - len(values)
            logged, = [x for x in logged_stats if (x['phase'], x['stage'], x['device'], x['counter']) == (phase, stage, device, counter)]
            mean = statistics.mean(values) if values else -1.0
            assert int(logged['valid_count']) == len(values) and int(logged['invalid_count']) == invalid
            assert abs(float(logged['mean_kBps']) - mean) <= 0.000501
            assert int(logged['min_kBps']) == (min(values) if values else 4294967295)
            assert int(logged['max_kBps']) == (max(values) if values else 4294967295)
            if stage != 'TAIL':
                valid = valid and len(values) >= 5 and invalid == 0
            all_stats.append({'phase': int(phase), 'stage': stage, 'device': int(device), 'counter': counter,
                              'count': len(values), 'invalid': invalid, 'mean_kBps': mean,
                              'min_kBps': min(values) if values else None, 'max_kBps': max(values) if values else None})
        assert int(end['valid']) == int(datum['sampling_valid']) == valid
        duration = finish - start
        duration_valid = 1200000000 <= duration <= 5000000000 and window['budget_exhausted'] == '0'
        assert int(datum['duration_valid']) == duration_valid and int(window['duration_ns']) == duration
        assert int(window['sampler_joined_ns']) >= finish
        computed_qualified += bool(valid and duration_valid)
    summary, = records('TRAFFIC_PROGRAM_END')
    assert int(summary['qualified_windows']) == computed_qualified
    owners = [x for x in records('FULL_COMPARE') if x['stage'] in ['source_initialized', 'destination_poisoned']]
    assert len(owners) == 8 and all(x['valid'] == '1' for x in owners)
    assert [x['valid'] for x in data] == ['0', '0', '1', '1']
    snapshots = records('PCIE_SNAPSHOT')
    assert len(snapshots) == 54
    assert all(x['CONFIG_BYTES'] == '4096' and x['READ_ERRNO'] == '0' for x in snapshots)
    previous, changes = {}, []
    for x in snapshots:
        bdf = x['bdf']
        if bdf in previous:
            diff = {k: [previous[bdf].get(k), value] for k, value in x.items() if k not in ['line', 'phase', 'monotonic'] and previous[bdf].get(k) != value}
            if diff:
                changes.append({'bdf': bdf, 'line': x['line'], 'phase': x['phase'], 'changes': diff})
        previous[bdf] = x
    phases = []
    for n, line in enumerate(kernel.splitlines(), 1):
        if 'CaskLogicTraffic phase=' in line:
            phases.append(dict(line=n, kernel_time=float(re.search(r'\[\s*(\d+\.\d+)\]', line)[1]), **m.fields(line)))
    done, = [x for x in phases if x['phase'] == 'data_done']
    exit_begin, = [x for x in phases if x['phase'] == 'context_exit_begin']
    frees = [x for x in phases if x['phase'] in ['allocation_free_begin', 'allocation_free_done']]
    assert len(frees) == 8 and all(done['line'] < x['line'] < exit_begin['line'] for x in frees)
    destroys = [x for x in mapping['events'] if x['event'] == 'WINDOW_DESTROY_DONE']
    assert len(destroys) == 2 and all(done['line'] < x['line'] < exit_begin['line'] for x in destroys)
    assert all(x['line'] > exit_begin['line'] for x in mapping['kernel_errors'])
    ccfg = {}
    for bdf, expected in [('00:01.0', '04008077'), ('00:07.0', '0e009077'), ('00:07.2', '0e009077')]:
        vals = re.findall(r'^(?:PEG_CCFG|TCSS_CCFG) ' + re.escape(bdf) + r' ([0-9a-f]+)$', raw, re.M)
        assert vals == [expected] * 3
        ccfg[bdf] = vals
    report = {'status': 'PASS_INDEPENDENT_AUDIT_DATA_FAILURE_PERSISTS', 'program_rc': int(summary['rc']),
              'collected_sha256_verified': collected, 'NVML_qualified_windows_recomputed': computed_qualified,
              'NVML_raw_samples_recomputed': len(samples), 'NVML_stats_recomputed': all_stats,
              'NVML_every_return_code_success': all(x['rc'] == '0' for x in samples),
              'windows': windows, 'data_results': data, 'owner_checks_passed': len(owners),
              'mapping_chains': chains, 'mapping_checks': mapping['checks'], 'page_alignment': mapping['page_alignment'],
              'pci_snapshot_count': len(snapshots), 'pci_changes': changes, 'CCFG': ccfg,
              'lifetime': {'data_done': done, 'frees': frees, 'window_destroy_done': destroys,
                           'context_exit_begin': exit_begin, 'kernel_errors': mapping['kernel_errors']},
              'limits': ['Qualifica NVML distinta dal confronto dei dati; se zero finestre qualificate non presentare un confronto baseline come validato.',
                         'Log PTE software, nessuna rilettura MMU hardware; contatori PCIe aggregati e non traccia TLP.',
                         'Nessuna certificazione CE in questa variante; nessuna localizzazione TCSS/ASMedia deducibile dalla sola NVML.'],
              'audit_source_sha256': sha(Path(__file__))}
    (result / 'independent-mapping-pci-nvml-review-firmware.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'status': report['status'], 'rc': report['program_rc'], 'qualified': computed_qualified,
                      'samples': len(samples), 'mapping_checks': len(mapping['checks']), 'pci_changes': changes,
                      'kernel_errors': len(mapping['kernel_errors'])}))


if __name__ == '__main__':
    main()
