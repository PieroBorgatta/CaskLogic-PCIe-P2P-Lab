"""Build RAM-only native package from the verified previous CE payload, CPU only."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys
R=Path('/mnt/llm/riscrivo/runtime/reports/p2p-next-investigation-20261021')
OLD=R.parent/'p2p-tcss-bit-tests-20261021'
OUT=R/'native-traffic-probe'
ROOT=OUT/'unpacked'
PACKAGE=R/'native-traffic-probe-package'
BASE=OLD/'native-ce-probe/unpacked'
BASE_PACKAGE=OLD/'native-ce-probe-package'
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
contract=json.loads((R/'traffic-build-inputs.json').read_text())
assert contract['status']=='reviewed_for_build'
for p,d in contract['files'].items():assert sha(R/p)==d,p
shutil.copytree(BASE,ROOT,symlinks=True)
PACKAGE.mkdir()
program=OUT/'peer_traffic_native'
for source,target in [(program,ROOT/'opt/probe/peer_word'),(R/'init-traffic.sh',ROOT/'init')]:
 assert target.is_file() and not target.is_symlink()
 target.unlink();shutil.copy2(source,target)
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
(PACKAGE/'IDENTITY.txt').write_text('CaskLogic-TCSS-traffic-20261021\n')
files={n:sha(PACKAGE/n) for n in ('probe-kernel.efi','probe-initrd.img','IDENTITY.txt')}
assert files['probe-kernel.efi']=='9f55ef7253055a9cf68f8a04323c93dead2fca617386d842fbde9ca7b178b27e'
manifest={
 'built_not_booted':True,'files':files,'input_files':contract['files'],
 'build_inputs_sha256':sha(R/'traffic-build-inputs.json'),
 'baseline_package_initrd_sha256':old['files']['probe-initrd.img'],
 'intended_payload_changes':['init','opt/probe/peer_word'],
 'initrd_bytes':(PACKAGE/'probe-initrd.img').stat().st_size,
 'native_program_sha256':sha(program),'init_sha256':sha(ROOT/'init'),
 'module_sha256':old['module_sha256'],'uvm_module_sha256':old['uvm_module_sha256'],'libcuda_sha256':old['libcuda_sha256'],
 'expected_CCFG':{'00:01.0':'04008077','00:07.0':'0e009077','00:07.2':'0e009077'},
 'automatic_return_seconds':182,'program_timeout_seconds':60,
 'vm_disks_mounted':False,'pci_config_writes':False,'firmware_writes':False,
 'comparisons':4,'sizes':[1048576],'modes':['PUSH'],
 'engines':['SM','CUDA_COPY_REQUEST'], 'CE_observed_in_this_probe':False,'direct_route_proven':False,
 'nvml_library_sha256':nvml_sha,
 'payload_files':{p:sha(ROOT/p) for p in list(old['payload_files'])+[nvml_path]}
}
for p,d in manifest['payload_files'].items():
 if p==nvml_path:assert d==nvml_sha,p
 elif p not in manifest['intended_payload_changes']:assert d==old['payload_files'][p],p
(PACKAGE/'files.json').write_text(json.dumps(files,indent=2)+'\n')
(PACKAGE/'build-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'package':str(PACKAGE),'files':files,'bytes':manifest['initrd_bytes']}))
