import importlib.util,sys,unittest
from pathlib import Path
from analyze_physical import audit,records,fields
HERE=Path(__file__).resolve().parent
OLD=HERE.parent/'native-traffic-probe'
sys.path.insert(0,str(OLD))
spec=importlib.util.spec_from_file_location('old_fixture',OLD/'test_analyze_traffic.py');old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)

def fixture():
 lines=[]
 def emit(kind,**v):lines.append(kind+' '+' '.join(f'{k}={x}' for k,x in v.items()))
 ids=[('0000:01:00.0','00000000000000000000000000000001'),('0000:06:00.0','00000000000000000000000000000002')]
 def identity(i):emit('PHYS_GPU',index=i,bdf=ids[i][0],uuid=ids[i][1],name='fixture',valid=1)
 buffers={(i,r):f'{0x100000000+(i*2+(r=="receive"))*0x800000:x}' for i in (0,1) for r in ('send','receive')}
 def access(i,r,stage):
  for device in (0,1):
   expected=0 if r=='send' and device!=i else 3
   emit('PHYS_ACCESS',stage=stage,owner=i,role=r,device=device,va=buffers[i,r],last_va=f'{int(buffers[i,r],16)+8388607:x}',first=expected,last=expected,expected=expected,allocation_type=1,location_type=1,location_id=i,valid=1)
 def full(stage,owner,s,d,size,iteration,mismatch=0):emit('FULL_COMPARE',stage=stage,owner=owner,s=s,d=d,bytes=size,iteration=iteration,checked_words=size//4,mismatches=mismatch,valid=int(not mismatch),first_expected='12345678')
 def executor(owner,i):emit('PHYS_EXECUTOR',id=i,device=owner,current='0x123',stream_context='0x123',stream='0x456',valid=1)
 emit('PHYS_NATIVE_CPU',vendor='GenuineIntel',eax='000906a3',hypervisor=0,valid=1)
 for bdf,pciid in {'0000:00:00.0':0x46418086,'0000:00:01.0':0x460d8086,'0000:00:07.0':0x466e8086,'0000:04:00.0':0x24611b21,'0000:05:00.0':0x24611b21}.items():emit('PHYS_NATIVE_PCI',bdf=bdf,id=f'{pciid:08x}',expected=f'{pciid:08x}',valid=1)
 for owner in (0,1):
  identity(owner)
  for role in ('send','receive'):emit('PHYS_ALLOCATION',owner=owner,role=role,va=buffers[owner,role],nonce=f'{owner}-{role}',handle=1,allocation_bytes=8388608,granularity=2097152);access(owner,role,'created')
 emit('PHYS_FD_VALIDATION',fd=5,request=100,rv=0,errno=0,rmStatus=0,flags=1,valid=1)
 emit('PHYS_FD_SELECTED',original=5,retained_fd=6,candidates=1,matches=1)
 for i in range(1,5):
  s=(i-1)//2;d=1-s;engine='SM' if i%2 else 'PHYSICAL_CE'
  identity(s);identity(d);access(s,'send','before_p2p');access(d,'receive','before_p2p')
  emit('PHYS_CASE',id=i,engine=engine,s=s,d=d,executor=s,bytes=4,src=buffers[s,'send'],dst=buffers[d,'receive'],expected='12345678',poison='edcba987',allocations_unchanged=1)
  full('source_initialized',s,s,d,4,i);full('destination_poisoned',d,s,d,4,i);executor(s,i)
  if engine=='PHYSICAL_CE':
   target=0x4600400000 if d==1 else 0x4000400000
   emit('PHYS_IOCTL_RESULT',request=100+i,src=buffers[s,'send'],dst=buffers[d,'receive'],bytes=4,rv=0,errno=0,rmStatus=0,flags='77',source_pa='200000',destination_pa=f'{target:x}',source_offset=0,destination_offset=0,source_handle='12',destination_handle='13',ce_class='c7b5',launch='4003186',source_mode=0,destination_mode=2,inputs_unchanged=1)
   emit('PHYS_BAR1',owner=d,start=f'{target-0x400000:x}',end=f'{target+0xffffff:x}',flags='200',destination_physical=f'{target:x}',valid=1)
  mismatch=int(s==0);full('peer_payload',d,s,d,4,i,mismatch)
  emit('PHYS_DATA_RESULT',id=i,engine=engine,s=s,d=d,bytes=4,checked_words=1,mismatches=mismatch,valid=1-mismatch,physical_ioctl_completed=int(engine=='PHYSICAL_CE'),direct_route_proven=0)
  access(s,'send','after_p2p');access(d,'receive','after_p2p')
 emit('PHYS_P2P_END',comparisons=4,failures=2,physical_completed=2,protocol_complete=1)
 emit('NVML_INIT',rc=0,valid=1)
 oldlines=old.BASE.splitlines()
 lines.extend(x for x in oldlines if x.startswith(('NVML_IDENTITY ','NVML_PREFLIGHT ')))
 for i in range(1,5):
  owner=(i-1)//2;op='HOST_TO_DEVICE' if i%2 else 'DEVICE_TO_HOST'
  identity(owner);access(owner,'send','before_cpu_calibration');full('calibration_owner_initialized',owner,owner,owner,1048576,i);executor(owner,i)
  emit('CALIBRATION_CASE',id=i,operation=op,owner=owner,bytes=1048576,gpu_va=buffers[owner,'send'],host='0xdeadbeef',owner_only=1,peer_access='NONE',p2p=0,batch_copies=64,target_ns=1200000000,limit_ns=5000000000)
  window=next(fields(x) for x in oldlines if x.startswith('TRAFFIC_WINDOW ') and int(fields(x)['id'])==i)
  for k in ('begin_ns','end_ns','sampler_joined_ns'):window[k]=str(int(window[k])+1800000000)
  emit('CALIBRATION_WINDOW',id=i,operation=op,owner=owner,**{k:window[k] for k in ('begin_ns','end_ns','sampler_joined_ns','duration_ns','batches','budget_exhausted')},submitted_host_payload_bytes=window['submitted_payload_bytes'],p2p=0)
  for x in oldlines:
   if not x.startswith(('NVML_SAMPLE ','NVML_STATS ','NVML_SAMPLER_END ')) or int(fields(x)['phase'])!=i:continue
   kind=x.split()[0];values=fields(x)
   if kind=='NVML_SAMPLE' and values['stage']!='BASELINE':
    for k in ('begin_ns','end_ns'):values[k]=str(int(values[k])+1800000000)
   if kind=='NVML_SAMPLER_END':values['joined_ns']=str(int(values['joined_ns'])+1800000000)
   emit(kind,**values)
  emit('CaskLogicPhysicalCE',phase='calibration_sampler_joined',monotonic=f"{(int(window['sampler_joined_ns'])+1000)/1e9:.9f}",s=owner,d=owner)
  full('calibration_host_payload',owner,owner,owner,1048576,i);full('calibration_owner_payload',owner,owner,owner,1048576,i)
  emit('CALIBRATION_DATA_RESULT',id=i,operation=op,owner=owner,bytes=1048576,host_mismatches=0,owner_mismatches=0,valid=1,sampling_valid=1,duration_valid=1,p2p=0,counter_sensitivity_proven=0)
  access(owner,'send','after_cpu_calibration')
 emit('CaskLogicPhysicalCE',phase='data_done',monotonic='24.0',s=-1,d=-1)
 for i in range(4):
  for p in ('allocation_free_begin','allocation_free_done'):emit('CaskLogicPhysicalCE',phase=p,monotonic='25.0',s=i//2,d=-1)
 emit('CaskLogicPhysicalCE',phase='cleanup_done',monotonic='26.0',s=-1,d=-1)
 emit('PHYS_PROGRAM_END',protocol_complete=1,p2p_comparisons=4,p2p_failures=2,physical_completed=2,calibrations=4,calibration_failures=0,qualified_windows=4,direct_route_proven=0,rc=5)
 return '\n'.join(lines)+'\n'
BASE=fixture()
class Audit(unittest.TestCase):
 def test_complete(self):
  r=audit(BASE);self.assertEqual((r['p2p_failures'],r['qualified_windows']),(2,4));self.assertFalse(r['p2p_solution_proven'])
 def bad(self,old,new):
  changed=BASE.replace(old,new,1);self.assertNotEqual(BASE,changed)
  with self.assertRaises((ValueError,KeyError)):audit(changed)
 def test_missing_final(self):
  with self.assertRaises(ValueError):audit(BASE[:BASE.index('PHYS_PROGRAM_END')])
 def test_retained(self):
  with self.assertRaises(ValueError):audit(BASE+'PHYS_CE_RETAINED parked=1\n')
 def test_input_changed(self):self.bad('inputs_unchanged=1','inputs_unchanged=0')
 def test_flags(self):self.bad('flags=77','flags=73')
 def test_mode(self):self.bad('destination_mode=2','destination_mode=1')
 def test_launch(self):self.bad('launch=4003186','launch=4003182')
 def test_class(self):self.bad('ce_class=c7b5','ce_class=c6b5')
 def test_pa(self):self.bad('destination_pa=4600400000','destination_pa=4600400004')
 def test_bar_wrong_owner(self):self.bad('PHYS_BAR1 owner=1','PHYS_BAR1 owner=0')
 def test_fd_ambiguous(self):self.bad('matches=1','matches=2')
 def test_physical_error(self):self.bad('flags=77','flags=7f')
 def test_source_shared(self):self.bad('first=0 last=0 expected=0','first=3 last=3 expected=3')
 def test_calibration_shared(self):self.bad('owner_only=1 peer_access=NONE','owner_only=1 peer_access=RW')
 def test_calibration_is_p2p(self):self.bad('peer_access=NONE p2p=0','peer_access=NONE p2p=1')
 def test_sensitivity_claim(self):self.bad('counter_sensitivity_proven=0','counter_sensitivity_proven=1')
 def test_baseline_short(self):self.bad('started_ns=5000000000','started_ns=5000000001')
 def test_bad_stats(self):self.bad('mean_kBps=100.000','mean_kBps=101.000')
 def test_wrong_sample_flag(self):self.bad('interior=0 baseline_quiet=1','interior=1 baseline_quiet=1')
 def test_false_final(self):self.bad('p2p_failures=2','p2p_failures=0')
 def test_nvml_during_physical(self):
  changed=BASE.replace('NVML_INIT rc=0 valid=1\n','');changed='NVML_INIT rc=0 valid=1\n'+changed
  with self.assertRaises(ValueError):audit(changed)
 def test_free_before_finish(self):
  changed=BASE.replace('CaskLogicPhysicalCE phase=allocation_free_begin monotonic=25.0 s=0 d=-1\n','',1)
  changed='CaskLogicPhysicalCE phase=allocation_free_begin monotonic=25.0 s=0 d=-1\n'+changed
  with self.assertRaises(ValueError):audit(changed)
 def test_wrong_cpu(self):self.bad('eax=000906a3','eax=000906a2')
if __name__=='__main__':unittest.main()
