#!/usr/bin/env python3
"""Build only, in the existing Linux VM; no EFI installation or boot mutation.

Reuse the previous native probe's RAM filesystem, with the synchronized-owner four-byte binary and delayed frees.
The result contains five controlled phases; GPU DEVCTL bits0x0810 only, verified restore.
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
OUT = BASE / 'p2p-tcss-bit-tests-20261021/native-nosnoop-probe'
PACKAGE = BASE / 'p2p-tcss-bit-tests-20261021/native-nosnoop-v2-probe-package'
ROOT = OUT / 'unpacked-gate2'
KERNEL = Path('/boot/vmlinuz-7.0.0-38-generic')
BUILD = BASE / 'p2p-tcss-bit-tests-20261021/driver-instrumented-build-01'
BUILD_MANIFEST = json.loads((BUILD / 'build-manifest.json').read_text())
assert BUILD_MANIFEST['status'] == 'built_not_installed'
MODULE = BUILD / 'modules/nvidia.ko'
UVM_MODULE = BUILD / 'modules/nvidia-uvm.ko'
NATIVE = OUT / 'peer_vmm_word_nosnoop_native'
SOURCE = OUT / 'peer_vmm_word_nosnoop.cu'
HEADER = OUT / 'pcie_diag.h'
LIBCUDA = DRIVERS / 'libcuda-experiment/libcuda.so.1'
EXPECTED_MODULE = 'ab41b0a38e7ab92c0d1468b33c456c5c5c57501c67dfe5a666f49aed9fb6b1b5'
assert BUILD_MANIFEST['modules']['nvidia.ko']['sha256'] == EXPECTED_MODULE
EXPECTED_UVM_MODULE = '9b993671ef066c9d3e58fd52b0d70228861769a2e3dcf304bc3d80bca089c4d0'
assert BUILD_MANIFEST['modules']['nvidia-uvm.ko']['sha256'] == EXPECTED_UVM_MODULE
EXPECTED_LIBCUDA = '03271500dbda9456e3ba765270bd2609bef2631672809da50b19c67fb1f609a7'
EXPECTED_KERNEL = '9f55ef7253055a9cf68f8a04323c93dead2fca617386d842fbde9ca7b178b27e'

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

assert sys.platform.startswith('linux'), 'Build exclusively inside the Linux VM'
assert subprocess.run(['systemctl', 'is-active', 'riscrivo-training.service'],
                      capture_output=True, text=True).stdout.strip() in ('inactive', 'failed')
assert (OLD / 'unpacked/init').is_file(), 'Prior extracted RAM image absent'
assert NATIVE.is_file(), 'Compile peer_vmm_word_nosnoop.cu with nvcc before building the RAM image'
assert sha(SOURCE) == 'd7e8cf9af7964ec93206638014586f028346058c045b8a043751a9c35025427b', 'Unexpected probe source'
assert sha(MODULE) == EXPECTED_MODULE
assert sha(UVM_MODULE) == EXPECTED_UVM_MODULE
assert sha(LIBCUDA) == EXPECTED_LIBCUDA
assert sha(KERNEL) == EXPECTED_KERNEL
assert sha(HEADER) == '4820c6c0f296c9af7bb75403885f860a3f8d1837d0aed1e625143258001358ae'
CPU_HEADER = OUT / 'cpubar_trace.h'
assert sha(CPU_HEADER) == '06aa999da4c9c06ebf3d5fb398d30dc79aae964765791fc386e21b2e6fb1d7a4'

ATTR_HEADER = OUT / 'pci_attrs.h'
TRIAL_MAIN = OUT / 'trial_main.inc'
INIT = OUT / 'init-tcss-native.sh'
assert sha(ATTR_HEADER) == '6780c0ceb37cbfd1585406e9e9334697e90145412456216a5eec37bd32520d31', 'Unexpected pci_attrs.h'
assert sha(TRIAL_MAIN) == 'c330936901293714a696f0aae5a4feadbba982a08ab4093fd50456a3332b8876', 'Unexpected trial_main.inc'
assert sha(INIT) == '2f216a3fe12bb4ba53487edb3a22aec3ac550271c82ff72c6228da9c859d487b', 'Unexpected init-tcss-native.sh'
assert not ROOT.exists(), 'Refuse to overwrite a prior repeat build'
assert not PACKAGE.exists(), 'Refuse to overwrite a prior package'
PACKAGE.mkdir(parents=True)
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
put(UVM_MODULE, '/opt/probe/nvidia-instrumented-uvm.ko')
binary(NATIVE, '/opt/probe/peer_word')
binary(LIBCUDA, '/usr/lib/x86_64-linux-gnu/libcuda.so.1')
put(OUT / 'init-tcss-native.sh', '/init')
(ROOT / 'init').chmod(0o755)
subprocess.run(['chroot', str(ROOT), '/bin/sh', '-n', '/init'], check=True)
loader = subprocess.run(['chroot', str(ROOT), '/lib64/ld-linux-x86-64.so.2', '--list', '/opt/probe/peer_word'], capture_output=True, text=True)
assert loader.returncode == 0 and 'not found' not in loader.stdout + loader.stderr
applets = subprocess.check_output(['chroot', str(ROOT), '/bin/busybox', '--list'], text=True).splitlines()
assert all(name in applets for name in ('timeout', 'reboot', 'mknod', 'awk', 'mount'))
with (PACKAGE / 'probe-initrd.img').open('wb') as output:
    listing = subprocess.Popen(['find', '.', '-print0'], cwd=ROOT, stdout=subprocess.PIPE)
    archive = subprocess.Popen(['cpio', '--null', '-o', '--format=newc', '--quiet'], cwd=ROOT, stdin=listing.stdout, stdout=subprocess.PIPE)
    listing.stdout.close()
    compressor = subprocess.Popen(['gzip', '-1'], stdin=archive.stdout, stdout=output)
    archive.stdout.close()
    assert compressor.wait() == 0 and archive.wait() == 0 and listing.wait() == 0
shutil.copy2(KERNEL, PACKAGE / 'probe-kernel.efi')
(PACKAGE / 'IDENTITY.txt').write_text('CaskLogic-TCSS-native-20261021\n')
manifest = {
    'kernel': str(KERNEL), 'kernel_sha256': sha(KERNEL),
    'initrd_sha256': sha(PACKAGE / 'probe-initrd.img'), 'initrd_bytes': (PACKAGE / 'probe-initrd.img').stat().st_size,
    'module': str(MODULE), 'module_sha256': sha(MODULE),
    'uvm_module': str(UVM_MODULE), 'uvm_module_sha256': sha(UVM_MODULE),
    'driver_build_manifest_sha256': sha(BUILD / 'build-manifest.json'),
    'instrumentation': 'RM DMA BAR1 PTE lifecycle and UVM map submission logs only',
    'native_program': str(NATIVE), 'native_program_sha256': sha(NATIVE),
    'native_source': str(SOURCE), 'native_source_sha256': sha(SOURCE),
    'native_header': str(HEADER), 'native_header_sha256': sha(HEADER),
    'owner_synchronization_before_peer': True, 'owner_local_word_readback_before_peer': True,
    'pcie_diagnostics': 'Read-only PCIe snapshots with DEVCTL readback before/after each operation in all five phases',
    'deferred_free_after_all_twenty_comparisons_and_restore': True,
    'timing': 'CLOCK_MONOTONIC and best-effort /dev/kmsg phase markers',
    'expected_CCFG': {'00:01.0': '00008077', '00:07.0': '00009077', '00:07.2': '00009077'},
    'libcuda_sha256': sha(LIBCUDA), 'init_sha256': sha(OUT / 'init-tcss-native.sh'),
    'trials': 5, 'payload_bytes': 4, 'comparisons': 20, 'persistent_vmm_allocations': 4,
    'phases': ['baseline_initial', 'ada_off', 'baseline_restored', 'both_off', 'baseline_final'],
    'pci_configuration_writes': 'GPU endpoints only, width16, DeviceControl mask0x0810; capture/readback/restore; no DeviceStatus writes',
    'attrs_header_sha256': sha(ATTR_HEADER), 'trial_main_sha256': sha(TRIAL_MAIN),
    'program_timeout_seconds': 60,
    'watchdog': 'RAM boot only; 180 seconds plus one-second async-sync grace, sysrq-b if available else force reboot',
    'cpu_bar1_control': 'O_RDONLY PROT_READ four bytes per pattern, two patterns per GPU, no BAR writes',
    'cpu_header_sha256': sha(CPU_HEADER),
    'cpu_postwrite_control': 'Read only same target after writer synchronization, before owner D2H; no CUDA API in observation',
    'printk_devkmsg': 'on during RAM boot for lossless allocation markers',
    'registry_override': 'RM64KBBAR1Mappings=0',
    'driver_binaries_identical_to_instrumented2': True,
    'hardware_boot_started': False, 'automatic_return_seconds': 180,
    'esp_partuuid': '3c6ae711-bbc9-4653-bf09-0baac6b3b380',
    'efi_directory': r'\EFI\CaskLogicTcssNative',
    'kernel_args': r'initrd=\EFI\CaskLogicTcssNative\probe-initrd.img rdinit=/init intel_iommu=off iommu=off module_blacklist=nouveau,nvidia_drm,nvidia_modeset panic=10 loglevel=4 console=tty0',
}
(PACKAGE / 'build-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps(manifest, indent=2))
