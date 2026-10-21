"""Build RAM-only native package from the verified previous CE payload, CPU only."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys
R=Path('/mnt/llm/riscrivo/runtime/reports/p2p-next-investigation-20261021')
OLD=R.parent/'p2p-tcss-bit-tests-20261021'
OUT=R/'native-physical2-ce-probe'
ROOT=OUT/'unpacked'
PACKAGE=R/'native-physical2-ce-probe-package'
BASE=OLD/'native-ce-probe/unpacked'
BASE_PACKAGE=OLD/'native-ce-probe-package'
DRIVER=R/'driver-physical-ce-build-03'
UVM_PAYLOAD='opt/probe/nvidia-instrumented-uvm.ko'
REJECTED_V1='8d3a9d42407f46bf66d498e09cb4fd9422ab950b75afd314912f4ff055078780'
EXPECTED_PATCH='34acdf3111d112f35358b4b549a4f1c9c55b76cce9ac2f4581354e783bc476af'
EXPECTED_UVM='83b6342f0ef44c0d97dd6fad0310e99438718a8450bf40a29939c250604e8bce'
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
assert sys.platform.startswith('linux') and os.geteuid()==0
assert subprocess.check_output(['hostname'],text=True).strip()=='gpu-vm'
assert subprocess.run(['systemctl','is-active','riscrivo-training.service'],capture_output=True,text=True).stdout.strip()=='inactive'
assert not subprocess.check_output(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader'],text=True).strip()
assert not ROOT.exists() and not PACKAGE.exists()
old=json.loads((BASE_PACKAGE/'build-manifest.json').read_text())
assert old['files']['probe-initrd.img']=='2f912fcfca5f69616b4f18159e777b28b60023ebe4e24d3e53a9d4ff7193fd72'
assert sha(BASE_PACKAGE/'probe-initrd.img')==old['files']['probe-initrd.img']
for p,d in old['payload_files'].items():assert sha(BASE/p)==d,p
contract=json.loads((R/'physical2-build-inputs.json').read_text())
assert contract['status']=='reviewed_for_build'
for p,d in contract['files'].items():
 assert not Path(p).is_absolute() and '..' not in Path(p).parts
 assert sha(R/p)==d,p
# Only the reviewed second build is eligible; the first build had a FORTIFY
# warning and was explicitly rejected before any hardware load.
driver_file=DRIVER/'build-manifest.json'
driver=json.loads(driver_file.read_text())
profile=json.loads((R/'driver-physical-ce-v3/manifest.json').read_text())
assert driver['status']=='built_not_installed' and driver['build_returncode']==0
assert profile['patch_sha256']==EXPECTED_PATCH
assert driver['contract_sha256']==sha(R/'driver-physical-ce-v3/build-contract.json')
assert set(driver['overlay'])==set(profile['files'])
for p,v in profile['files'].items():assert driver['overlay'][p]['after']==v['postimage_sha256'],p
uvm_source=DRIVER/'modules/nvidia-uvm.ko'
uvm_sha=sha(uvm_source)
assert uvm_sha==driver['modules']['nvidia-uvm.ko']['sha256']==EXPECTED_UVM
assert uvm_sha not in (REJECTED_V1,old['uvm_module_sha256'])
assert driver['modules']['nvidia.ko']['sha256']==old['module_sha256']
assert sha(DRIVER/'modules/nvidia.ko')==old['module_sha256']
for p in (driver_file,uvm_source,R/'driver-physical-ce-v3/manifest.json',R/'driver-physical-ce-v3/build-contract.json',R/'init-physical2.sh',OUT/'peer_physical_ce_native',R/'build_physical2_package.py'):
 assert contract['files'][str(p.relative_to(R))]==sha(p),str(p)
shutil.copytree(BASE,ROOT,symlinks=True)
PACKAGE.mkdir()
program=OUT/'peer_physical_ce_native'
for source,target in [(program,ROOT/'opt/probe/peer_word'),(R/'init-physical2.sh',ROOT/'init'),(uvm_source,ROOT/UVM_PAYLOAD)]:
 assert target.is_file() and not target.is_symlink()
 old_mode=target.stat().st_mode & 0o7777
 target.unlink();shutil.copyfile(source,target);target.chmod(old_mode)
(ROOT/'init').chmod(0o755)
subprocess.run(['chroot',str(ROOT),'/bin/sh','-n','/init'],check=True)
loader=subprocess.run(['chroot',str(ROOT),'/lib64/ld-linux-x86-64.so.2','--list','/opt/probe/peer_word'],capture_output=True,text=True)
assert loader.returncode==0 and 'not found' not in loader.stdout+loader.stderr,loader.stdout+loader.stderr
assert 'libcuda.so.1' in loader.stdout
nvml_path='usr/lib/x86_64-linux-gnu/libnvidia-ml.so.1'
nvml_sha='770e9de75c14b07cce9718b214700b10e6d6866f7383101d6fe530352543b1de'
assert (ROOT/nvml_path).is_file() and sha(ROOT/nvml_path)==nvml_sha
(OUT/'loader-verification.txt').write_text(loader.stdout)
with (PACKAGE/'probe-initrd.img').open('wb') as output:
 listing=subprocess.Popen(['find','.','-print0'],cwd=ROOT,stdout=subprocess.PIPE)
 archive=subprocess.Popen(['cpio','--null','-o','--format=newc','--quiet'],cwd=ROOT,stdin=listing.stdout,stdout=subprocess.PIPE)
 listing.stdout.close()
 compressor=subprocess.Popen(['gzip','-1'],stdin=archive.stdout,stdout=output)
 archive.stdout.close()
 assert compressor.wait()==archive.wait()==listing.wait()==0
shutil.copy2(BASE_PACKAGE/'probe-kernel.efi',PACKAGE/'probe-kernel.efi')
(PACKAGE/'IDENTITY.txt').write_text('CaskLogic-TCSS-physical2-20261021\n')
files={n:sha(PACKAGE/n) for n in ('probe-kernel.efi','probe-initrd.img','IDENTITY.txt')}
assert files['probe-kernel.efi']=='9f55ef7253055a9cf68f8a04323c93dead2fca617386d842fbde9ca7b178b27e'
manifest={
 'built_not_booted':True,'files':files,'input_files':contract['files'],
 'build_inputs_sha256':sha(R/'physical2-build-inputs.json'),
 'baseline_package_initrd_sha256':old['files']['probe-initrd.img'],
 'intended_payload_changes':['init','opt/probe/peer_word',UVM_PAYLOAD],
 'driver_build_manifest_sha256':sha(driver_file),
 'driver_build_contract_sha256':driver['contract_sha256'],
 'driver_source_patch_sha256':EXPECTED_PATCH,
 'driver_build_directory':DRIVER.name,
 'initrd_bytes':(PACKAGE/'probe-initrd.img').stat().st_size,
 'native_program_sha256':sha(program),'init_sha256':sha(ROOT/'init'),
 'module_sha256':old['module_sha256'],'uvm_module_sha256':uvm_sha,'libcuda_sha256':old['libcuda_sha256'],
 'expected_CCFG':{'00:01.0':'04008077','00:07.0':'0e009077','00:07.2':'0e009077'},
 'automatic_return_seconds':182,'program_timeout_seconds':60,
 'vm_disks_mounted':False,'pci_config_writes':False,'firmware_writes':False,
 'comparisons':4,'sizes':[4],'modes':['PUSH'],
 'engines':['SM','PHYSICAL_CE'],'direct_route_proven':False,
 'physical_ce_ioctl':315,'physical_ce_abi':1,'physical_ce_bytes':4,
 'physical_ce_module_parameters':{'uvm_cask_physical_ce':'Y','uvm_enable_builtin_tests':'1'},
 'physical_destination_mode':'NONCOHERENT_SYSMEM',
 'calibrations':4,'calibration_sizes':[1048576],
 'calibration_modes':['HOST_TO_DEVICE','DEVICE_TO_HOST'],
 'calibration_payload_is_p2p':False,'NVML_sampling_during_physical_ioctl':False,
 'watchdog_evidence_capture':'best effort asynchronous worker writes marker and kernel log before nominal182second emergency return',
 'nvml_library_sha256':nvml_sha,
 'payload_files':{p:sha(ROOT/p) for p in list(old['payload_files'])+[nvml_path]}
}
for p,d in manifest['payload_files'].items():
 if p==nvml_path:assert d==nvml_sha,p
 elif p==UVM_PAYLOAD:assert d==uvm_sha,p
 elif p not in manifest['intended_payload_changes']:assert d==old['payload_files'][p],p
(PACKAGE/'files.json').write_text(json.dumps(files,indent=2)+'\n')
(PACKAGE/'build-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'package':str(PACKAGE),'files':files,'bytes':manifest['initrd_bytes']}))
