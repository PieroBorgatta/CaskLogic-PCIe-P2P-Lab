"""Pure offline qualification: unchanged peer protocol plus four host controls."""
from pathlib import Path
import hashlib
import importlib.util

BASE_SHA = '29a7aa02bd2bb3b53a56a4b214d148b52984291d4408976ff9712c1d920d1d9b'
p = Path(__file__).with_name('base_log_validation.py')
if hashlib.sha256(p.read_bytes()).hexdigest() != BASE_SHA:
    raise RuntimeError('Base validator differs from qualified ABI2 version')
s = importlib.util.spec_from_file_location('physical_base_validation', str(p))
base = importlib.util.module_from_spec(s)
s.loader.exec_module(base)


def require(value, message):
    if not value:
        raise ValueError(message)


def qualify_host(raw, kernel):
    rows = []
    for line in kernel.splitlines():
        start = line.find('CASKHOST ')
        if start >= 0:
            rows.append(base.fields(line[start+len('CASKHOST '):]))
    def one(stage, request, mode=None):
        found = [r for r in rows if r.get('stage') == stage and r.get('request') == request
                 and (mode is None or r.get('mode') == str(mode))]
        require(len(found) == 1, 'Missing/duplicate host record: '+stage)
        return found[0]
    cases = {}
    for line in raw.splitlines():
        if line.startswith('PHYS_CASE '):
            row = base.fields(line[len('PHYS_CASE '):])
            cases[int(row['id'])] = row
    require(3 in cases and 9 in cases, 'Host controls require both first peer PULL requests')
    expected_order = [(1, 1), (1, 2), (0, 1), (0, 2)]
    results = [r for r in rows if r.get('stage') == 'result']
    require([(int(r['index']), int(r['mode'])) for r in results] == expected_order,
            'Four ordered host results required')
    require(sum(r.get('stage') == 'methods' for r in rows) == 4, 'Four host submissions required')
    require(sum(r.get('stage') == 'baseline' for r in rows) == 4, 'Four host baselines required')
    require(sum(r.get('stage') == 'return' for r in rows) == 2, 'Two host groups required')
    summary = []
    for index, mode in expected_order:
        request = cases[3 if index == 1 else 9]['request']
        expected = (0x6975c23a ^ ((index+1)*0x11a33799) ^ (mode*0x9e3779b9)) & 0xffffffff
        sentinel = expected ^ 0xffffffff
        require(expected not in (0, 0xffffffff, sentinel), 'Invalid synthetic host pattern')
        initial = one('baseline', request, mode)
        method = one('methods', request, mode)
        result = one('result', request, mode)
        for r in (initial, method, result):
            require(r.get('executor') == base.BDFS[index] and int(r['index']) == index,
                    'Host executor differs')
        require(initial['valid'] == '1' and initial['mismatches'] == '0' and
                initial['checked_words'] == '1024' and int(initial['expected'],16) == sentinel and
                int(initial['actual'],16) == sentinel, 'Private local baseline not correct')
        require(method['bytes'] == '4' and method['class'] == 'c7b5' and
                int(method['launch'],16) == 0x04003186 and method['p2p'] == '1' and
                method['privileged'] == '1' and method['no_virtual_fallback'] == '1',
                'Host raw method contract differs')
        source = int(method['source_phys'],16)
        target = int(method['destination_phys'],16)
        require(source and target and source != target and not (source & 3) and not (target & 3),
                'Invalid private physical addresses')
        require(result['bytes'] == '4' and result['checked_words'] == '1024' and
                result['mismatches'] == '0' and result['source_changed'] == '0' and
                result['valid'] == '1' and int(result['expected'],16) == expected and
                int(result['actual'],16) == expected and int(result['sentinel'],16) == sentinel,
                'Host raw source control failed')
        pci = [r for r in rows if r.get('stage') == 'pci' and r.get('request') == request and
               r.get('mode') == str(mode)]
        require([r.get('phase') for r in pci] == ['before','after_baseline','after_raw','after_readback'],
                'Host PCI observations missing/duplicated')
        require(all(r.get('executor') == base.BDFS[index] and r.get('read_rc') == '0' for r in pci),
                'Host PCI read failed')
        require(all(int(r['pci_status'],16) == 0x0010 for r in pci),
                'Host control did not preserve clean initial PCI status')
        summary.append({'executor': index, 'mode': mode, 'expected': format(expected,'08x'),
                        'actual': result['actual'], 'checked_gpu_words': 1024,
                        'source_words_preserved': 1024, 'pci_status_unchanged': True})
    for index, case in [(1,3),(0,9)]:
        r = one('return', cases[case]['request'])
        require(r.get('executor') == base.BDFS[index] and r.get('index') == str(index) and
                r.get('status') == '0' and r.get('pending') == '0', 'Host completion not confirmed')
    return summary


def validate_log(raw, ccfg, kernel=''):
    result = base.validate_log(raw, ccfg, kernel)
    result['core_peer_protocol_complete'] = result['protocol_complete']
    result['host_controls_qualified'] = False
    if not result['protocol_complete']:
        return result
    try:
        host = qualify_host(raw, kernel)
    except (ValueError, KeyError, TypeError) as exc:
        result.update(status='incomplete_preserved', protocol_complete=False,
                      data_all_comparisons_pass=False, logs_are_partial_evidence=True,
                      host_control_error=str(exc))
        return result
    result.update(host_controls_qualified=True, host_controls=host,
                  host_control_comparisons=4, host_control_failures=0,
                  total_comparisons_including_host_controls=16)
    return result
