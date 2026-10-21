import copy,json,unittest
from pathlib import Path
from analyze_traffic import audit,fields
D=Path(__file__).resolve().parent

def fixture():
 lines=[]
 def emit(kind,**v):lines.append(kind+' '+' '.join(f'{k}={x}' for k,x in v.items()))
 ids=[('0000:01:00.0','00000000000000000000000000000001'),('0000:06:00.0','00000000000000000000000000000002')]
 def identity(i):emit('TRAFFIC_GPU',index=i,bdf=ids[i][0],uuid=ids[i][1],name='fixture',valid=1)
 buffers={(i,r):hex(0x100000000+(i*2+(r=='receive'))*0x800000)[2:] for i in (0,1) for r in ('send','receive')}
 def access(i,r,stage):
  for device in (0,1):
   expected=0 if r=='send' and device!=i else 3
   emit('TRAFFIC_ACCESS',stage=stage,owner=i,role=r,device=device,va=buffers[i,r],last_va=hex(int(buffers[i,r],16)+8388607)[2:],first=expected,last=expected,expected=expected,allocation_type=1,location_type=1,location_id=i,valid=1)
 for i in (0,1):
  identity(i);u=ids[i][1];u='GPU-'+u[:8]+'-'+u[8:12]+'-'+u[12:16]+'-'+u[16:20]+'-'+u[20:]
  emit('NVML_IDENTITY',device=i,bdf=ids[i][0],uuid=u,handle_rc=0,uuid_rc=0,valid=1)
  for c in ('TX','RX'):emit('NVML_PREFLIGHT',device=i,counter=c,rc=0,valid=1,value_kBps=100,begin_ns=1,end_ns=2)
  for r in ('send','receive'):
   emit('TRAFFIC_ALLOCATION',nonce=f'{i}-{r}',owner=i,role=r,va=buffers[i,r],handle=1,allocation_bytes=8388608,granularity=2097152);access(i,r,'created')
 for phase in range(1,5):
  source=(phase-1)//2;target=1-source;engine='SM' if phase%2 else 'CUDA_COPY_REQUEST'
  identity(source);identity(target);access(source,'send','before_phase');access(target,'receive','before_phase')
  emit('TRAFFIC_CASE',id=phase,engine=engine,s=source,d=target,executor=source,bytes=1048576,batch_copies=64,max_batches=4096,target_ns=1200000000,limit_ns=5000000000,src=buffers[source,'send'],dst=buffers[target,'receive'],allocations_unchanged=1,ce_observed=0)
  for role,owner in [('source_initialized',source),('destination_poisoned',target)]:emit('FULL_COMPARE',stage=role,owner=owner,s=source,d=target,bytes=1048576,iteration=phase,checked_words=262144,mismatches=0,valid=1)
  emit('TRAFFIC_EXECUTOR',id=phase,device=source,current='0x123',stream_context='0x123',stream='0x456',valid=1)
  start=phase*5000000000;begin=start+200000000;end=begin+1200000000;join=end+100000000
  emit('TRAFFIC_WINDOW',id=phase,engine=engine,s=source,d=target,begin_ns=begin,end_ns=end,sampler_joined_ns=join,duration_ns=end-begin,batches=10,submitted_payload_bytes=10*64*1048576,budget_exhausted=0,no_host_payload_ops_during_window=1)
  values={};samples=0;interior=quiet=0
  for stage,stamps in [('BASELINE',[start+50000000+x*20000000 for x in range(7)]),('ACTIVE',[begin+60000000+x*20000000 for x in range(10)]),('TAIL',[end+20000000+x*20000000 for x in range(4)])]:
   for t in stamps:
    for d in (0,1):
     for ci,c in enumerate(('TX','RX')):
      a=t+(d*2+ci)*1000;b=a+100;v=100+d*10+ci+(1000 if stage=='ACTIVE' else 0)
      use=stage=='ACTIVE';q=stage=='BASELINE';samples+=1;interior+=use;quiet+=q
      emit('NVML_SAMPLE',phase=phase,stage=stage,device=d,counter=c,begin_ns=a,end_ns=b,rc=0,valid=1,value_kBps=v,interior=int(use),baseline_quiet=int(q))
      k=('BASELINE_QUIET' if q else 'ACTIVE_INTERIOR' if use else 'TAIL',d,c);values.setdefault(k,[]).append(v)
  for (stage,d,c),v in values.items():emit('NVML_STATS',phase=phase,stage=stage,device=d,counter=c,valid_count=len(v),invalid_count=0,mean_kBps=f'{sum(v)/len(v):.3f}',min_kBps=min(v),max_kBps=max(v),available=1)
  emit('NVML_SAMPLER_END',phase=phase,started_ns=start,joined_ns=join+100,samples=samples,interior_samples=interior,baseline_quiet_samples=quiet,overflow=0,exception=0,valid=1,aggregation='all_pcie_traffic',payload_specific=0)
  emit('CaskLogicTraffic',phase='sampler_joined',monotonic=f'{(join+200)/1e9:.9f}',s=source,d=target)
  mismatch=262144 if source==0 else 0
  emit('FULL_COMPARE',stage='peer_payload',owner=target,s=source,d=target,bytes=1048576,iteration=phase,checked_words=262144,mismatches=mismatch,valid=int(mismatch==0))
  emit('TRAFFIC_DATA_RESULT',id=phase,engine=engine,s=source,d=target,bytes=1048576,checked_words=262144,mismatches=mismatch,valid=int(mismatch==0),sampling_valid=1,duration_valid=1,ce_observed=0,direct_route_proven=0)
  access(source,'send','after_phase');access(target,'receive','after_phase')
 emit('CaskLogicTraffic',phase='data_done',monotonic='22.000000000',s=-1,d=-1)
 for i in range(4):
  for phase in ('allocation_free_begin','allocation_free_done'):emit('CaskLogicTraffic',phase=phase,monotonic=f'22.00000{i}000',s=i//2,d=-1)
 emit('CaskLogicTraffic',phase='cleanup_done',monotonic='22.010000000',s=-1,d=-1)
 emit('TRAFFIC_PROGRAM_END',protocol_complete=1,comparisons=4,failures=2,qualified_windows=4,nvml_only=1,ce_observed=0,direct_route_proven=0,rc=5)
 return '\n'.join(lines)+'\n'

BASE=fixture()
class TestAudit(unittest.TestCase):
 def test_complete(self):
  r=audit(BASE);self.assertEqual((r['data_failures'],r['qualified_windows']),(2,4));self.assertFalse(r['p2p_solution_proven'])
 def bad(self,old,new):
  changed=BASE.replace(old,new,1);self.assertNotEqual(BASE,changed)
  with self.assertRaises((ValueError,KeyError)):audit(changed)
 def test_missing_final(self):
  with self.assertRaises(ValueError):audit(BASE[:BASE.index('TRAFFIC_PROGRAM_END')])
 def test_wrong_gpu(self):self.bad('uuid=00000000000000000000000000000001','uuid=wrong')
 def test_fake_ce_claim(self):self.bad('ce_observed=0','ce_observed=1')
 def test_fake_no_host(self):self.bad('no_host_payload_ops_during_window=1','no_host_payload_ops_during_window=0')
 def test_submitted_count(self):self.bad('submitted_payload_bytes=671088640','submitted_payload_bytes=671088641')
 def test_stats_mean(self):self.bad('mean_kBps=100.000','mean_kBps=101.000')
 def test_stats_count(self):self.bad('valid_count=7','valid_count=8')
 def test_stats_min(self):self.bad('min_kBps=100','min_kBps=99')
 def test_rc_zero_value(self):self.bad('rc=0 valid=1 value_kBps=100 interior=0','rc=3 valid=0 value_kBps=0 interior=0')
 def test_baseline_flag(self):self.bad('interior=0 baseline_quiet=1','interior=0 baseline_quiet=0')
 def test_interior_flag(self):self.bad('interior=1 baseline_quiet=0','interior=0 baseline_quiet=0')
 def test_drop_sample(self):
  l=BASE.splitlines();l.pop(next(i for i,x in enumerate(l) if x.startswith('NVML_SAMPLE')))
  with self.assertRaises(ValueError):audit('\n'.join(l))
 def test_late_join(self):self.bad('sampler_joined_ns=6500000000','sampler_joined_ns=6400000000')
 def test_payload_valid(self):self.bad('mismatches=262144 valid=0','mismatches=262144 valid=1')
 def test_false_final(self):self.bad('failures=2 qualified_windows=4','failures=0 qualified_windows=4')
 def test_wrong_executor(self):self.bad('executor=0','executor=1')
 def test_source_shared(self):self.bad('first=0 last=0 expected=0','first=3 last=3 expected=3')
 def test_wrong_physical_owner(self):self.bad('allocation_type=1 location_type=1 location_id=0','allocation_type=1 location_type=1 location_id=1')
 def test_duplicate_case(self):self.bad('TRAFFIC_CASE id=2','TRAFFIC_CASE id=1')
 def test_overflow_ignored(self):self.bad('overflow=0 exception=0 valid=1','overflow=1 exception=0 valid=1')
 def test_short_duration(self):self.bad('duration_ns=1200000000','duration_ns=1000000000')
if __name__=='__main__':
 (D/'fixture-complete.log').write_text(BASE)
 unittest.main()
