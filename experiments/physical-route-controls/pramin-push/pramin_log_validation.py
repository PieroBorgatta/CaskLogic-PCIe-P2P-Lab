"""Qualify private-page PRAMIN PUSH separately from the unchanged peer suite."""
from pathlib import Path
import hashlib
import importlib.util

p = Path(__file__).with_name('bar0_log_validation.py')
if hashlib.sha256(p.read_bytes()).hexdigest() != 'c8c5f97b4b189d3b3530020e644eeae6b3ac22d4a2edfb4ccad40d32acffceee':
    raise RuntimeError('BAR0 validator differs')
s = importlib.util.spec_from_file_location('qualified_bar0_validation', str(p))
bar0 = importlib.util.module_from_spec(s)
s.loader.exec_module(bar0)
require = bar0.require
base = bar0.host.base


def pattern(index, mode, source):
    return ((0x416ba372 if source else 0xa73295c1) ^ ((index+1)*0x11889933) ^ (mode*0x517cc1b7)) & 0xffffffff


def qualify_pramin(raw, kernel):
    rows = [base.fields(line.split('CASKPRAMIN ',1)[1]) for line in kernel.splitlines() if 'CASKPRAMIN ' in line]
    require(len(rows) == 36, 'PRAMIN record count differs')
    counts = {stage:sum(r.get('stage') == stage for r in rows)
              for stage in ['reference','baseline','window','methods','restored','result','pci','return']}
    require(counts == dict(reference=2,baseline=4,window=4,methods=4,restored=4,result=4,pci=12,**{'return':2}), 'PRAMIN stages differ')
    results = [r for r in rows if r.get('stage') == 'result']
    order = [(1,1),(1,2),(0,1),(0,2)]
    require([(int(r['index']),int(r['mode'])) for r in results] == order,'PRAMIN order differs')
    cases = {int(r['id']):r for line in raw.splitlines() if line.startswith('PHYS_CASE ')
             for r in [base.fields(line[len('PHYS_CASE '):]) ]}
    def one(stage,request,mode=None):
        selected = [r for r in rows if r.get('stage') == stage and r.get('request') == request and
                    (mode is None or r.get('mode') == str(mode))]
        require(len(selected) == 1,'PRAMIN missing/duplicate '+stage)
        return selected[0]
    output = []
    for index,mode in order:
        request = cases[3 if index else 9]['request']
        ref = one('reference',request)
        require(ref['executor'] == base.BDFS[index] and ref['remote'] == base.BDFS[1-index] and ref['index'] == str(index), 'PRAMIN reference identity differs')
        b = int(ref['base'],16); length = int(ref['length'],16); flags = int(ref['resource_flags'],16)
        target = int(ref['target_vid'],16); source = int(ref['source_vid'],16)
        offset = int(ref['alias_offset'],16); dest = int(ref['alias_phys'],16)
        require(ref['bar'] == '0' and ref['window_register'] == '1700' and ref['private_target'] == '1' and ref['bytes'] == '4' and
                b > 0 and length >= 0x800000 and flags&0x200 and not(flags&0x2000) and
                target > 0 and not(target&0xfff) and target>>16 <= 0xffffff and source > 0 and not(source&3) and
                offset == 0x700000+(target&0xffff) and dest == b+offset and offset+4096 <= length,'PRAMIN private alias differs')
        initial,window,method,restored,result = [one(stage,request,mode) for stage in ['baseline','window','methods','restored','result']]
        for r in [initial,window,method,restored,result]:
            require(r['executor'] == base.BDFS[index] and r['index'] == str(index),'PRAMIN executor differs')
        expected = pattern(index,mode,True); sentinel = pattern(index,mode,False)
        require(initial['checked_words'] == '1024' and initial['source_mismatches'] == '0' and initial['target_mismatches'] == '0' and initial['valid'] == '1' and
                int(initial['expected'],16) == expected and int(initial['sentinel'],16) == sentinel,'PRAMIN baseline failed')
        old = int(window['old'],16); new = (old & ~0x03ffffff) | (target>>16)
        require(old != 0xffffffff and int(window['programmed'],16) == new and int(window['observed'],16) == new and
                window['alias_checked_words'] == '16' and window['alias_mismatches'] == '0','PRAMIN alias unproven')
        require(method['remote'] == base.BDFS[1-index] and int(method['source_phys'],16) == source and int(method['destination_phys'],16) == dest and
                method['source_mode'] == '0' and method['destination_mode'] == str(mode) and method['bytes'] == '4' and method['class'] == 'c7b5' and
                int(method['launch'],16) == 0x04003186 and method['p2p'] == '1' and method['privileged'] == '1' and method['host_relay'] == '0','PRAMIN method differs')
        require(int(restored['old'],16) == old and int(restored['restored'],16) == old and int(restored['observed_during'],16) == new and
                restored['alias_guard_changed'] == '0','PRAMIN window not restored')
        actual = int(result['actual'],16)
        require(result['remote'] == base.BDFS[1-index] and result['bytes'] == '4' and result['checked_words'] == '1024' and
                int(result['expected'],16) == expected and int(result['sentinel'],16) == sentinel and int(result['alias_actual'],16) == actual and
                int(restored['alias_actual'],16) == actual and int(result['match']) == int(actual == expected) and
                int(result['alias_match']) == int(actual == expected) and result['guard_changed'] == '0' and
                result['alias_guard_changed'] == '0' and result['source_changed'] == '0','PRAMIN result/guards differ')
        pci = [r for r in rows if r.get('stage') == 'pci' and r.get('request') == request and r.get('mode') == str(mode)]
        require([r.get('phase') for r in pci] == ['before','after_raw','after_readback'] and
                all(r['executor'] == base.BDFS[index] and r['read_rc'] == '0' for r in pci),'PRAMIN PCI evidence differs')
        output.append(dict(executor=index,mode=mode,expected=format(expected,'08x'),actual=result['actual'],
                           match=actual == expected,known_value=actual in [expected,sentinel,0,0xffffffff],
                           target_guard_words_unchanged=1023,source_words_preserved=1024,window_restored=True))
    for index,case in [(1,3),(0,9)]:
        r = one('return',cases[case]['request'])
        require(r['executor'] == base.BDFS[index] and r['index'] == str(index) and r['status'] == '0' and r['pending'] == '0','PRAMIN completion uncertain')
    return output


def validate_log(raw,ccfg,kernel=''):
    result = bar0.validate_log(raw,ccfg,kernel)
    result['pramin_controls_qualified'] = False
    if not result['protocol_complete']:
        return result
    try:
        controls = qualify_pramin(raw,kernel)
    except (ValueError,KeyError,TypeError) as exc:
        result.update(status='incomplete_preserved',protocol_complete=False,logs_are_partial_evidence=True,pramin_error=str(exc))
        return result
    result.update(pramin_controls_qualified=True,pramin_controls=controls,pramin_comparisons=4,
                  pramin_passes=sum(r['match'] for r in controls),pramin_failures=sum(not r['match'] for r in controls),
                  pramin_values_known=all(r['known_value'] for r in controls),total_comparisons_including_all_controls=24,
                  production_transport_proven=False)
    return result
