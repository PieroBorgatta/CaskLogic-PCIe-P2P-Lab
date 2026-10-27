"""Offline validation of four read-only BAR0 probes, plus qualified host/peer tests."""
from pathlib import Path
import importlib.util
import hashlib

p = Path(__file__).with_name('host_log_validation.py')
if hashlib.sha256(p.read_bytes()).hexdigest() != '31ed723be7650909e2332a7f1099df36c99712b17aafc647830d2e66cdcb897d':
    raise RuntimeError('Host validator changed')
s = importlib.util.spec_from_file_location('qualified_host_validation', str(p))
host = importlib.util.module_from_spec(s)
s.loader.exec_module(host)
require = host.require


def qualify_bar0(raw, kernel):
    rows = []
    for line in kernel.splitlines():
        start = line.find('CASKBAR0 ')
        if start >= 0:
            rows.append(host.base.fields(line[start+len('CASKBAR0 '):]))
    require(len(rows) == 28, 'BAR0 record count differs')
    counts = {stage:sum(r.get('stage') == stage for r in rows)
              for stage in ['cpu_reference','baseline','methods','result','pci','return']}
    require(counts == dict(cpu_reference=2,baseline=4,methods=4,result=4,pci=12,**{'return':2}),
            'BAR0 stages differ')
    results = [r for r in rows if r.get('stage') == 'result']
    require([(int(r['index']),int(r['mode'])) for r in results] == [(1,1),(1,2),(0,1),(0,2)],
            'BAR0 result order differs')
    cases = {int(r['id']):r for line in raw.splitlines() if line.startswith('PHYS_CASE ')
             for r in [host.base.fields(line[len('PHYS_CASE '):]) ]}
    def one(stage, request, mode=None):
        matches = [r for r in rows if r.get('stage') == stage and r.get('request') == request
                   and (mode is None or r.get('mode') == str(mode))]
        require(len(matches) == 1,'BAR0 missing/duplicate '+stage)
        return matches[0]
    output = []
    for index, mode in [(1,1),(1,2),(0,1),(0,2)]:
        request = cases[3 if index else 9]['request']
        ref = one('cpu_reference',request)
        require(ref['executor'] == host.base.BDFS[index] and ref['remote'] == host.base.BDFS[1-index]
                and ref['index'] == str(index) and ref['bar'] == '0' and ref['offset'] == '0'
                and ref['register'] == 'NV_PMC_BOOT_0' and ref['read_only'] == '1','BAR0 reference differs')
        expected = int(ref['expected'],16)
        sentinel = expected ^ 0xffffffff
        address = int(ref['base'],16)
        flags = int(ref['resource_flags'],16)
        require(expected not in (0,0xffffffff) and address and not(address&3) and
                int(ref['length'],16) >= 4 and flags&0x200 and not(flags&0x2000),'Invalid BAR0 resource')
        initial, method, result = [one(stage,request,mode) for stage in ['baseline','methods','result']]
        for r in [initial,method,result]:
            require(r['executor'] == host.base.BDFS[index] and r['index'] == str(index),'BAR0 executor differs')
        require(initial['valid'] == '1' and initial['mismatches'] == '0' and initial['checked_words'] == '1024'
                and int(initial['expected'],16) == sentinel and int(initial['actual'],16) == sentinel,
                'BAR0 destination baseline failed')
        require(method['remote'] == host.base.BDFS[1-index] and int(method['source_phys'],16) == address
                and int(method['destination_phys'],16) and not(int(method['destination_phys'],16)&3)
                and method['bytes'] == '4' and method['class'] == 'c7b5' and int(method['launch'],16) == 0x04003186
                and method['p2p'] == '1' and method['privileged'] == '1' and method['register_offset'] == '0'
                and method['read_only'] == '1','BAR0 method differs')
        actual = int(result['actual'],16)
        require(result['remote'] == host.base.BDFS[1-index] and result['bytes'] == '4'
                and result['checked_words'] == '1024' and result['guard_changed'] == '0'
                and result['source_stable'] == '1' and int(result['cpu_after'],16) == expected
                and int(result['expected'],16) == expected and int(result['sentinel'],16) == sentinel
                and int(result['match']) == int(actual == expected),'BAR0 result/guards differ')
        pci = [r for r in rows if r.get('stage') == 'pci' and r.get('request') == request and r.get('mode') == str(mode)]
        require([r.get('phase') for r in pci] == ['before','after_raw','after_readback']
                and all(r.get('executor') == host.base.BDFS[index] and r.get('read_rc') == '0' for r in pci),
                'BAR0 PCI observations differ')
        output.append({'executor':index,'mode':mode,'expected':ref['expected'],'actual':result['actual'],
                       'match':actual == expected,'guard_words_unchanged':1023,
                       'known_value':actual in (expected,sentinel,0,0xffffffff),
                       'pci_status':[r['pci_status'] for r in pci]})
    for index, case in [(1,3),(0,9)]:
        r = one('return',cases[case]['request'])
        require(r['executor'] == host.base.BDFS[index] and r['index'] == str(index)
                and r['status'] == '0' and r['pending'] == '0','BAR0 completion uncertain')
    return output


def validate_log(raw, ccfg, kernel=''):
    result = host.validate_log(raw,ccfg,kernel)
    result['bar0_controls_qualified'] = False
    if not result['protocol_complete']:
        return result
    try:
        controls = qualify_bar0(raw,kernel)
    except (ValueError,KeyError,TypeError) as exc:
        result.update(status='incomplete_preserved',protocol_complete=False,
                      logs_are_partial_evidence=True,bar0_control_error=str(exc))
        return result
    result.update(bar0_controls_qualified=True,bar0_controls=controls,
                  bar0_read_comparisons=4,bar0_read_passes=sum(r['match'] for r in controls),
                  bar0_read_failures=sum(not r['match'] for r in controls),
                  bar0_values_known=all(r['known_value'] for r in controls),
                  total_comparisons_including_host_and_bar0_controls=20)
    return result
