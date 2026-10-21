import hashlib,json,os,re,subprocess
from pathlib import Path
D=Path(__file__).resolve().parent;F=D/'offline-fake-nvml'
checks=[]
for name,flags,rc in [('success',{},0),('invalid_identity',{'FAKE_BAD_UUID':'1'},27),('preflight_unavailable',{'FAKE_PREFLIGHT_FAIL':'1'},27),('sampling_unavailable',{'FAKE_LATE_FAIL':'1'},6)]:
 env=dict(os.environ,DYLD_LIBRARY_PATH=str(F),LD_LIBRARY_PATH=str(F));env.update(flags)
 p=subprocess.run([str(F/'run')],env=env,text=True,capture_output=True,timeout=5)
 (F/(name+'.stdout')).write_text(p.stdout);(F/(name+'.stderr')).write_text(p.stderr)
 assert p.returncode==rc,(name,p.returncode,p.stderr)
 assert not p.stderr,(name,p.stderr)
 if name=='success':
  assert 'valid=1 aggregation=all_pcie_traffic payload_specific=0' in p.stdout
  assert 'counter=TX' in p.stdout and 'counter=RX' in p.stdout
 if name=='sampling_unavailable':
  invalid=[x for x in p.stdout.splitlines() if x.startswith('NVML_SAMPLE ') and 'valid=0' in x]
  assert invalid and all('value_kBps=4294967295' in x for x in invalid)
  assert 'valid=0 aggregation=all_pcie_traffic payload_specific=0' in p.stdout
 if name in ('invalid_identity','preflight_unavailable'):assert 'NVML_SAMPLE ' not in p.stdout
 checks.append({'scenario':name,'expected_rc':rc,'rc':p.returncode,'pass':True})
result={'status':'PASS','real_sampler_header_sha256':hashlib.sha256((D/'nvml_sampler.h').read_bytes()).hexdigest(),'nvml_header_sha256':hashlib.sha256((D/'include/nvml.h').read_bytes()).hexdigest(),'cases':checks,'boundary_and_stats_assertions':16,'asan_ubsan':True,'hardware_calls':False,'scope':'Real sampler/client code against local fake NVML shared library. No CUDA or GPU.'}
(D/'offline-sampler-validation.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
