from pathlib import Path
import gzip,hashlib,json,stat
r=Path('ARCHIVE_ROOT/p2p-tcss-bit-tests-20261021');p=r/'native-ce-probe-package';q=r/'native-ce-probe'
def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for x in iter(lambda:f.read(1<<20),b''):h.update(x)
 return h.hexdigest()
m=json.loads((p/'build-manifest.json').read_text());files=json.loads((p/'files.json').read_text());contract=json.loads((q/'build-inputs.json').read_text());checks={}
assert files==m['files']
for name,expected in files.items():
 assert Path(name).name==name
 actual=sha(p/name);assert actual==expected,(name,actual,expected);checks[name]=actual
assert checks['probe-initrd.img']=='2f912fcfca5f69616b4f18159e777b28b60023ebe4e24d3e53a9d4ff7193fd72'
assert checks['probe-kernel.efi']=='9f55ef7253055a9cf68f8a04323c93dead2fca617386d842fbde9ca7b178b27e'
assert (p/'probe-initrd.img').stat().st_size==m['initrd_bytes']==279245127
assert sha(q/'build-inputs.json')==m['build_inputs_sha256']=='54d585473c8738687eac7e6eba15867ae862c3d381baa4679f93e5081572ac23'
assert m['input_files']==contract['files']
for name,expected in m['input_files'].items(): assert sha(q/name)==expected,name
assert m['module_sha256']=='ab41b0a38e7ab92c0d1468b33c456c5c5c57501c67dfe5a666f49aed9fb6b1b5'
assert m['uvm_module_sha256']=='9b993671ef066c9d3e58fd52b0d70228861769a2e3dcf304bc3d80bca089c4d0'
assert m['libcuda_sha256']=='03271500dbda9456e3ba765270bd2609bef2631672809da50b19c67fb1f609a7'
assert m['native_program_sha256']=='7184d44dc039f662b21c86b1f20e644b21a3188bb7c028a8a0b12084bcdcfa4d'
expected=dict(m['payload_files']);assert len(expected)==6
expected.update({'usr/lib/x86_64-linux-gnu/'+Path(n).name:h for n,h in m['input_files'].items() if n.startswith('lib/')});found={};members=0
with gzip.open(p/'probe-initrd.img','rb') as f:
 while True:
  h=f.read(110);assert len(h)==110 and h[:6] in (b'070701',b'070702')
  a=[int(h[6+i*8:14+i*8],16) for i in range(13)];mode=a[1];size=a[6];namesize=a[11]
  name=f.read(namesize);assert name.endswith(b'\0');name=name[:-1].decode();assert len(f.read((-110-namesize)%4))==(-110-namesize)%4
  if name=='TRAILER!!!':break
  members+=1;name=name.removeprefix('./');digest=hashlib.sha256();left=size
  while left:
   part=f.read(min(1<<20,left));assert part;left-=len(part);digest.update(part)
  assert len(f.read((-size)%4))==(-size)%4
  if name in expected:
   assert name not in found and stat.S_ISREG(mode),(name,mode)
   found[name]={'sha256':digest.hexdigest(),'bytes':size,'mode':oct(mode)}
   assert digest.hexdigest()==expected[name],(name,digest.hexdigest(),expected[name])
 # Read remaining padding through EOF to validate gzip CRC, and reject concatenated payloads.
 trailing=f.read();assert not trailing.strip(b'\0'), 'unexpected nonzero bytes after cpio trailer'
assert set(found)==set(expected)
init=(q/'init-tcss-native.sh').read_text()
assert ";RM64KBBAR1Mappings=0'" in init
assert all(x not in init for x in ['RMCaskPeerCoherent','uvm_cask_peer_small_pages','cask_low_mmio','pci_attrs'])
assert 'timeout 60 /opt/probe/peer_word' in init and 'sleep 180' in init and 'echo PROBE_COMPLETED' in init
assert m['automatic_return_seconds']==180 and m['program_timeout_seconds']==60 and m['comparisons']==12 and m['sizes']==[4,65536,1048576] and m['direct_route_proven'] is False
report={'status':'PASS_STREAMED_CPIO_AND_INPUT_PROVENANCE','files_sha256_verified':checks,'archive_members':members,'archive_targets_verified':found,'required_payload_count':6,'additional_CUPTI_library_count':4,'input_file_count':len(m['input_files']),'input_manifest_preserved':True,'build_inputs_sha256':m['build_inputs_sha256'],'input_files_rehashed':m['input_files'],'RM_baseline_unchanged':True,'UVM_baseline_2MiB_unchanged':True,'patched_libcuda_actual_initrd_verified':True,'CUPTI_actual_initrd_verified':True,'effective_registry':'ForceP2P=0x11;RMForceP2PType=1;RMPcieP2PType=1;RMForceStaticBar1=0;RM64KBBAR1Mappings=0','no_coherent_smallpage_lowBAR_NoSnoop_in_init':True,'probe_timeout_seconds':60,'watchdog_seconds':180,'comparisons_expected':12,'hardware_operations':False,'direct_route_proven':False,'limits':['Local streaming verification only; no binary or GPU execution.','A successful CUDA memcpy or CUPTI activity does not alone prove direct PCIe transport.','Execution report must distinguish completed comparisons, callback correlation, dropped records and CUPTI timestamps from CLOCK_MONOTONIC.']}
(q/'independent-package-review-storico.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'status':report['status'],'archive_members':members,'targets':len(found),'input_files':len(m['input_files']),'program':m['native_program_sha256'],'timeout':60,'watchdog':180}))
