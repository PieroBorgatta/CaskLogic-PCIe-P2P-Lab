#!/usr/bin/env python3
"""Costruzione CPU della sola immagine RAM; nessuna installazione o prova GPU."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

R = Path('/mnt/llm/riscrivo/runtime/reports/p2p-tcss-bit-tests-20261021')
OUT = R / 'native-ce-probe'
ROOT = OUT / 'unpacked'
PACKAGE = R / 'native-ce-probe-package'
BUILD = R / 'driver-instrumented-build-01'
KERNEL = Path('/boot/vmlinuz-7.0.0-38-generic')
LIBCUDA = R.parent / 'gpu-followup-20261020/p2p-driver/libcuda-experiment/libcuda.so.1'

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

assert sys.platform.startswith('linux') and os.geteuid() == 0
assert subprocess.check_output(['hostname'], text=True).strip() == 'gpu-vm'
assert subprocess.run(['systemctl', 'is-active', 'riscrivo-training.service'], capture_output=True, text=True).stdout.strip() == 'inactive'
contract = json.loads((OUT / 'build-inputs.json').read_text())
assert contract['status'] == 'reviewed_for_build'
for name, digest in contract['files'].items():
    assert sha(OUT / name) == digest, name
assert sha(BUILD / 'modules/nvidia.ko') == 'ab41b0a38e7ab92c0d1468b33c456c5c5c57501c67dfe5a666f49aed9fb6b1b5'
assert sha(BUILD / 'modules/nvidia-uvm.ko') == '9b993671ef066c9d3e58fd52b0d70228861769a2e3dcf304bc3d80bca089c4d0'
assert sha(KERNEL) == '9f55ef7253055a9cf68f8a04323c93dead2fca617386d842fbde9ca7b178b27e'
assert sha(LIBCUDA) == '03271500dbda9456e3ba765270bd2609bef2631672809da50b19c67fb1f609a7'
assert not ROOT.exists() and not PACKAGE.exists()
shutil.copytree(R / 'native-probe/unpacked', ROOT, symlinks=True)
PACKAGE.mkdir()

def put(source, destination):
    target = ROOT / destination.lstrip('/')
    target.parent.mkdir(parents=True, exist_ok=True)
    assert target.parent.resolve().is_relative_to(ROOT.resolve())
    if target.exists() or target.is_symlink():
        target.unlink()
    shutil.copy2(Path(source).resolve(), target)

def binary(source, destination):
    put(source, destination)
    env = dict(os.environ, LD_LIBRARY_PATH=str(OUT / 'lib') + ':' + str(LIBCUDA.parent))
    found = subprocess.run(['ldd', str(source)], capture_output=True, text=True, env=env)
    assert found.returncode == 0 and 'not found' not in found.stdout + found.stderr, found.stdout
    for line in found.stdout.splitlines():
        match = re.search(r'(/[^\s]+)', line)
        if match:
            dependency = Path(match[1])
            put(dependency, '/usr/lib/x86_64-linux-gnu/' + dependency.name)

put(BUILD / 'modules/nvidia.ko', '/opt/probe/nvidia-dynamic.ko')
put(BUILD / 'modules/nvidia-uvm.ko', '/opt/probe/nvidia-instrumented-uvm.ko')
binary(OUT / 'peer_ce_cupti_native', '/opt/probe/peer_word')
for source in sorted((OUT / 'lib').glob('*.so*')):
    binary(source, '/usr/lib/x86_64-linux-gnu/' + source.name)
binary(LIBCUDA, '/usr/lib/x86_64-linux-gnu/libcuda.so.1')
assert sha(ROOT / 'usr/lib/x86_64-linux-gnu/libcuda.so.1') == sha(LIBCUDA)
put(OUT / 'init-tcss-native.sh', '/init')
(ROOT / 'init').chmod(0o755)
subprocess.run(['chroot', str(ROOT), '/bin/sh', '-n', '/init'], check=True)
loader = subprocess.run(['chroot', str(ROOT), '/lib64/ld-linux-x86-64.so.2', '--list', '/opt/probe/peer_word'], capture_output=True, text=True)
assert loader.returncode == 0 and 'not found' not in loader.stdout + loader.stderr, loader.stdout
(OUT / 'loader-verification.txt').write_text(loader.stdout)
assert 'libcupti.so.12' in loader.stdout and 'libcuda.so.1' in loader.stdout
with (PACKAGE / 'probe-initrd.img').open('wb') as output:
    listing = subprocess.Popen(['find', '.', '-print0'], cwd=ROOT, stdout=subprocess.PIPE)
    archive = subprocess.Popen(['cpio', '--null', '-o', '--format=newc', '--quiet'], cwd=ROOT, stdin=listing.stdout, stdout=subprocess.PIPE)
    listing.stdout.close()
    compressor = subprocess.Popen(['gzip', '-1'], stdin=archive.stdout, stdout=output)
    archive.stdout.close()
    assert compressor.wait() == archive.wait() == listing.wait() == 0
shutil.copy2(KERNEL, PACKAGE / 'probe-kernel.efi')
(PACKAGE / 'IDENTITY.txt').write_text('CaskLogic-TCSS-native-20261021\n')
files = {name: sha(PACKAGE / name) for name in ['probe-kernel.efi', 'probe-initrd.img', 'IDENTITY.txt']}
(PACKAGE / 'files.json').write_text(json.dumps(files, indent=2) + '\n')
manifest = dict(contract, built_not_booted=True, files=files,
                input_files=contract['files'], build_inputs_sha256=sha(OUT / 'build-inputs.json'),
                initrd_bytes=(PACKAGE / 'probe-initrd.img').stat().st_size,
                native_program_sha256=sha(OUT / 'peer_ce_cupti_native'),
                module_sha256=sha(BUILD / 'modules/nvidia.ko'),
                uvm_module_sha256=sha(BUILD / 'modules/nvidia-uvm.ko'),
                libcuda_sha256=sha(LIBCUDA),
                init_sha256=sha(OUT / 'init-tcss-native.sh'),
                expected_CCFG={'00:01.0':'00008077', '00:07.0':'00009077', '00:07.2':'00009077'},
                automatic_return_seconds=180, program_timeout_seconds=60,
                vm_disks_mounted=False, pci_config_writes=False,
                comparisons=12, sizes=[4,65536,1048576], engines=['SM','CUDA_DtoD_with_CUPTI'],
                direct_route_proven=False,
                payload_files={str(p.relative_to(ROOT)):sha(p) for p in
                    [ROOT/'opt/probe/peer_word', ROOT/'opt/probe/nvidia-dynamic.ko', ROOT/'opt/probe/nvidia-instrumented-uvm.ko', ROOT/'usr/lib/x86_64-linux-gnu/libcupti.so.12', ROOT/'usr/lib/x86_64-linux-gnu/libcuda.so.1', ROOT/'init']})
(PACKAGE / 'build-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps({'package':str(PACKAGE), 'files':files, 'bytes':manifest['initrd_bytes']}))
