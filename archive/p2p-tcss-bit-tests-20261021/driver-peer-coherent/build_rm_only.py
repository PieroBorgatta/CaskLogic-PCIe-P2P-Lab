#!/usr/bin/env python3
"""Ricostruisce RM da archivio verificato; copia UVM invariato. Solo CPU, nessuna installazione."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from strict_patch import apply_file

HERE = Path(__file__).resolve().parent
KERNEL = '7.0.0-38-generic'


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(part)
    return value.hexdigest()


def require_hash(path, expected):
    actual = sha(path)
    if actual != expected:
        raise RuntimeError('SHA256 diverso: ' + str(path) + ': ' + actual)
    return actual


def capture(command):
    done = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    return {'command': command, 'returncode': done.returncode, 'output': done.stdout}


def rm_exports(path):
    exports = {}
    for line in path.read_text().splitlines():
        fields = line.split()
        if len(fields) >= 4 and Path(fields[2]).name == 'nvidia':
            if fields[1] in exports:
                raise RuntimeError('Simbolo RM duplicato: ' + fields[1])
            exports[fields[1]] = {'crc': fields[0], 'export_type': fields[3],
                                  'namespace': fields[4] if len(fields) > 4 else ''}
    if not exports:
        raise RuntimeError('Nessun export RM: ' + str(path))
    return exports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--baseline-build', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='Directory nuova, mai sovrascritta')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--build', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.jobs <= 32:
        parser.error('--jobs deve essere fra 1 e 32')
    profile = json.loads((HERE / 'manifest.json').read_text())
    helper = HERE.parent / 'driver-instrumented' / 'prepare_and_build.py'
    source_manifest = helper.with_name('source-manifest.json')
    require_hash(helper, profile['baseline_builder_sha256'])
    require_hash(source_manifest, profile['baseline_source_manifest_sha256'])
    require_hash(args.archive, profile['archive_sha256'])
    require_hash(HERE / 'peer-coherent.patch', profile['patch_sha256'])
    require_hash(HERE / 'strict_patch.py', profile['strict_patch_sha256'])
    require_hash(helper.with_name('strict_patch.py'), profile['strict_patch_sha256'])
    baseline_file = args.baseline_build / 'build-manifest.json'
    baseline = json.loads(baseline_file.read_text())
    if baseline['status'] != 'built_not_installed' or baseline['build_returncode'] != 0:
        raise RuntimeError('Baseline non compilata correttamente')
    if baseline['source_manifest_sha256'] != profile['baseline_source_manifest_sha256']:
        raise RuntimeError('Manifest sorgenti baseline inatteso')
    for name, expected in [('nvidia.ko', profile['baseline_nvidia_sha256']),
                           ('nvidia-uvm.ko', profile['baseline_uvm_sha256'])]:
        require_hash(args.baseline_build / 'modules' / name, expected)
    baseline_symvers = Path(baseline['source_root']) / 'kernel-open/Module.symvers'
    expected_exports = rm_exports(baseline_symvers)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    evidence = {'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'profile': profile, 'builder_sha256': sha(__file__),
                'baseline_build': str(args.baseline_build.resolve()),
                'baseline_manifest_sha256': sha(baseline_file),
                'baseline_symvers_sha256': sha(baseline_symvers),
                'rm_export_count': len(expected_exports),
                'build_requested': args.build, 'hardware_operations': False,
                'baseline_tree_reused': False}
    try:
        prepare = [sys.executable, str(helper), '--archive', str(args.archive.resolve()),
                   '--output', str(output / 'clean-baseline')]
        evidence['prepare_command'] = prepare
        with (output / 'prepare.log').open('w') as stream:
            done = subprocess.run(prepare, stdout=stream, stderr=subprocess.STDOUT, check=False)
        evidence['prepare_returncode'] = done.returncode
        evidence['prepare_log_sha256'] = sha(output / 'prepare.log')
        if done.returncode:
            raise RuntimeError('Ricostruzione pulita fallita: prepare.log')
        clean_manifest_path = output / 'clean-baseline/build-manifest.json'
        clean = json.loads(clean_manifest_path.read_text())
        if clean['status'] != 'prepared':
            raise RuntimeError('Stato ricostruzione inatteso')
        root = Path(clean['source_root'])
        expected = json.loads(source_manifest.read_text())['instrumented_subset']
        if clean['instrumented_verified'] != expected or baseline['instrumented_verified'] != expected:
            raise RuntimeError('Identità baseline strumentata differente')
        for name, digest in expected.items():
            require_hash(root / name, digest)
        target = root / profile['source_path']
        require_hash(target, profile['preimage_sha256'])
        apply_file(root, HERE / 'peer-coherent.patch', profile['source_path'])
        require_hash(target, profile['candidate_sha256'])
        evidence.update(source_root=str(root), clean_manifest_sha256=sha(clean_manifest_path),
                        source_sha256=sha(target), instrumented_baseline_verified=expected,
                        status='prepared_not_built')
        if args.build:
            if not (Path('/lib/modules') / KERNEL / 'build').is_dir():
                raise RuntimeError('Header kernel mancanti')
            evidence['toolchain'] = [capture(['uname', '-a']), capture(['cc', '--version']),
                                     capture(['ld', '--version']), capture(['make', '--version'])]
            keys = ['CC', 'CXX', 'LD', 'HOSTCC', 'HOSTCXX', 'CFLAGS', 'CPPFLAGS',
                    'LDFLAGS', 'MAKEFLAGS', 'NV_KERNEL_MODULES', 'NV_VERBOSE']
            evidence['build_environment'] = {k: os.environ[k] for k in keys if k in os.environ}
            command = ['make', '-j' + str(args.jobs), 'NV_VERBOSE=1',
                       'KERNEL_UNAME=' + KERNEL, 'NV_KERNEL_MODULES=nvidia', 'modules']
            evidence['build_command'] = command
            with (output / 'build.log').open('w') as stream:
                done = subprocess.run(command, cwd=root, stdout=stream, stderr=subprocess.STDOUT, check=False)
            evidence['build_returncode'] = done.returncode
            evidence['build_log_sha256'] = sha(output / 'build.log')
            if done.returncode:
                raise RuntimeError('Compilazione RM fallita: build.log')
            actual_exports = rm_exports(root / 'kernel-open/Module.symvers')
            evidence['rm_export_abi_unchanged'] = actual_exports == expected_exports
            if actual_exports != expected_exports:
                evidence['actual_rm_exports'] = actual_exports
                evidence['expected_rm_exports'] = expected_exports
                raise RuntimeError('Export RM diversi: incompatibilità UVM non esclusa')
            modules = output / 'modules'
            modules.mkdir()
            shutil.copy2(root / 'kernel-open/nvidia.ko', modules / 'nvidia.ko')
            shutil.copy2(args.baseline_build / 'modules/nvidia-uvm.ko', modules / 'nvidia-uvm.ko')
            require_hash(modules / 'nvidia-uvm.ko', profile['baseline_uvm_sha256'])
            evidence['modules'] = {}
            for name in ['nvidia.ko', 'nvidia-uvm.ko']:
                module = modules / name
                info = capture(['modinfo', str(module)])
                if info['returncode']:
                    raise RuntimeError('modinfo fallito: ' + name)
                fields = {}
                for line in info['output'].splitlines():
                    if ':' in line:
                        key, value = line.split(':', 1)
                        fields[key] = value.strip()
                if fields.get('version') != '595.99.02' or not fields.get('vermagic', '').startswith(KERNEL + ' '):
                    raise RuntimeError('Versione/vermagic inattesa: ' + name)
                evidence['modules'][name] = {'sha256': sha(module), 'size': module.stat().st_size,
                                             'modinfo': fields}
            if profile['registry_key'].encode() not in (modules / 'nvidia.ko').read_bytes():
                raise RuntimeError('Chiave registry assente dal nuovo RM')
            evidence['status'] = 'built_not_installed'
        print(json.dumps({'status': evidence['status'], 'output': str(output),
                          'manifest': str(output / 'build-manifest.json')}))
    except Exception as error:
        evidence.update(status='failed', error=str(error))
        raise
    finally:
        evidence['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        (output / 'build-manifest.json').write_text(json.dumps(evidence, indent=2) + '\n')


if __name__ == '__main__':
    main()
