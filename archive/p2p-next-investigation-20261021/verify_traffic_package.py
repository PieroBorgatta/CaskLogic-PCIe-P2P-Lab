"""Read-only streamed comparison of native CPIO contents and payload provenance."""
from pathlib import Path
import gzip,hashlib,json,stat
R=Path(__file__).resolve().parent
OLD=R.parent/'p2p-tcss-bit-tests-20261021/native-ce-probe-package'
NEW=R/'native-traffic-probe-package'
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def inventory(path):
 found={}
 with gzip.open(path,'rb') as f:
  while True:
   h=f.read(110)
   assert len(h)==110 and h[:6] in (b'070701',b'070702')
   a=[int(h[6+i*8:14+i*8],16) for i in range(13)]
   size,namesize=a[6],a[11]
   assert 0<namesize<4096 and size<(1<<31)
   name=f.read(namesize);assert len(name)==namesize and name.endswith(b'\0')
   name=name[:-1].decode();n=(-110-namesize)%4;assert len(f.read(n))==n
   if name=='TRAILER!!!':assert size==0;break
   if name.startswith('./'):name=name[2:]
   assert not name.startswith('/') and '..' not in Path(name).parts and name not in found
   digest=hashlib.sha256();left=size
   while left:
    b=f.read(min(1<<20,left));assert b;left-=len(b);digest.update(b)
   n=(-size)%4;assert len(f.read(n))==n
   found[name]={'bytes':size,'sha256':digest.hexdigest(),'mode':a[1]}
  assert not f.read().strip(b'\0')
 return found
m=json.loads((NEW/'build-manifest.json').read_text())
assert m['files']==json.loads((NEW/'files.json').read_text())
for n,d in m['files'].items():assert Path(n).name==n and sha(NEW/n)==d,n
assert m['files']['probe-kernel.efi']=='9f55ef7253055a9cf68f8a04323c93dead2fca617386d842fbde9ca7b178b27e'
assert sha(OLD/'probe-initrd.img')==m['baseline_package_initrd_sha256']=='2f912fcfca5f69616b4f18159e777b28b60023ebe4e24d3e53a9d4ff7193fd72'
old=inventory(OLD/'probe-initrd.img');new=inventory(NEW/'probe-initrd.img')
assert old.keys()==new.keys()
changed=[]
for n in new:
 assert old[n]['mode']==new[n]['mode'],n
 if old[n]['sha256']!=new[n]['sha256'] or old[n]['bytes']!=new[n]['bytes']:changed.append(n)
assert set(changed)=={'init','opt/probe/peer_word'},changed
for p,d in m['payload_files'].items():assert stat.S_ISREG(new[p]['mode']) and new[p]['sha256']==d,p
contract=json.loads((R/'traffic-build-inputs.json').read_text())
assert sha(R/'traffic-build-inputs.json')==m['build_inputs_sha256']
assert contract['files']==m['input_files']
for p,d in contract['files'].items():assert sha(R/p)==d,p
assert new['init']['sha256']==sha(R/'init-traffic.sh')==m['init_sha256']
assert new['opt/probe/peer_word']['sha256']==sha(R/'native-traffic-probe/peer_traffic_native')==m['native_program_sha256']
assert m['module_sha256']=='ab41b0a38e7ab92c0d1468b33c456c5c5c57501c67dfe5a666f49aed9fb6b1b5'
assert m['uvm_module_sha256']=='9b993671ef066c9d3e58fd52b0d70228861769a2e3dcf304bc3d80bca089c4d0'
assert m['libcuda_sha256']=='03271500dbda9456e3ba765270bd2609bef2631672809da50b19c67fb1f609a7'
assert m['expected_CCFG']=={'00:01.0':'04008077','00:07.0':'0e009077','00:07.2':'0e009077'}
assert m['comparisons']==4 and m['sizes']==[1048576] and not m['direct_route_proven']
assert m['nvml_library_sha256']==m['payload_files']['usr/lib/x86_64-linux-gnu/libnvidia-ml.so.1']=='770e9de75c14b07cce9718b214700b10e6d6866f7383101d6fe530352543b1de'
assert (NEW/'IDENTITY.txt').read_text()=='CaskLogic-TCSS-traffic-20261021\n'
report={'status':'PASS_COMPLETE_ARCHIVE_DIFFERENCE_AND_PROVENANCE','files':m['files'],'members':len(new),'changed_payloads':changed,'unchanged_payloads':len(new)-len(changed),'input_files_verified':len(contract['files']),'payloads':m['payload_files'],'gzip_crc_verified':True,'hardware_test_executed_by_verifier':False}
(NEW/'local-package-verification.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
