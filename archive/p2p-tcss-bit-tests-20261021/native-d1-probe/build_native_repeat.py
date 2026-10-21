#!/usr/bin/env python3
"""Build only, in the existing Linux VM; no EFI installation or boot mutation.

Reuse the previous native probe's RAM filesystem, with the delayed-free four-byte binary.
The result contains one dynamic-driver trial and no PCI configuration writes.
"""
from pathlib import Path
import hashlib
import json
import re
import shutil
import subprocess
import sys

BASE = Path('/mnt/llm/riscrivo/runtime/reports')
OLD = BASE / 'p2p-tcss-bit-tests-20261021/native-probe'
DRIVERS = BASE / 'gpu-followup-20261020/p2p-driver'
OUT = BASE / 'p2p-tcss-bit-tests-20261021/native-d1-probe'
ROOT = OUT / 'unpacked'
KERNEL = Path('/boot/vmlinuz-7.0.0-38-generic')
MODULE = DRIVERS / 'compiled-dynamic/nvidia.ko'
NATIVE = OUT / 'peer_vmm_word_delayed_native'
SOURCE = OUT / 'peer_vmm_word_delayed.cu'
LIBCUDA = DRIVERS / 'libcuda-experiment/libcuda.so.1'
EXPECTED_MODULE = '41a3025b63192242bda4f9eb692d8a000fc85850d009c45f679f9ef46f9bef80'
EXPECTED_LIBCUDA = '03271500dbda9456e3ba765270bd2609bef2631672809da50b19c67fb1f609a7'
EXPECTED_KERNEL = '9f55ef7253055a9cf68f8a04323c93dead2fca617386d842fbde9ca7b178b27e'

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

assert sys.platform.startswith('linux'), 'Build exclusively inside the Linux VM'
assert subprocess.run(['systemctl', 'is-active', 'riscrivo-training.service'],
                      capture_output=True, text=True).stdout.strip() in ('inactive', 'failed')
assert (OLD / 'unpacked/init').is_file(), 'Prior extracted RAM image absent'
assert NATIVE.is_file(), 'Compile peer_vmm_word_delayed.cu with nvcc before building the RAM image'
assert sha(SOURCE) == '2c3ea614b702fd6d02e940e10586976b51d80ce849b425767578d6521530d117', 'Unexpected probe source'
assert sha(MODULE) == EXPECTED_MODULE
assert sha(LIBCUDA) == EXPECTED_LIBCUDA
assert sha(KERNEL) == EXPECTED_KERNEL
assert not ROOT.exists(), 'Refuse to overwrite a prior repeat build'
OUT.mkdir(parents=True, exist_ok=True)
shutil.copytree(OLD / 'unpacked', ROOT, symlinks=True)

def put(src, dest):
    dest = ROOT / dest.lstrip('/')
    dest.parent.mkdir(parents=True, exist_ok=True)
    assert dest.parent.resolve().is_relative_to(ROOT.resolve())
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    shutil.copy2(Path(src).resolve(), dest)

def binary(src, dest):
    put(src, dest)
    result = subprocess.run(['ldd', str(src)], capture_output=True, text=True)
    assert result.returncode == 0 and 'not found' not in result.stdout + result.stderr
    for line in result.stdout.splitlines():
        match = re.search(r'(/[^\s]+)', line)
        if match:
            lib = Path(match[1])
            put(lib, '/usr/lib/x86_64-linux-gnu/' + lib.name)

put(MODULE, '/opt/probe/nvidia-dynamic.ko')
binary(NATIVE, '/opt/probe/peer_word')
binary(LIBCUDA, '/usr/lib/x86_64-linux-gnu/libcuda.so.1')
put(OUT / 'init-tcss-native.sh', '/init')
(ROOT / 'init').chmod(0o755)
subprocess.run(['chroot', str(ROOT), '/bin/sh', '-n', '/init'], check=True)
loader = subprocess.run(['chroot', str(ROOT), '/lib64/ld-linux-x86-64.so.2', '--list', '/opt/probe/peer_word'], capture_output=True, text=True)
assert loader.returncode == 0 and 'not found' not in loader.stdout + loader.stderr
applets = subprocess.check_output(['chroot', str(ROOT), '/bin/busybox', '--list'], text=True).splitlines()
assert all(name in applets for name in ('timeout', 'reboot', 'mknod', 'awk', 'mount'))
with (OUT / 'probe-initrd.img').open('wb') as output:
    listing = subprocess.Popen(['find', '.', '-print0'], cwd=ROOT, stdout=subprocess.PIPE)
    archive = subprocess.Popen(['cpio', '--null', '-o', '--format=newc', '--quiet'], cwd=ROOT, stdin=listing.stdout, stdout=subprocess.PIPE)
    listing.stdout.close()
    compressor = subprocess.Popen(['gzip', '-1'], stdin=archive.stdout, stdout=output)
    archive.stdout.close()
    assert compressor.wait() == 0 and archive.wait() == 0 and listing.wait() == 0
shutil.copy2(KERNEL, OUT / 'probe-kernel.efi')
(OUT / 'IDENTITY.txt').write_text('CaskLogic-TCSS-native-20261021\n')
manifest = {
    'kernel': str(KERNEL), 'kernel_sha256': sha(KERNEL),
    'initrd_sha256': sha(OUT / 'probe-initrd.img'), 'initrd_bytes': (OUT / 'probe-initrd.img').stat().st_size,
    'module': str(MODULE), 'module_sha256': sha(MODULE),
    'native_program': str(NATIVE), 'native_program_sha256': sha(NATIVE),
    'native_source': str(SOURCE), 'native_source_sha256': sha(SOURCE),
    'deferred_free_after_all_four_comparisons': True,
    'timing': 'CLOCK_MONOTONIC and best-effort /dev/kmsg phase markers',
    'expected_CCFG': {'00:01.0': '00008077', '00:07.0': '00009077', '00:07.2': '00009077'},
    'libcuda_sha256': sha(LIBCUDA), 'init_sha256': sha(OUT / 'init-tcss-native.sh'),
    'trials': 1, 'payload_bytes': 4, 'pci_configuration_writes': False,
    'hardware_boot_started': False, 'automatic_return_seconds': 180,
    'esp_partuuid': '3c6ae711-bbc9-4653-bf09-0baac6b3b380',
    'efi_directory': r'\EFI\CaskLogicTcssNative',
    'kernel_args': r'initrd=\EFI\CaskLogicTcssNative\probe-initrd.img rdinit=/init intel_iommu=off iommu=off module_blacklist=nouveau,nvidia_drm,nvidia_modeset panic=10 loglevel=4 console=tty0',
}
(OUT / 'build-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps(manifest, indent=2))
