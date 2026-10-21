#!/usr/bin/env python3
"""Valida offline catene e traduzione enum GMMU→campo PTE della variante coerente."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('p2ptrc', HERE.parent / 'driver-instrumented/analyze_p2ptrc.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate(report):
    checks = []
    for event in report['events']:
        if event['event'] != 'RM_PTE':
            continue
        enum = base.integer(event, 'aperture', 10)
        raw = base.integer(event, 'raw0')
        hardware = (raw >> 1) & 3 if raw is not None else None
        expected_hardware = {3: 3, 4: 2}.get(enum)
        checks.append({'line': event['line'], 'software_enum': enum,
                       'hardware_encoding': hardware, 'expected_hardware_encoding': expected_hardware,
                       'software_enum_is_coherent': enum == 4,
                       'encoding_matches_enum': expected_hardware is not None and hardware == expected_hardware,
                       'valid': base.integer(event, 'valid', 10) == 1,
                       'readonly': base.integer(event, 'readonly', 10),
                       'atomic': base.integer(event, 'atomic', 10),
                       'volatile': base.integer(event, 'volatile', 10),
                       'page_size': base.integer(event, 'page'), 'raw0': event['fields'].get('raw0')})
    return {'checks': checks,
            'exact_four_coherent_writable_valid_PTEs': len(checks) == 4 and all(
                x['software_enum_is_coherent'] and x['encoding_matches_enum'] and x['valid'] and x['readonly'] == 0
                for x in checks),
            'interpretation': 'Software SYS_COH enum4 maps to hardware2; SYS_NONCOH3 maps to hardware3. Peer enum2 is excluded. Encoding evidence is not TLP capture.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    kernel, result = args.directory / 'kernel.log', args.directory / 'result.log'
    report = base.analyze(kernel.read_text(errors='replace'), result.read_text(errors='replace'))
    report['coherent_aperture_validation'] = validate(report)
    report['sources'] = {str(p.resolve()): sha(p) for p in [kernel, result, Path(__file__)]}
    if args.baseline:
        old_kernel, old_result = args.baseline / 'kernel.log', args.baseline / 'result.log'
        old = base.analyze(old_kernel.read_text(errors='replace'), old_result.read_text(errors='replace'))
        old_pte = [e for e in old['events'] if e['event'] == 'RM_PTE']
        new_pte = [e for e in report['events'] if e['event'] == 'RM_PTE']
        comparisons = []
        if len(old_pte) == len(new_pte) == 4:
            for number, (a, b) in enumerate(zip(old_pte, new_pte), 1):
                unchanged = ['src', 'dst', 'fmt', 'entry', 'page', 'readonly', 'volatile', 'atomic', 'valid', 'addr_shift']
                same = {k: {'before': a['fields'].get(k), 'after': b['fields'].get(k),
                            'same': k in a['fields'] and k in b['fields'] and a['fields'][k] == b['fields'][k]} for k in unchanged}
                raw_a, raw_b = base.integer(a, 'raw0'), base.integer(b, 'raw0')
                physical_same = base.integer(a, 'phys_input') == base.integer(b, 'phys_input')
                comparisons.append({'allocation_sequence': number, 'baseline_line': a['line'], 'candidate_line': b['line'],
                                    'fields': same, 'physical_input_unchanged': physical_same,
                                    'raw0_xor': hex(raw_a ^ raw_b) if raw_a is not None and raw_b is not None else None,
                                    'only_raw_aperture_bit_changed_if_same_address': ((raw_a ^ raw_b) == 2) if physical_same and raw_a is not None and raw_b is not None else None})
        report['comparison_to_baseline'] = {'association': 'Four mapping events in allocation order; source/destination fields must match before interpretation',
                                             'baseline_PTE_count': len(old_pte), 'candidate_PTE_count': len(new_pte), 'mappings': comparisons}
        report['sources'].update({str(p.resolve()): sha(p) for p in [old_kernel, old_result]})
    if not report['coherent_aperture_validation']['exact_four_coherent_writable_valid_PTEs']:
        report['status'] = 'coherent_aperture_not_fully_confirmed'
    destination = args.output or args.directory / 'coherent-chain-validation.json'
    destination.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'coherent_PTEs_confirmed': report['coherent_aperture_validation']['exact_four_coherent_writable_valid_PTEs'],
                      'chains': len(report['chains']), 'failed_chain_checks': sum(x['ok'] is False for x in report['checks']),
                      'missing_chain_checks': sum(x['ok'] is None for x in report['checks']), 'output': str(destination)}))


if __name__ == '__main__':
    main()
