"""Fixture mirate del clone Traffic2; solo import e funzioni pure locali."""
from pathlib import Path
import ast
import hashlib
import importlib.util
import json

R = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, R / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    old = load('install_native_traffic')
    new = load('install_native_traffic2')
    collector = load('collect_cleanup_traffic2')
    provenance = json.loads((R / 'traffic2-installer-collector-provenance.json').read_text())
    results = []

    def check(name, ok):
        assert ok, name
        results.append({'name': name, 'passed': True})

    for base, clone, changes in [
        ('install_native_traffic.py', 'install_native_traffic2.py', provenance['installer_replacements']),
        ('collect_cleanup_traffic.py', 'collect_cleanup_traffic2.py', provenance['collector_replacements'])
    ]:
        expected = (R / base).read_text()
        for before, after in changes.items():
            expected = expected.replace(before, after)
        check('exact_reviewed_replacements_' + clone, (R / clone).read_text() == expected)
    check('unchanged_firmware_and_payload_guards', new.CCFG == old.CCFG and new.PINNED == old.PINNED
          and new.PARTUUID == old.PARTUUID and new.KERNEL_SHA == old.KERNEL_SHA)
    check('separate_state_and_result_paths', new.STATE.name == 'traffic2-state.json'
          and new.BACKUP.name == 'traffic2-stage-metadata'
          and collector.BACKUP.name == 'native-traffic2-esp-backup'
          and collector.RESULTS.name == 'native-traffic2-results'
          and collector.COLLECTION.name == 'native-traffic2-collection.json')
    originals = {'0000': 'Boot0000* XCP-ng original', '0001': 'Boot0001* UEFI original'}
    line = 'Boot0002* ' + new.LABEL + '\tHD(1,GPT,' + new.PARTUUID + ',0x800,0x1000)/File(' + new.LOADER + ') ' + new.ARGS
    entries = dict(originals, **{'0002': line})
    new.verify_new_entry(entries, originals, '0002')
    check('traffic2_exact_entry_accepted', True)
    for name, changed in [
        ('old_label_rejected', line.replace(new.LABEL, old.LABEL)),
        ('old_loader_rejected', line.replace(new.LOADER, old.LOADER)),
        ('old_initrd_rejected', line.replace(new.ARGS, old.ARGS)),
        ('additional_kernel_argument_rejected', line + ' init=/bin/sh')
    ]:
        rejected = False
        try:
            new.verify_new_entry(dict(originals, **{'0002': changed}), originals, '0002')
        except RuntimeError:
            rejected = True
        check(name, rejected)
    def validation_ast(name):
        tree = ast.parse((R / name).read_text())
        function, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'validate_log']
        return ast.dump(function, include_attributes=False)
    check('log_validation_byte_semantics_unchanged', validation_ast('collect_cleanup_native.py') != validation_ast('collect_cleanup_traffic2.py')
          and validation_ast('collect_cleanup_traffic.py') == validation_ast('collect_cleanup_traffic2.py'))
    actual = R / 'native-traffic-results/result.log'
    if actual.is_file():
        result = collector.validate_log(actual.read_text())
        check('actual_traffic_rc6_collected_without_solution_claim', result['program_rc'] == 6
              and result['qualified_windows'] == 0 and result['failures'] == 2
              and result['P2P_solution_claimed'] is False)
    output = {'status': 'PASS', 'scope': 'Delta locale; nessun main, comando remoto, GPU o scrittura EFI.',
              'fixtures': results, 'installer_sha256': hashlib.sha256((R / 'install_native_traffic2.py').read_bytes()).hexdigest(),
              'collector_sha256': hashlib.sha256((R / 'collect_cleanup_traffic2.py').read_bytes()).hexdigest()}
    (R / 'traffic2-delta-fixtures.json').write_text(json.dumps(output, indent=2) + '\n')
    print(json.dumps({'status': 'PASS', 'fixtures': len(results)}))


if __name__ == '__main__':
    main()
