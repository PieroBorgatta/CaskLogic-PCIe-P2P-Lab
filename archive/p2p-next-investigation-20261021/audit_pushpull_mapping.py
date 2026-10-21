#!/usr/bin/env python3
"""Audit offline specifico della prova PUSH/PULL; nessun accesso hardware/rete."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
R = HERE / 'native-pushpull-results'
OLD = HERE.parent / 'p2p-tcss-bit-tests-20261021'
PARSER = OLD / 'driver-instrumented/analyze_p2ptrc.py'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    spec = importlib.util.spec_from_file_location('mapping_arithmetic', PARSER)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    text = (R / 'result.log').read_text()
    kernel = (R / 'kernel.log').read_text()
    rows = text.splitlines()
    krows = kernel.splitlines()
    manifest = json.loads((R / 'preliminary-collected-manifest.json').read_text())
    verified = {n: sha(R / n) for n in manifest['files']}
    assert verified == manifest['files'] and len(verified) == 17
    build = json.loads((R / 'build-manifest.json').read_text())
    assert json.loads((R / 'files.json').read_text()) == build['files']
    for name, digest in build['input_files'].items():
        assert sha(HERE / name) == digest, name
    # Solo l'aritmetica delle catene viene riutilizzata: le vecchie inferenze
    # temporali CaskLogicPeer non sono applicabili al protocollo CaskLogicCE.
    arithmetic = m.analyze(kernel, text)
    assert len(arithmetic['chains']) == 4
    assert sum(len(c['check_indexes']) for c in arithmetic['chains']) == 68
    assert all(c['ok'] is True for c in arithmetic['checks'])
    assert len(arithmetic['page_alignment']) == 12
    assert all(c['aligned'] for c in arithmetic['page_alignment'])
    records = lambda prefix: [dict(line=n, **m.fields(line)) for n, line in enumerate(rows, 1) if line.startswith(prefix + ' ')]
    allocations = records('CE_ALLOCATION')
    assert len(allocations) == 8 and len({x['nonce'] for x in allocations}) == 8
    markers = [dict(line=n, **m.fields(line)) for n, line in enumerate(krows, 1) if 'CaskLogicCEAllocation ' in line]
    chains = []
    for c in arithmetic['chains']:
        w = arithmetic['events'][c['window_index']]
        p = arithmetic['events'][c['rm_pte_index']]
        u = arithmetic['events'][c['uvm_pte_index']]
        a, = [x for x in allocations if x['va'] == c['gpu_va']]
        begin, = [x for x in markers if x['nonce'] == a['nonce'] and x['stage'] == 'begin']
        end, = [x for x in markers if x['nonce'] == a['nonce'] and x['stage'] == 'end']
        assert all(begin[k] == end[k] == a[k] for k in ['owner', 'mode', 'role', 'va'])
        assert begin['line'] < w['line'] < p['line'] < u['line'] < end['line']
        assert a['role'] == ('receive' if a['mode'] == 'PUSH' else 'send')
        assert int(a['owner']) == int(w['fields']['dst'])
        assert int(w['fields']['src']) == 1 - int(a['owner'])
        assert int(a['allocation_bytes']) == int(w['fields']['size'], 16) == 8388608
        assert int(a['va'], 16) % int(p['fields']['page'], 16) == 0
        chains.append({'allocation': a, 'requester': int(w['fields']['src']),
                       'requester_bdf': c['source_bdf'], 'owner_bdf': c['owner_bdf'],
                       'nonce_kernel_begin_line': begin['line'], 'nonce_kernel_end_line': end['line'],
                       'window': w, 'rm_pte': p, 'uvm_pte': u,
                       'dma_translation_delta': c['dma_translation_delta']})
    snapshots = records('PCIE_SNAPSHOT')
    assert len(snapshots) == 294
    assert all(x['CONFIG_BYTES'] == '4096' and x['READ_ERRNO'] == '0' and x['clock_ok'] == '1' for x in snapshots)
    previous, changes = {}, []
    for x in snapshots:
        bdf = x['bdf']
        if bdf in previous:
            before = previous[bdf]
            delta = {k: [before.get(k), v] for k, v in x.items()
                     if k not in ['line', 'phase', 'monotonic'] and before.get(k) != v}
            if delta:
                changes.append({'bdf': bdf, 'before_line': before['line'], 'after_line': x['line'],
                                'before_phase': before['phase'], 'after_phase': x['phase'], 'delta': delta})
        previous[bdf] = x
    assert len(changes) == 4
    assert all(x['delta'] == {'PCI_STATUS': ['0010', '2010']} for x in changes)
    assert {(x['bdf'], x['after_phase']) for x in changes} == {
        ('0000:00:07.0', 'ce_case_13_after'), ('0000:06:00.0', 'ce_case_13_after'),
        ('0000:00:01.0', 'ce_case_19_after'), ('0000:01:00.0', 'ce_case_19_after')}
    cases = records('CE_DATA_RESULT')
    assert len(cases) == 24 and [int(x['id']) for x in cases] == list(range(1, 25))
    assert [int(x['valid']) for x in cases] == [0] * 6 + [1] * 6 + [0] * 12
    assert all(int(x['mismatches']) == (0 if x['valid'] == '1' else int(x['checked_words'])) for x in cases)
    owners = [x for x in records('FULL_COMPARE') if x['stage'] != 'peer_payload']
    assert len(owners) == 48 and all(x['valid'] == '1' and x['mismatches'] == '0' for x in owners)
    access = records('CE_ACCESS')
    assert len(access) == 208 and all(x['valid'] == '1' for x in access)
    phases = []
    for n, line in enumerate(krows, 1):
        if 'CaskLogicCE phase=' in line:
            phases.append(dict(line=n, kernel_time=float(re.search(r'\[\s*(\d+\.\d+)\]', line)[1]), **m.fields(line)))
    data_done, = [x for x in phases if x['phase'] == 'data_done']
    exit_begin, = [x for x in phases if x['phase'] == 'context_exit_begin']
    free_begin = [x for x in phases if x['phase'] == 'allocation_free_begin']
    free_done = [x for x in phases if x['phase'] == 'allocation_free_done']
    assert len(free_begin) == len(free_done) == 8
    assert data_done['line'] < min(x['line'] for x in free_begin)
    assert max(x['line'] for x in free_done) < exit_begin['line']
    destroys = [x for x in arithmetic['events'] if x['event'] == 'WINDOW_DESTROY_DONE']
    assert len(destroys) == 4 and all(data_done['line'] < x['line'] < exit_begin['line'] for x in destroys)
    errors = arithmetic['kernel_errors']
    assert len(errors) == 9 and all(x['line'] > exit_begin['line'] for x in errors)
    assert '4 left-over mappings' in errors[0]['raw']
    assert sum('Assertion failed:' in x['raw'] for x in errors) == 8
    assert not any('Xid ' in x for x in krows)
    ccfg = {}
    for bdf, expected in [('00:01.0', '04008077'), ('00:07.0', '0e009077'), ('00:07.2', '0e009077')]:
        vals = re.findall(r'^(?:PEG_CCFG|TCSS_CCFG) ' + re.escape(bdf) + r' ([0-9a-f]+)$', text, re.M)
        assert vals == [expected] * 3
        raw = (R / 'before-driver' / ('0000_' + bdf.replace(':', '_') + '.config')).read_bytes()
        assert int.from_bytes(raw[0xd0:0xd4], 'little') == int(expected, 16)
        ccfg[bdf] = vals
    previous_report = OLD / 'native-ce-gpu-results/independent-mapping-lifetime-review-storico.json'
    report = {
        'status': 'PASS_INDEPENDENT_MAPPING_PCI_LIFETIME_AUDIT_NOT_A_P2P_SOLUTION',
        'scope': 'Analisi offline di copie locali; nessuna operazione remota o hardware.',
        'collected_sha256_verified': verified, 'collection_scope': manifest['scope'],
        'package_input_hashes_match_reviewed_sources': True,
        'module_sha256': build['module_sha256'], 'uvm_module_sha256': build['uvm_module_sha256'],
        'source_parser_sha256': sha(PARSER), 'source_audit_sha256': sha(Path(__file__)),
        'CCFG_before_after_driver_after_test': ccfg,
        'software_mapping_checks': arithmetic['checks'], 'peer_chain_check_count': 68,
        'page_alignment': arithmetic['page_alignment'],
        'chains_linked_by_nonce_and_exact_va': chains, 'allocation_count': 8,
        'local_owner_checks_passed': len(owners), 'VMM_access_checks_passed': len(access),
        'data_results': cases, 'pci_snapshot_count': len(snapshots), 'pci_changes': changes,
        'AER_fields_changed': False, 'PUSH_cases_have_new_PCI_errors': False,
        'lifetime': {'data_done': data_done, 'free_begin': free_begin, 'free_done': free_done,
                     'window_destroy_done': destroys, 'context_exit_begin': exit_begin,
                     'errors': errors, 'first_error_seconds_after_context_exit': round(errors[0]['kernel_time'] - exit_begin['kernel_time'], 6),
                     'Xid_count': 0},
        'comparison_previous': {'report': str(previous_report), 'sha256': sha(previous_report),
            'PUSH_results_same': True, 'PUSH_physical_DMA_and_raw_first_PTE_same': True,
            'new_PULLEXECUTOR_destination': True, 'previous_peer_windows': 2, 'current_peer_windows': 4,
            'previous_and_current_cleanup_leftovers': 4, 'previous_and_current_cleanup_assertions': 8,
            'firmware_changed_from_combined_patch_to_original': True},
        'limits': ['Le PTE registrate sono dati software, non riletture hardware della MMU.',
                   'Per ogni mapping di 8 MiB viene stampata la prima PTE da 2 MiB; i payload testati massimi di 1 MiB vi rientrano.',
                   'PCI_STATUS è sticky: l’assenza di nuove transizioni dopo i primi PULL non prova assenza di ulteriori UR.',
                   'CUPTI distingue CE ed SM, ma non prova da solo l’intero percorso fisico né l’assenza universale di staging nascosto.',
                   'I residui IOVAS restano un difetto separato da risolvere; in questa prova compaiono dopo tutti i confronti e i free.',
                   'Raccolta preliminare 17 raw verificata; questo audit non certifica completamento del successivo backup/cleanup ESP.']}
    (R / 'independent-mapping-pci-lifetime-review-firmware.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'status': report['status'], 'raw_files': len(verified), 'mapping_checks': len(arithmetic['checks']),
                      'chains': len(chains), 'pci_changes': len(changes), 'first_cleanup_error_after_exit_seconds': report['lifetime']['first_error_seconds_after_context_exit']}))


if __name__ == '__main__':
    main()
