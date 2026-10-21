#!/usr/bin/env python3
"""CPU-only mocked PM tests plus fixed-source integration checks; no hardware."""
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
BASELINE = HERE.parent / 'diagnostic' / 'cask_low_mmio.c'
EXPECTED_BASELINE = '017dc64e2de0b3b11782cbc686e6c4db708022e1d19a88fb20cecaccaed18003'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def body(source, function):
    start = source.index(function + '(')
    start = source.index('{', start)
    depth = 1
    at = start + 1
    while depth:
        if source[at] == '{':
            depth += 1
        elif source[at] == '}':
            depth -= 1
        at += 1
    return source[start:at]

def main():
    source = (HERE / 'cask_low_mmio.c').read_text()
    baseline = BASELINE.read_text()
    inc = (HERE / 'audio_pm.inc').read_text()
    checks = {}
    checks['diagnostic_baseline_unchanged'] = sha(BASELINE) == EXPECTED_BASELINE
    for fn in ['validate', 'detach_tree', 'attach_tree', 'program_config',
               'verify_new_tree', 'rollback', 'write32_verify', 'command_verify']:
        checks['unchanged_' + fn] = body(source, fn) == body(baseline, fn)
    init = body(source, 'low_init')
    checks['platform_before_pm'] = init.index('X86_FEATURE_HYPERVISOR') < init.index('prepare_audio_pm()')
    checks['references_resume_locks_order'] = (init.index('pm_runtime_get_noresume') <
        init.index('prepare_audio_pm()') < init.index('device_lock(') <
        init.index('verify_pm_config_resources()') < init.index('validate()'))
    checks['release_refs_only_unpinned'] = 'if (!pinned)\n        while (pm_refs)\n            pm_runtime_put_noidle' in init
    for fn in ['gate_commands', 'restore_commands']:
        checks['live_guard_before_' + fn] = body(source, fn).index('verify_live_pm_ready()') < body(source, fn).index('command_verify(')
    checks['no_new_raw_pm_config_writes'] = all(term not in inc for term in [
        'pci_write_config', 'pm_runtime_set_active(', 'pm_runtime_disable(', 'device_lock(',
        'current_state =', 'current_state='])
    checks['post_relocation_live_guard'] = 'ret = program_config(false);\n    if (ret)\n        goto failed;\n    ret = verify_live_pm_ready();' in init
    checks['honest_dry_run_token'] = 'activate_audio ? "preflight_ok_pm_ready"' in init
    assert all(checks.values()), checks
    with tempfile.TemporaryDirectory(prefix='cask-pm-fixture-') as tmp:
        binary = Path(tmp) / 'test-audio-pm'
        command = ['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                   '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                   str(HERE / 'test_audio_pm.c'), '-o', str(binary)]
        compile_result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        assert compile_result.returncode == 0, compile_result.stderr
        run = subprocess.run([str(binary)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        assert run.returncode == 0, run.stderr
        tests = json.loads(run.stdout)
    report = {
        'status': 'PASS', 'hardware_access': False, 'network_access': False,
        'mock_tests': tests, 'integration_checks': checks,
        'compiler': subprocess.check_output(['clang', '--version'], universal_newlines=True).splitlines()[0],
        'compile_flags': command[1:7],
        'sanitizer_stderr': run.stderr,
        'sha256': {name: sha(HERE/name) for name in ['cask_low_mmio.c','audio_pm.inc','test_audio_pm.c','run_offline_checks.py']},
        'limits': ['Mocked APIs do not validate real runtime-PM callback behavior.',
                   'Kernel build and hardware relocation are separate checks.',
                   'No hardware test, insmod, or PCI access is performed by this runner.']
    }
    (HERE / 'offline-validation.json').write_text(json.dumps(report, indent=2) + '\n')
    (HERE / 'active-pm.patch').write_text(''.join(difflib.unified_diff(baseline.splitlines(True),source.splitlines(True),fromfile='diagnostic/cask_low_mmio.c',tofile='active-pm/cask_low_mmio.c')))
    print(json.dumps({'status':'PASS','mock_cases':tests['cases'],'integration_checks':len(checks)}))

if __name__ == '__main__':
    main()
