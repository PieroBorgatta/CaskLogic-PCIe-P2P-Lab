#!/usr/bin/env python3
"""Verifica offline dei log P2PTRC; non accede a dispositivi o rete."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import statistics

KV = re.compile(r'(?:^|\s)([A-Za-z][A-Za-z0-9_]*)=')


def fields(text):
    matches = list(KV.finditer(text))
    return {m.group(1): text[m.end():matches[i+1].start() if i+1 < len(matches) else len(text)].strip()
            for i, m in enumerate(matches)}


def integer(event, key, base=16):
    try:
        return int(event['fields'][key], base)
    except (ValueError, KeyError, TypeError):
        return None


def identity(event, keys):
    return tuple(event['fields'].get(k) for k in keys)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parse(kernel, result):
    events, phases, operations, owners, snapshots, errors = [], [], [], [], [], []
    offsets = []
    for number, line in enumerate(result.splitlines(), 1):
        if line.startswith('CaskLogicPeer '):
            p = fields(line)
            p['line'] = number
            phases.append(p)
        elif line.startswith(('REMOTE_READ ', 'REMOTE_WRITE ')):
            operations.append({'operation': line.split()[0], **fields(line), 'line': number})
        elif line.startswith('OWNER_CHECK '):
            owners.append({**fields(line), 'line': number})
        elif line.startswith('PCIE_SNAPSHOT '):
            snapshots.append({**fields(line), 'line': number})
    for number, line in enumerate(kernel.splitlines(), 1):
        time = re.search(r'\[\s*(\d+\.\d+)\]', line)
        marker = re.search(r'CaskLogicPeer phase=\w+ monotonic=([\d.]+)', line)
        if time and marker:
            offsets.append(float(time[1]) - float(marker[1]))
        m = re.search(r'P2PTRC\s+(\w+)\s+(.*)', line)
        if m:
            events.append({'index': len(events), 'line': number, 'event': m[1],
                           'kernel_time': float(time[1]) if time else None,
                           'fields': fields(m[2]), 'raw': line})
        if 'left-over mappings' in line or 'Assertion failed:' in line or 'Xid ' in line:
            errors.append({'line': number, 'kernel_time': float(time[1]) if time else None, 'raw': line})
    offset = statistics.median(offsets) if offsets else None
    timed_phases = [(float(p['monotonic']), p) for p in phases if 'monotonic' in p]
    for event in events + errors:
        t = event['kernel_time']
        event['monotonic_estimate'] = t - offset if t is not None and offset is not None else None
        previous = [p for pt, p in timed_phases if event['monotonic_estimate'] is not None and pt <= event['monotonic_estimate']]
        event['phase_estimate'] = previous[-1] if previous else None
    return events, phases, operations, owners, snapshots, errors, offsets


def analyze(kernel, result):
    events, phases, operations, owners, snapshots, errors, offsets = parse(kernel, result)
    chains, checks = [], []
    probe_pointers = [{**fields(line), 'line': number} for number, line in enumerate(result.splitlines(), 1)
                      if line.startswith('PROBE_PTR ')]

    def check(name, actual, expected, evidence, required=True):
        available = actual is not None and expected is not None
        entry = {'check': name, 'actual': actual, 'expected': expected,
                 'ok': actual == expected if available else None,
                 'required': required, 'evidence': evidence}
        checks.append(entry)
        return len(checks) - 1

    def nearest_before(event, kind, predicate):
        matches = [e for e in events[:event['index']] if e['event'] == kind and predicate(e)]
        return matches[-1] if matches else None

    for pte in (e for e in events if e['event'] == 'RM_PTE'):
        request = nearest_before(pte, 'RM_REQUEST', lambda e: identity(e, ['client', 'src', 'dst', 'desc']) == identity(pte, ['client', 'src', 'dst', 'desc']))
        chain = {'rm_pte_index': pte['index'], 'request_index': request['index'] if request else None,
                 'check_indexes': [], 'phase_estimate': pte['phase_estimate']}
        ci = chain['check_indexes']
        if request is None:
            ci.append(check('RM_PTE_has_matching_request', None, True, [pte['line']]))
            chains.append(chain)
            continue
        window = nearest_before(request, 'WINDOW_CREATE', lambda e: identity(e, ['mem', 'src', 'dst']) == identity(request, ['mem', 'src', 'dst']))
        chain['window_index'] = window['index'] if window else None
        ci.append(check('RM_dynamic_path', integer(pte, 'dynamic', 10), 1, [pte['line']]))
        ci.append(check('RM_valid_PTE', integer(pte, 'valid', 10), 1, [pte['line']]))
        ci.append(check('RM_writable_PTE', integer(pte, 'readonly', 10), 0, [pte['line']]))
        ci.append(check('RM_decoded_equals_encoded_input', integer(pte, 'decoded'), integer(pte, 'phys_input'), [pte['line']]))
        dma_base, off = integer(pte, 'dma_base'), integer(pte, 'offset')
        ci.append(check('RM_input_equals_dma_plus_offset', integer(pte, 'phys_input'), dma_base + off if dma_base is not None and off is not None else None, [pte['line']]))
        if window:
            address, baroff = integer(window, 'bar1'), integer(window, 'bar1_off')
            ci.append(check('window_phys_equals_BAR1_plus_offset', integer(window, 'window_phys'), address + baroff if address is not None and baroff is not None else None, [window['line']]))
            ci.append(check('RM_dma_equals_window_dma', dma_base, integer(window, 'dma'), [window['line'], pte['line']]))
            mapping = nearest_before(window, 'DMA_MAP', lambda e: integer(e, 'input') == integer(window, 'window_phys') and integer(e, 'output') == integer(window, 'dma'))
            chain['dma_map_index'] = mapping['index'] if mapping else None
            if mapping:
                ci.append(check('DMA_mapping_success', integer(mapping, 'status'), 0, [mapping['line']]))
                begin, end = integer(mapping, 'resource_start'), integer(mapping, 'resource_end')
                start, pages = integer(mapping, 'input'), integer(mapping, 'pages')
                page = integer(mapping, 'os_page', 10)
                ci.append(check('DMA_input_range_within_live_BAR', begin <= start and start + pages * page - 1 <= end if all(x is not None for x in [begin, end, start, pages, page]) else None, True, [mapping['line']]))
                # Native identity or IOMMU translation is evidence, not a forced assumption.
                chain['dma_translation_delta'] = integer(mapping, 'output') - integer(mapping, 'input')
                chain['source_bdf'] = mapping['fields'].get('src')
                chain['owner_bdf'] = mapping['fields'].get('dst')
            else:
                ci.append(check('window_has_matching_DMA_trace', None, True, [window['line']]))
            destroyed = [e for e in events[window['index']+1:pte['index']] if e['event'] == 'WINDOW_DESTROY_BEGIN' and e['fields'].get('id') == window['fields'].get('id')]
            ci.append(check('window_alive_at_PTE_build', not destroyed, True, [window['line'], pte['line']]))
        else:
            ci.append(check('RM_request_has_window_trace', None, True, [request['line']]))
        # Match on RM handle and offset before comparing PTE words, so bad words remain detectable.
        matching_uvm = [e for e in events[pte['index']+1:] if e['event'] == 'UVM_PTE' and e['fields'].get('mem') == request['fields'].get('mem') and integer(e, 'map_offset') == off]
        uvm = matching_uvm[0] if matching_uvm else None
        chain['uvm_pte_index'] = uvm['index'] if uvm else None
        if uvm:
            chain['gpu_va'] = uvm['fields'].get('gpu_va')
            chain['gpu_name'] = uvm['fields'].get('gpu')
            for key in ['raw0', 'raw1', 'entry']:
                base = 10 if key == 'entry' else 16
                ci.append(check('UVM_equals_RM_' + key, integer(uvm, key, base), integer(pte, key, base), [pte['line'], uvm['line']]))
            ci.append(check('UVM_equals_RM_page_size', integer(uvm, 'page'), integer(pte, 'page'), [pte['line'], uvm['line']]))
            submit = next((e for e in events[uvm['index']+1:] if e['event'] == 'UVM_SUBMIT' and identity(e, ['gpu', 'mem', 'gpu_va']) == identity(uvm, ['gpu', 'mem', 'gpu_va'])), None)
            chain['uvm_submit_index'] = submit['index'] if submit else None
            ci.append(check('UVM_submission_success', integer(submit, 'status') if submit else None, 0, [submit['line']] if submit else [uvm['line']]))
            complete = next((e for e in events[uvm['index']+1:] if e['event'] == 'UVM_MAP_COMPLETE' and e['fields'].get('gpu_va') == uvm['fields'].get('gpu_va')), None)
            chain['uvm_complete_index'] = complete['index'] if complete else None
            ci.append(check('UVM_mapping_wait_success', integer(complete, 'status') if complete else None, 0, [complete['line']] if complete else [uvm['line']]))
        else:
            ci.append(check('RM_PTE_has_UVM_copy_trace', None, True, [pte['line']]))
        returned = next((e for e in events[pte['index']+1:] if e['event'] == 'RM_RETURN' and identity(e, ['client', 'mem', 'src']) == identity(request, ['client', 'mem', 'src'])), None)
        chain['rm_return_index'] = returned['index'] if returned else None
        ci.append(check('RM_matching_return_success', integer(returned, 'status') if returned else None, 0, [returned['line']] if returned else [request['line']]))
        # Precise source pointer isn't printed by this unchanged probe. Infer its role only from timed phases.
        phase = chain['phase_estimate'] or {}
        if phase.get('phase') == 'mapping_begin':
            chain['probe_allocation_role'] = 'src: actual peer-read/peer-write target'
            chain['probe_owner_cuda_index'] = phase.get('s')
        elif phase.get('phase') == 'owner_init_ready':
            chain['probe_allocation_role'] = 'dst: local output of read kernel'
            chain['probe_owner_cuda_index'] = phase.get('d')
        else:
            chain['probe_allocation_role'] = 'unresolved: manual temporal inspection required'
        chain['probe_role_source'] = 'phase time alignment; no direct pointer'
        if uvm and probe_pointers:
            va, map_size = integer(uvm, 'gpu_va'), integer(uvm, 'map_size')
            pointer_matches = []
            for row in probe_pointers:
                for pointer, owner in [('src', 's'), ('dst', 'd')]:
                    try:
                        address = int(row[pointer], 16)
                    except (ValueError, KeyError):
                        continue
                    if va is not None and map_size is not None and va <= address < va + map_size:
                        pointer_matches.append({'pointer': pointer, 'address': hex(address),
                                                'owner_cuda_index': row.get(owner), 'probe_line': row['line']})
            chain['direct_probe_pointer_matches'] = pointer_matches
            if len(pointer_matches) == 1:
                match = pointer_matches[0]
                chain['probe_allocation_role'] = ('src: actual peer-read/peer-write target' if match['pointer'] == 'src'
                                                  else 'dst: local output of read kernel')
                chain['probe_owner_cuda_index'] = match['owner_cuda_index']
                chain['probe_role_source'] = 'direct PROBE_PTR address within UVM mapping'
            elif not pointer_matches:
                chain['probe_role_source'] = 'no direct pointer in this UVM mapping; phase inference only'
            else:
                chain['probe_role_source'] = 'ambiguous PROBE_PTR matches; inspect manually'
        chains.append(chain)
    for event in events:
        if event['event'] == 'UVM_MAP_COMPLETE':
            check('UVM_existing_wait_completed', integer(event, 'status'), 0, [event['line']])
        if event['event'] == 'RM_RETURN':
            check('RM_request_success', integer(event, 'status'), 0, [event['line']])
    by_phase = {}
    for item in snapshots:
        by_phase.setdefault(item.get('phase'), {})[item.get('bdf')] = item
    aer_deltas = []
    for phase in ['read_0_to_1', 'write_1_to_0', 'read_1_to_0', 'write_0_to_1']:
        before, after = by_phase.get(phase + '_before', {}), by_phase.get(phase + '_after', {})
        changes = []
        for bdf in before.keys() & after.keys():
            for field in before[bdf].keys() | after[bdf].keys():
                if field not in {'phase', 'monotonic', 'line'} and before[bdf].get(field) != after[bdf].get(field):
                    changes.append({'bdf': bdf, 'field': field, 'before': before[bdf].get(field), 'after': after[bdf].get(field)})
        aer_deltas.append({'operation': phase, 'snapshots_before': len(before), 'snapshots_after': len(after), 'changes': changes})
    page_alignment = []
    for event in events:
        if event['event'] != 'RM_PTE':
            continue
        page = integer(event, 'page')
        for field in ['phys_input', 'decoded', 'dma_base']:
            address = integer(event, field)
            available = address is not None and page is not None and page > 0 and page & (page - 1) == 0
            page_alignment.append({'line': event['line'], 'event_index': event['index'], 'field': field,
                                   'address': address, 'page_size': page,
                                   'remainder': address % page if available else None,
                                   'aligned': address % page == 0 if available else None})
    status = 'trace_incomplete'
    if any(x['ok'] is False for x in checks):
        status = 'mapping_chain_mismatch'
    elif chains and all(x['ok'] is True for x in checks if x['required']):
        status = 'observed_software_mapping_chain_consistent'
    equality_status = status
    if any(x['aligned'] is False for x in page_alignment):
        status = 'PTE_page_alignment_mismatch_requires_resolution'
    return {'status': status, 'event_counts': dict(Counter(e['event'] for e in events)),
            'chain_equality_status': equality_status, 'page_alignment': page_alignment,
            'alignment_interpretation': 'Checks arithmetic alignment to the actual RM_PTE page size, separately from equality of encoded and decoded fields. Hardware handling of a misaligned large-page PTE is not inferred from the raw decoder.',
            'chains': chains, 'checks': checks, 'events': events, 'phases': phases,
            'owners': owners, 'data_operations': operations, 'pcie_changes': aer_deltas, 'probe_pointers': probe_pointers,
            'coverage': {'rm_pte_chains': len(chains), 'window_creates': sum(e['event'] == 'WINDOW_CREATE' for e in events),
                         'owner_checks': len(owners), 'peer_data_comparisons': len(operations),
                         'direct_probe_pointer_rows': len(probe_pointers),
                         'distinct_uvm_virtual_addresses_in_chains': len({c['gpu_va'] for c in chains if c.get('gpu_va')})},
            'kernel_errors': errors, 'clock_alignment': {'sample_count': len(offsets),
                'kernel_minus_monotonic_median': statistics.median(offsets) if offsets else None,
                'spread_seconds': max(offsets) - min(offsets) if offsets else None},
            'limits': ['Software PTE and submission trace is not a hardware page-table readback or a TLP capture.',
                       'Probe pointers use PROBE_PTR when present; otherwise roles are inferred from mapping phases.',
                       'No absent trace or missing status is treated as success.',
                       'No transport correctness is inferred from a successful mapping chain.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    kernel, result = args.directory / 'kernel.log', args.directory / 'result.log'
    report = analyze(kernel.read_text(errors='replace'), result.read_text(errors='replace'))
    report['sources'] = {str(p.resolve()): digest(p) for p in [kernel, result, Path(__file__)]}
    destination = args.output or args.directory / 'pte-chain-validation.json'
    destination.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'events': sum(report['event_counts'].values()),
                      'chains': len(report['chains']), 'failed_checks': sum(x['ok'] is False for x in report['checks']),
                      'missing_checks': sum(x['ok'] is None for x in report['checks']), 'output': str(destination)}))


if __name__ == '__main__':
    main()
