#!/usr/bin/env python3
"""Ricostruzione locale/CPU: nessun caricamento, installazione o accesso GPU."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time

from strict_patch import apply_file

HERE = Path(__file__).resolve().parent


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def check_subset(root, expected):
    actual = {name: sha(root / name) for name in expected}
    if actual != expected:
        raise RuntimeError('Hash sorgenti diverso: ' + str({k: v for k, v in actual.items() if v != expected[k]}))
    return actual


def patch_paths(path):
    return [line[6:].split()[0] for line in path.read_text().splitlines() if line.startswith('+++ b/')]


def capture(command):
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    return {'command': command, 'returncode': result.returncode, 'output': result.stdout}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='Directory nuova; rifiuta qualsiasi directory esistente')
    parser.add_argument('--build', action='store_true', help='Compila solamente; non installa né carica moduli')
    parser.add_argument('--kernel', default='7.0.0-38-generic')
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    if args.jobs < 1 or args.jobs > 32:
        parser.error('--jobs deve essere fra 1 e 32')
    manifest = json.loads((HERE / 'source-manifest.json').read_text())
    if sha(args.archive) != manifest['archive_sha256']:
        raise RuntimeError('SHA256 archivio NVIDIA diverso da quello autenticato')
    for name, expected in manifest['patches'].items():
        if sha(HERE / name) != expected:
            raise RuntimeError('Patch modificata: ' + name)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    evidence = {'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'archive': str(args.archive.resolve()), 'archive_sha256': sha(args.archive),
                'patches': manifest['patches'], 'build_requested': args.build,
                'historical_binary_sha256': manifest['historical_binary_sha256'],
                'bit_identical_rebuild_claimed': False,
                'source_manifest_sha256': sha(HERE / 'source-manifest.json'),
                'builder_sha256': sha(Path(__file__)), 'strict_patch_sha256': sha(HERE / 'strict_patch.py')}
    evidence_path = out / 'build-manifest.json'
    try:
        with tarfile.open(args.archive, 'r:gz') as archive:
            roots = {m.name.split('/')[0] for m in archive.getmembers()}
            if roots != {manifest['archive_root']}:
                raise RuntimeError('Radice archivio inattesa: ' + str(roots))
            archive.extractall(out / 'source', filter='data')
        root = out / 'source' / manifest['archive_root']
        evidence['stock_verified'] = check_subset(root, manifest['stock_subset'])
        for name in ['bar1-minimal.patch', 'bar1-dynamic.patch']:
            for path in patch_paths(HERE / name):
                apply_file(root, HERE / name, path)
        evidence['baseline_verified'] = check_subset(root, manifest['baseline_subset'])
        for path in patch_paths(HERE / 'pte-logging.patch'):
            apply_file(root, HERE / 'pte-logging.patch', path)
        evidence['instrumented_verified'] = check_subset(root, manifest['instrumented_subset'])
        evidence['source_root'] = str(root)
        evidence['status'] = 'prepared'
        evidence_path.write_text(json.dumps(evidence, indent=2) + '\n')
        if not args.build:
            print(json.dumps({'status': 'prepared', 'source_root': str(root), 'manifest': str(evidence_path)}))
            return
        headers = Path('/lib/modules') / args.kernel / 'build'
        if not headers.is_dir():
            raise RuntimeError('Header kernel mancanti: ' + str(headers))
        evidence['toolchain'] = [capture(['uname', '-a']), capture(['cc', '--version']),
                                 capture(['ld', '--version']), capture(['make', '--version'])]
        environment_keys = ['CC', 'CXX', 'LD', 'HOSTCC', 'HOSTCXX', 'CFLAGS', 'CPPFLAGS',
                            'LDFLAGS', 'MAKEFLAGS', 'NV_KERNEL_MODULES', 'NV_VERBOSE']
        evidence['build_environment'] = {k: os.environ[k] for k in environment_keys if k in os.environ}
        command = ['make', '-j' + str(args.jobs), 'NV_VERBOSE=1', 'KERNEL_UNAME=' + args.kernel, 'modules']
        evidence['build_command'] = command
        evidence_path.write_text(json.dumps(evidence, indent=2) + '\n')
        with (out / 'build.log').open('w') as log:
            result = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT, check=False)
        evidence['build_returncode'] = result.returncode
        evidence['build_log_sha256'] = sha(out / 'build.log')
        if result.returncode:
            raise RuntimeError('Compilazione fallita; conservato build.log')
        modules = out / 'modules'
        modules.mkdir()
        evidence['modules'] = {}
        for name in ['nvidia.ko', 'nvidia-uvm.ko']:
            source = root / 'kernel-open' / name
            destination = modules / name
            shutil.copy2(source, destination)
            info = capture(['modinfo', str(destination)])
            if info['returncode']:
                raise RuntimeError('modinfo fallito: ' + name)
            fields = {}
            for line in info['output'].splitlines():
                if ':' in line:
                    key, value = line.split(':', 1)
                    fields[key] = value.strip()
            if fields.get('version') != '595.99.02' or not fields.get('vermagic', '').startswith(args.kernel + ' '):
                raise RuntimeError('Versione/vermagic modulo inattesa: ' + name)
            evidence['modules'][name] = {'sha256': sha(destination), 'size': destination.stat().st_size,
                                         'modinfo': fields}
        evidence['status'] = 'built_not_installed'
        print(json.dumps({'status': evidence['status'], 'modules': str(modules), 'manifest': str(evidence_path)}))
    except Exception as error:
        evidence['status'] = 'failed'
        evidence['error'] = str(error)
        raise
    finally:
        evidence['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        evidence_path.write_text(json.dumps(evidence, indent=2) + '\n')


if __name__ == '__main__':
    main()
