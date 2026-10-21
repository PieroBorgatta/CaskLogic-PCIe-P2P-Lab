#!/usr/bin/env python3
"""Clona la build verificata e compila solo UVM; non installa né carica moduli."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time
from strict_patch import apply_file

HERE = Path(__file__).resolve().parent


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for part in iter(lambda: f.read(1024*1024), b''):
            h.update(part)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline-build', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--jobs', type=int, default=4)
    p.add_argument('--build', action='store_true')
    a = p.parse_args()
    if not 1 <= a.jobs <= 32:
        p.error('jobs fuori intervallo1..32')
    profile = json.loads((HERE/'manifest.json').read_text())
    baseline_file = a.baseline_build/'build-manifest.json'
    baseline = json.loads(baseline_file.read_text())
    source = Path(baseline['source_root'])
    if baseline['status'] != 'built_not_installed' or baseline['build_returncode'] != 0:
        raise RuntimeError('Baseline non compilata correttamente')
    for filename, expected in baseline['instrumented_verified'].items():
        if sha(source/filename) != expected:
            raise RuntimeError('Sorgente baseline modificata: '+filename)
    if sha(source/profile['source_path']) != profile['preimage_sha256']:
        raise RuntimeError('Preimmagine UVM diversa')
    for name, expected in [('nvidia.ko', profile['baseline_nvidia_sha256']),
                           ('nvidia-uvm.ko', profile['baseline_uvm_sha256'])]:
        if sha(a.baseline_build/'modules'/name) != expected:
            raise RuntimeError('Modulo baseline diverso: '+name)
    if sha(HERE/'uvm-peer-4k.patch') != profile['patch_sha256']:
        raise RuntimeError('Patch modificata')
    output = a.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    tree = output/'source'
    evidence = {'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'baseline_build': str(a.baseline_build.resolve()), 'baseline_manifest_sha256': sha(baseline_file),
                'profile': profile, 'baseline_source_verified': baseline['instrumented_verified'],
                'build_requested': a.build, 'hardware_operations': False,
                'builder_sha256': sha(Path(__file__)), 'source_root': str(tree)}
    try:
        shutil.copytree(source, tree, symlinks=True)
        for filename, expected in baseline['instrumented_verified'].items():
            if sha(tree/filename) != expected:
                raise RuntimeError('Copia sorgente non identica: '+filename)
        apply_file(tree, HERE/'uvm-peer-4k.patch', profile['source_path'])
        if sha(tree/profile['source_path']) != profile['candidate_sha256']:
            raise RuntimeError('Hash post-patch diverso')
        # Modpost must resolve RM exports without recompiling/linking nvidia.ko.
        symvers = tree/'kernel-open/Module.symvers'
        exported = [line for line in symvers.read_text().splitlines(True)
                    if len(line.split()) >= 3 and Path(line.split()[2]).name == 'nvidia']
        if not exported:
            raise RuntimeError('Nessun simbolo NVIDIA RM nella Module.symvers baseline')
        extra = output/'nvidia-only.symvers'
        extra.write_text(''.join(exported))
        evidence['rm_export_count'] = len(exported)
        evidence['rm_exports_sha256'] = sha(extra)
        evidence['status'] = 'prepared_not_built'
        if a.build:
            command = ['make', '-C', str(tree/'kernel-open'), '-j'+str(a.jobs), 'NV_VERBOSE=1',
                       'KERNEL_UNAME=7.0.0-38-generic', 'NV_KERNEL_MODULES=nvidia-uvm',
                       'KBUILD_EXTRA_SYMBOLS='+str(extra), 'modules']
            evidence['command'] = command
            with (output/'build.log').open('w') as log:
                done = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=False)
            evidence['build_returncode'] = done.returncode
            evidence['build_log_sha256'] = sha(output/'build.log')
            if done.returncode:
                raise RuntimeError('Compilazione UVM fallita, vedere build.log')
            modules = output/'modules'
            modules.mkdir()
            shutil.copy2(a.baseline_build/'modules/nvidia.ko', modules/'nvidia.ko')
            shutil.copy2(tree/'kernel-open/nvidia-uvm.ko', modules/'nvidia-uvm.ko')
            if sha(modules/'nvidia.ko') != profile['baseline_nvidia_sha256']:
                raise RuntimeError('RM non identico alla baseline')
            evidence['modules'] = {}
            for name in ['nvidia.ko', 'nvidia-uvm.ko']:
                path = modules/name
                info = subprocess.run(['modinfo', str(path)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True).stdout
                if '595.99.02' not in info or '7.0.0-38-generic SMP' not in info:
                    raise RuntimeError('Versione o vermagic inatteso')
                if name == 'nvidia-uvm.ko' and profile['parameter'] not in info:
                    raise RuntimeError('Parametro sperimentale assente dal modulo')
                evidence['modules'][name] = {'sha256': sha(path), 'size': path.stat().st_size, 'modinfo': info}
            evidence['status'] = 'built_not_installed'
        print(json.dumps({'status': evidence['status'], 'output': str(output)}))
    except Exception as error:
        evidence.update(status='failed', error=str(error))
        raise
    finally:
        evidence['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        (output/'build-manifest.json').write_text(json.dumps(evidence, indent=2)+'\n')


if __name__ == '__main__':
    main()
