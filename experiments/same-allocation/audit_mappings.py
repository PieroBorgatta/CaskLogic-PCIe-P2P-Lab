#!/usr/bin/env python3
"""Offline audit of the same-allocation native run; no hardware access."""
from collections import Counter
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if not __debug__:
        raise SystemExit('This evidence auditor requires assertions; do not use python -O.')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='Directory containing result.log and kernel.log')
    parser.add_argument('--kernel-log', default='kernel.log', help='Kernel log filename inside the evidence directory')
    parser.add_argument('--arithmetic-parser', required=True, type=Path, help='Path to archived analyze_p2ptrc.py')
    parser.add_argument('--output', required=True, type=Path, help='New JSON filename; existing files are refused')
    args = parser.parse_args()
    RESULTS, PARSER = args.directory, args.arithmetic_parser
    spec = importlib.util.spec_from_file_location('historical_arithmetic_only', PARSER)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    text = (RESULTS / 'result.log').read_text()
    kernel_path = RESULTS / args.kernel_log
    kernel = kernel_path.read_text()
    rows, krows = text.splitlines(), kernel.splitlines()
    records = lambda prefix: [dict(line=n, **m.fields(line)) for n, line in enumerate(rows, 1) if line.startswith(prefix + ' ')]
    def unique(rows, description):
        assert len(rows) == 1, (description, len(rows))
        return rows[0]
    phases = []
    markers = []
    for n, line in enumerate(krows, 1):
        if 'CaskLogicCE phase=' in line:
            phases.append(dict(line=n, kernel_time=float(re.search(r'\[\s*(\d+\.\d+)\]', line)[1]), **m.fields(line)))
        if 'CaskLogicCEAllocation ' in line:
            markers.append(dict(line=n, **m.fields(line)))
    allocation_done = unique([p for p in phases if p['phase'] == 'allocations_done'], 'allocations_done')
    data_done = unique([p for p in phases if p['phase'] == 'data_done'], 'data_done')
    context_exit = unique([p for p in phases if p['phase'] == 'context_exit_begin'], 'context_exit_begin')
    arithmetic = m.analyze(kernel, text)
    assert arithmetic['status'] == 'observed_software_mapping_chain_consistent'
    assert len(arithmetic['chains']) == 2
    assert sum(len(c['check_indexes']) for c in arithmetic['chains']) == 34
    assert all(c['ok'] is True for c in arithmetic['checks'])
    assert len(arithmetic['page_alignment']) == 6 and all(c['aligned'] for c in arithmetic['page_alignment'])
    events = arithmetic['events']
    peer_types = ['DMA_MAP', 'WINDOW_CREATE', 'RM_REQUEST', 'RM_PTE', 'RM_RETURN', 'WINDOW_DESTROY_BEGIN', 'WINDOW_DESTROY_DONE']
    assert all(arithmetic['event_counts'].get(t) == 2 for t in peer_types)
    allocations = records('CE_ALLOCATION')
    assert len(allocations) == 2 and {a['owner'] for a in allocations} == {'0', '1'}
    assert len({a['nonce'] for a in allocations}) == len({a['va'] for a in allocations}) == len({a['handle'] for a in allocations}) == 2
    assert len(markers) == 4
    by_owner = {int(a['owner']): a for a in allocations}
    gpu_rows = records('CE_GPU')
    expected_bdfs = {0: '0000:01:00.0', 1: '0000:06:00.0'}
    assert all(g['valid'] == '1' and g['bdf'] == expected_bdfs[int(g['index'])] for g in gpu_rows)
    gpu_uuid = {int(g['index']): g['uuid'] for g in gpu_rows}
    assert len(gpu_uuid) == 2
    def uuid_of(event):
        match = re.search(r'GPU-([0-9a-f-]+)', event['fields'].get('gpu', ''))
        assert match
        return match[1].replace('-', '')
    chains = []
    for chain in arithmetic['chains']:
        window = events[chain['window_index']]
        request = events[chain['request_index']]
        pte = events[chain['rm_pte_index']]
        uvm = events[chain['uvm_pte_index']]
        submit = events[chain['uvm_submit_index']]
        complete = events[chain['uvm_complete_index']]
        returned = events[chain['rm_return_index']]
        dma = events[chain['dma_map_index']]
        allocation = unique([a for a in allocations if a['va'] == chain['gpu_va']], 'VA allocation join')
        owner = int(allocation['owner']); requester = 1 - owner
        begin = unique([x for x in markers if x['nonce'] == allocation['nonce'] and x['stage'] == 'begin'], 'nonce begin')
        end = unique([x for x in markers if x['nonce'] == allocation['nonce'] and x['stage'] == 'end'], 'nonce end')
        assert all(begin[k] == end[k] == allocation[k] for k in ['owner', 'mode', 'role', 'va'])
        assert allocation['mode'] == 'SHARED' and allocation['role'] == 'shared'
        assert int(allocation['allocation_bytes']) == int(window['fields']['size'], 16) == 8388608
        assert int(allocation['granularity']) == int(pte['fields']['page'], 16) == 2097152
        assert int(window['fields']['src']) == requester and int(window['fields']['dst']) == owner
        assert chain['source_bdf'] == expected_bdfs[requester] and chain['owner_bdf'] == expected_bdfs[owner]
        assert uuid_of(uvm) == gpu_uuid[requester]
        assert begin['line'] < dma['line'] < window['line'] < request['line'] < pte['line'] < returned['line'] < uvm['line'] < submit['line'] < complete['line'] < end['line'] < allocation_done['line']
        pf = pte['fields']
        for key, expected in {'offset':'0', 'page':'200000', 'pte_count':'4', 'entry':'16', 'fmt':'2', 'aperture':'3', 'valid':'1', 'readonly':'0', 'atomic':'1', 'volatile':'1', 'dynamic':'1', 'addr_shift':'12'}.items():
            assert pf[key] == expected, (key, pf[key])
        within = [e for e in events if begin['line'] < e['line'] < end['line']]
        for kind in ['UVM_ALLOCATION', 'UVM_PTE', 'UVM_SUBMIT', 'UVM_MAP_COMPLETE']:
            relevant = [e for e in within if e['event'] == kind]
            assert len(relevant) == 2 and all(e['fields']['gpu_va'] == allocation['va'] for e in relevant), kind
        uallocs = [e for e in within if e['event'] == 'UVM_ALLOCATION']
        assert len({e['fields']['user_client'] for e in uallocs}) == len({e['fields']['user_mem'] for e in uallocs}) == 1
        assert {uuid_of(e) for e in uallocs} == set(gpu_uuid.values())
        assert all(e['fields']['length'] == e['fields']['allocation_size'] == '800000' and e['fields']['map_offset'] == '0' for e in uallocs)
        assert unique([e for e in uallocs if uuid_of(e) == gpu_uuid[requester]], 'requester allocation')['fields']['rm_mem'] == window['fields']['mem']
        owner_pte = unique([e for e in within if e['event'] == 'UVM_PTE' and uuid_of(e) == gpu_uuid[owner]], 'owner PTE')
        assert owner_pte['fields']['map_size'] == '800000' and owner_pte['fields']['map_offset'] == '0'
        for e in within:
            if e['event'] in ('UVM_SUBMIT', 'UVM_MAP_COMPLETE', 'RM_RETURN'):
                assert e['fields']['status'] == '0'
        destroys = [e for e in events if e['event'].startswith('WINDOW_DESTROY_') and e['fields']['id'] == window['fields']['id']]
        assert [e['event'] for e in destroys] == ['WINDOW_DESTROY_BEGIN', 'WINDOW_DESTROY_DONE']
        assert all(e['fields']['mem'] == window['fields']['mem'] and data_done['line'] < e['line'] < context_exit['line'] for e in destroys)
        assert int(allocation['va'], 16) % 2097152 == 0
        chains.append({'owner':owner, 'requester':requester, 'allocation':allocation, 'nonce_begin_line':begin['line'], 'nonce_end_line':end['line'],
                       'window':window, 'dma_map':dma, 'rm_request':request, 'rm_pte':pte, 'uvm_peer_pte':uvm,
                       'uvm_owner_pte':owner_pte, 'uvm_submit':submit, 'uvm_complete':complete, 'rm_return':returned,
                       'window_destroy':destroys, 'dma_translation_delta':chain['dma_translation_delta']})
    events_during_cases = [e for e in events if allocation_done['line'] < e['line'] < data_done['line']]
    assert events_during_cases == [], events_during_cases
    free_begin = [p for p in phases if p['phase'] == 'allocation_free_begin']
    free_done = [p for p in phases if p['phase'] == 'allocation_free_done']
    assert len(free_begin) == len(free_done) == 2
    assert data_done['line'] < min(p['line'] for p in free_begin) < max(p['line'] for p in free_done) < context_exit['line']
    for ph in ('owners_ready', 'transfer_begin', 'transfer_complete', 'comparison_done'):
        assert len([p for p in phases if p['phase'] == ph]) == 36
    accesses = records('CE_ACCESS')
    assert len(accesses) == 292
    assert Counter(a['stage'] for a in accesses) == {'created':4,'before_case':144,'after_case':144}
    for a in accesses:
        alloc = by_owner[int(a['owner'])]
        assert a['mode'] == 'SHARED' and a['role'] == 'shared' and a['va'] == alloc['va']
        assert int(a['last_va'],16) == int(a['va'],16) + 8388608 - 1
        assert a['first'] == a['last'] == a['expected'] == '3' and a['valid'] == '1'
        assert a['location_id'] == a['owner'] and a['allocation_type'] == a['location_type'] == '1'
    cases, data, same_cases = records('CE_CASE'), records('CE_DATA_RESULT'), records('SA_CASE')
    assert len(cases) == len(data) == len(same_cases) == 36
    assert [int(c['id']) for c in cases] == list(range(1,37))
    assert len(records('SA_GROUP_BEGIN')) == len(records('SA_GROUP_END')) == 12
    source_ranges=[]; id=0
    for executor in (1,0):
        for size in (4,65536,1048576):
            for engine in ('CE_REQUEST','SM'):
                base=0x6b8b4567 ^ size ^ (0x13579bdf*(executor+1)) ^ (0 if engine == 'CE_REQUEST' else 0x2468ace0)
                for step in range(3):
                    id += 1
                    mode='PULL' if step==1 else 'PUSH'
                    source=1-executor if step==1 else executor; dest=1-source
                    c,d,sa=cases[id-1],data[id-1],same_cases[id-1]
                    expected={'id':str(id),'mode':mode,'executor':str(executor),'s':str(source),'d':str(dest),'bytes':str(size),'engine':engine}
                    assert all(c[k]==d[k]==v for k,v in expected.items())
                    assert c['src']==by_owner[source]['va'] and c['dst']==by_owner[dest]['va']
                    assert all(sa[f'buffer{o}']==by_owner[o]['va'] and sa[f'handle{o}']==by_owner[o]['handle'] for o in (0,1))
                    assert sa['id']==str(id) and sa['group']==str((id-1)//3+1) and sa['step']==('PUSH_BEFORE','PULL','PUSH_AFTER')[step]
                    seed=base ^ ((id*0x9e3779b9)&0xffffffff)
                    assert c['seed']==f'{seed:08x}'
                    words=size//4; lo=seed & ~(words-1)
                    source_ranges.append((lo,lo+words))
                    assert size <= 2097152
                    good=mode=='PUSH' and executor==1
                    assert d['valid']==str(int(good)) and int(d['mismatches'])==(0 if good else words)
                    assert d['direct_route_proven']=='0'
    assert all(max(a[0],b[0]) >= min(a[1],b[1]) for i,a in enumerate(source_ranges) for b in source_ranges[i+1:])
    full=records('FULL_COMPARE'); init=[x for x in full if x['stage']!='peer_payload']
    assert len(full)==108 and len(init)==72 and all(x['valid']=='1' and x['mismatches']=='0' for x in init)
    trace=records('CUPTI_CASE_RESULT')
    assert len(trace)==36 and [int(c['id']) for c in trace]==list(range(1,37))
    assert all(c['metadata_valid']==c['coverage_complete']=='1' and c['unattributed']==c['host_copies']=='0' for c in trace)
    assert sum(c['ce_observed']=='1' for c in trace)==18
    assert sum(c['engine']=='SM' and c['kernels']=='1' and c['copies']=='0' for c in trace)==18
    summary=unique(records('CUPTI_SUMMARY'),'CUPTI summary')
    assert all(summary[k]==v for k,v in {'trace_complete':'1','cases':'36','ce_cases':'18','ce_observed':'18','sm_observed':'18','dropped':'0','errors':'0','direct_route_proven':'0'}.items())
    final=unique(records('CE_PROGRAM_END'),'program end')
    assert all(final[k]==v for k,v in {'protocol_complete':'1','comparisons':'36','failures':'24','rc':'5'}.items())
    snapshots=records('PCIE_SNAPSHOT')
    assert len(snapshots)==438
    assert all(s['CONFIG_BYTES']=='4096' and s['READ_ERRNO']=='0' and s['clock_ok']=='1' for s in snapshots)
    previous={}; changes=[]
    for s in snapshots:
        if s['bdf'] in previous:
            b=previous[s['bdf']]
            delta={k:[b.get(k),v] for k,v in s.items() if k not in ('line','phase','monotonic') and b.get(k)!=v}
            if delta:changes.append({'bdf':s['bdf'],'before_phase':b['phase'],'after_phase':s['phase'],'before_line':b['line'],'after_line':s['line'],'delta':delta})
        previous[s['bdf']]=s
    errors=arithmetic['kernel_errors']
    assert len(errors)==9 and all(e['line']>context_exit['line'] for e in errors)
    assert '4 left-over mappings' in errors[0]['raw'] and sum('Assertion failed:' in e['raw'] for e in errors)==8
    assert not any('Xid ' in line for line in krows)
    assert not any(re.search(r'(messages dropped|callbacks suppressed|printk.*dropped)',line,re.I) for line in krows)
    ccfg={}
    for bdf in ('00:01.0','00:07.0','00:07.2'):
        ccfg[bdf]=re.findall(r'^(?:PEG_CCFG|TCSS_CCFG) '+re.escape(bdf)+r' ([0-9a-f]+)$',text,re.M)
    report={'status':'PASS_SAME_ALLOCATION_SOFTWARE_MAPPING_AUDIT_NOT_P2P_SOLUTION',
            'scope':'Offline audit of supplied native logs only; no SSH or hardware access. CUPTI per-case recorded classifications cross-checked; raw correlation reconstruction is a separate audit.',
            'source_hashes':{'result.log':sha(RESULTS/'result.log'),args.kernel_log:sha(kernel_path),'audit_parser':sha(Path(__file__)),'historical_arithmetic_parser':sha(PARSER)},
            'checks':{'peer_chains':2,'peer_chain_arithmetic_checks':34,'total_arithmetic_checks':len(arithmetic['checks']),'mapping_mutation_events_during_cases':len(events_during_cases),'allocation_count':2,'nonce_markers':4,'access_checks':292,'initialization_checks':72,'comparisons':36,'passing_comparisons':12,'failing_comparisons':24,'ce_observed':18,'sm_observed':18,'dropped':0,'trace_errors':0,'pci_snapshots':438,'unique_active_source_pattern_sets':36,'source_pattern_value_sets_pairwise_disjoint':True},
            'chains':chains,'software_arithmetic_checks':arithmetic['checks'],'page_alignment':arithmetic['page_alignment'],
            'case_data':data,'PCI_changes':changes,'CCFG_readbacks':ccfg,
            'lifetime':{'allocations_done':allocation_done,'data_done':data_done,'free_begin':free_begin,'free_done':free_done,'context_exit_begin':context_exit,'kernel_errors':errors,'first_teardown_error_after_context_exit_seconds':round(errors[0]['kernel_time']-context_exit['kernel_time'],6),'Xid_count':0},
            'limits':['Same persistent software allocations and peer-window/PTE chains are established for these cases; this is not a hardware MMU or BAR1 mapping readback.',
                      'Only the first PTE is printed per allocation; maximum tested payload is 1 MiB and fits the observed first 2 MiB page.',
                      'CUPTI activity and callback metadata do not prove the complete physical TLP path or exclude every internal staging route.',
                      'PCI_STATUS is sticky; absence of later transitions does not exclude repeated Unsupported Requests.',
                      'The unchanged-direction result excludes the previous separate-allocation/window explanation for this run; it does not localize requester, fabric, bridge or mapping implementation.',
                      'Kernel teardown defects persist but are observed after all completed data comparisons and window destruction.',
                      'Raw payload word classification is validated by the separate payload audit; this audit cross-checks full-comparison counters.']}
    destination=args.output
    with destination.open('x') as f:json.dump(report,f,indent=2);f.write('\n')
    print(json.dumps({'status':report['status'],'checks':report['checks'],'PCI_changes':changes,'CCFG_readbacks':ccfg,'first_cleanup_error_after_exit':report['lifetime']['first_teardown_error_after_context_exit_seconds'],'report':str(destination)},indent=2))


if __name__=='__main__':main()
