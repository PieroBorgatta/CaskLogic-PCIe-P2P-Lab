#!/usr/bin/env python3
"""Offline qualification. P2P data, physical ioctl metadata and CPU calibrations are distinct."""
import argparse,hashlib,json
from pathlib import Path
from nvml_analysis_core import fields,records,require,one,num,audit_samples

IDS={0:('0000:01:00.0','00000000000000000000000000000001'),1:('0000:06:00.0','00000000000000000000000000000002')}
def hx(x,k):return int(x[k],16)
def audit(text):
 lines=text.splitlines();rec=lambda p:records(lines,p)
 require(not any(x.startswith(('PHYS_ABORT ','PHYS_CE_RETAINED ','CUDA_ERROR ','DRIVER_ERROR ','FATAL ')) for x in lines),'runtime_abort_or_retained')
 final=one(rec('PHYS_PROGRAM_END'),'final_count');p2pend=one(rec('PHYS_P2P_END'),'p2p_end_count')
 cases=rec('PHYS_CASE');data=rec('PHYS_DATA_RESULT');ioctls=rec('PHYS_IOCTL_RESULT');bar=rec('PHYS_BAR1')
 for xs in (cases,data):require([int(x['id']) for x in xs]==[1,2,3,4],'p2p_ordered_four')
 require(len(ioctls)==len(bar)==2,'two_physical_completions')
 selected=one(rec('PHYS_FD_SELECTED'),'one_selected_fd');require(int(selected['matches'])==1,'one_valid_fd')
 validations=rec('PHYS_FD_VALIDATION');require(sum(x['valid']=='1' for x in validations)==1,'one_validation')
 v=one([x for x in validations if x['valid']=='1'],'valid_validation');require(num(v,'rv','rmStatus')==(0,0) and hx(v,'flags')==1,'validation_flags');require(v['line']<selected['line']<cases[0]['line'],'fd_before_cases')
 native=one(rec('PHYS_NATIVE_CPU'),'native_cpu');require(native['vendor']=='GenuineIntel' and hx(native,'eax')==0x906a3 and num(native,'hypervisor','valid')==(0,1),'native_cpu_fields')
 pci=rec('PHYS_NATIVE_PCI');expectpci={'0000:00:00.0':0x46418086,'0000:00:01.0':0x460d8086,'0000:00:07.0':0x466e8086,'0000:04:00.0':0x24611b21,'0000:05:00.0':0x24611b21}
 require(len(pci)==5 and {x['bdf'] for x in pci}==set(expectpci),'native_pci_count')
 for x in pci:require(hx(x,'id')==hx(x,'expected')==expectpci[x['bdf']] and x['valid']=='1','native_pci_identity')
 gpu=rec('PHYS_GPU');require(len(gpu)==14,'gpu_identity_count')
 for x in gpu:require((x['bdf'],x['uuid'])==IDS[int(x['index'])] and x['valid']=='1','gpu_identity')
 allocations=rec('PHYS_ALLOCATION');require(len(allocations)==4 and len({x['va'] for x in allocations})==4 and len({x['nonce'] for x in allocations})==4,'allocations_unique')
 buffers={(int(x['owner']),x['role']):x for x in allocations};require(set(buffers)=={(i,r) for i in (0,1) for r in ('send','receive')},'allocation_identity')
 for x in allocations:require(int(x['allocation_bytes'])==8388608 and int(x['granularity'])>0 and 8388608%int(x['granularity'])==0,'allocation_geometry')
 require(max(x['line'] for x in allocations)<cases[0]['line'],'allocation_order')
 access=rec('PHYS_ACCESS');require(len(access)==56,'rights_count')
 for x in access:
  owner=int(x['owner']);d=int(x['device']);a=buffers[(owner,x['role'])];e=0 if x['role']=='send' and owner!=d else 3
  require(num(x,'first','last','expected','valid')==(e,e,e,1),'access_value')
  require(x['va']==a['va'] and hx(x,'last_va')==hx(a,'va')+8388607,'access_range');require(num(x,'allocation_type','location_type','location_id')==(1,1,owner),'access_property')
 full=rec('FULL_COMPARE');require(len(full)==24,'full_compare_count');executors=rec('PHYS_EXECUTOR');require(len(executors)==8,'executor_count')
 for e in executors:require(e['current']==e['stream_context'] and e['valid']=='1','executor_context')
 p2p=[];failures=0;request_ids=set()
 for i,(c,d) in enumerate(zip(cases,data),1):
  source=(i-1)//2;target=1-source;engine='SM' if i%2 else 'PHYSICAL_CE'
  require(num(c,'s','d','executor','bytes')==(source,target,source,4) and c['engine']==engine and c['allocations_unchanged']=='1','p2p_contract')
  require(c['src']==buffers[(source,'send')]['va'] and c['dst']==buffers[(target,'receive')]['va'],'same_allocations')
  require(hx(c,'poison')==(hx(c,'expected')^0xffffffff),'poison_differs')
  e=one([x for x in executors if c['line']<x['line']<d['line']],'p2p_executor');require(int(e['device'])==source,'p2p_executor_device')
  for stage,owner in [('source_initialized',source),('destination_poisoned',target)]:
   f=one([x for x in full if x['stage']==stage and int(x['iteration'])==i],'owner_compare')
   require(num(f,'owner','s','d','bytes','checked_words','mismatches','valid')==(owner,source,target,4,1,0,1) and c['line']<f['line']<e['line'],'owner_correctness_before_transfer')
  f=one([x for x in full if x['stage']=='peer_payload' and int(x['iteration'])==i],'p2p_compare')
  mismatch=int(f['mismatches']);require(mismatch in (0,1),'word_mismatch_range')
  require(num(f,'owner','s','d','bytes','checked_words','valid')==(target,source,target,4,1,int(mismatch==0)),'p2p_full_compare')
  require(num(d,'s','d','bytes','checked_words','mismatches','valid','physical_ioctl_completed','direct_route_proven')==(source,target,4,1,mismatch,int(mismatch==0),int(engine=='PHYSICAL_CE'),0) and d['engine']==engine,'p2p_result')
  require(e['line']<f['line']<d['line'],'p2p_compare_order');failures+=bool(mismatch)
  details={'id':i,'engine':engine,'source':source,'destination':target,'bytes':4,'data_valid':mismatch==0}
  if engine=='PHYSICAL_CE':
   q=one([x for x in ioctls if e['line']<x['line']<f['line']],'ioctl_between_owner_and_compare')
   require(num(q,'bytes','rv','errno','inputs_unchanged')==(4,0,0,1) and hx(q,'rmStatus')==0 and hx(q,'flags')==0x77,'ioctl_success')
   require(q['src']==c['src'] and q['dst']==c['dst'] and q['request'] not in request_ids,'ioctl_operands_request');request_ids.add(q['request'])
   cls=hx(q,'ce_class');require(cls in (0xc6b5,0xc7b5) and hx(q,'launch')==(0x4003186 if cls==0xc7b5 else 0x3186),'exact_physical_methods')
   require(hx(q,'source_mode')==0 and hx(q,'destination_mode')==2 and hx(q,'source_offset')==hx(q,'destination_offset')==0,'physical_apertures_offsets')
   require(hx(q,'source_handle')>0 and hx(q,'destination_handle')>0 and hx(q,'source_pa')%4==hx(q,'destination_pa')%4==0,'physical_handles_alignment')
   b=one([x for x in bar if q['line']<x['line']<f['line']],'bar_check_order')
   require(int(b['owner'])==target and b['valid']=='1' and hx(b,'flags')&0x200 and hx(b,'start')<=hx(q,'destination_pa')<=hx(b,'end')-3 and hx(b,'destination_physical')==hx(q,'destination_pa'),'current_bar1_destination')
   details['ioctl']=q
  elif mismatch:require(hx(f,'first_expected')==hx(c,'expected'),'sm_expected_word')
  p2p.append(details)
 require(num(p2pend,'comparisons','failures','physical_completed','protocol_complete')==(4,failures,2,1) and data[-1]['line']<p2pend['line'],'p2p_end')
 init=one(rec('NVML_INIT'),'nvml_init');require(p2pend['line']<init['line'] and num(init,'rc','valid')==(0,1),'no_nvml_during_ioctls')
 nvml_ids=rec('NVML_IDENTITY');require(len(nvml_ids)==2,'nvml_identity_count')
 for x in nvml_ids:require((x['bdf'],x['uuid'].removeprefix('GPU-').replace('-',''))==IDS[int(x['device'])] and num(x,'handle_rc','uuid_rc','valid')==(0,0,1),'nvml_identity')
 pre=rec('NVML_PREFLIGHT');require(len(pre)==4 and {(x['device'],x['counter']) for x in pre}=={(str(d),c) for d in (0,1) for c in ('TX','RX')} and all(num(x,'rc','valid')==(0,1) for x in pre),'nvml_preflight')
 cc=rec('CALIBRATION_CASE');cw=rec('CALIBRATION_WINDOW');cd=rec('CALIBRATION_DATA_RESULT');se=rec('NVML_SAMPLER_END')
 for xs in (cc,cw,cd):require([int(x['id']) for x in xs]==[1,2,3,4],'calibration_order')
 require([int(x['phase']) for x in se]==[1,2,3,4],'sampler_order')
 phases=rec('CaskLogicPhysicalCE');joined=[x for x in phases if x['phase']=='calibration_sampler_joined'];require(len(joined)==4,'sampler_join_markers')
 calibration=[];calfail=qualified=0
 for i,(c,w,d,end,j) in enumerate(zip(cc,cw,cd,se,joined),1):
  owner=(i-1)//2;op='HOST_TO_DEVICE' if i%2 else 'DEVICE_TO_HOST'
  require(c['operation']==w['operation']==d['operation']==op and num(c,'owner','bytes','owner_only','p2p','batch_copies','target_ns','limit_ns')==(owner,1048576,1,0,64,1200000000,5000000000) and c['peer_access']=='NONE','calibration_contract')
  require(c['gpu_va']==buffers[(owner,'send')]['va'],'calibration_owner_only_buffer')
  require(num(w,'owner','p2p')==num(d,'owner','p2p')==(owner,0),'calibration_identity')
  begin,stop,join,duration,batches,submitted=num(w,'begin_ns','end_ns','sampler_joined_ns','duration_ns','batches','submitted_host_payload_bytes')
  require(stop-begin==duration and begin<stop<join<=int(end['joined_ns']) and 1<=batches<=4096 and submitted==batches*64*1048576,'calibration_window')
  require(begin-int(end['started_ns'])>=2000000000,'calibration_baseline_two_seconds')
  stats=audit_samples([x for x in rec('NVML_SAMPLE') if int(x['phase'])==i],[x for x in rec('NVML_STATS') if int(x['phase'])==i],end,begin,stop)
  duration_valid=1200000000<=duration<=5000000000 and w['budget_exhausted']=='0';qualified+=stats['qualified'] and duration_valid
  require(num(d,'sampling_valid','duration_valid','bytes','counter_sensitivity_proven')==(int(stats['qualified']),int(duration_valid),1048576,0),'calibration_qualification')
  ownerinit=one([x for x in full if x['stage']=='calibration_owner_initialized' and int(x['iteration'])==i],'calibration_owner_init')
  require(num(ownerinit,'owner','s','d','bytes','checked_words','mismatches','valid')==(owner,owner,owner,1048576,262144,0,1) and init['line']<ownerinit['line']<c['line'],'calibration_owner_init_order')
  host=one([x for x in full if x['stage']=='calibration_host_payload' and int(x['iteration'])==i],'host_compare');gpucheck=one([x for x in full if x['stage']=='calibration_owner_payload' and int(x['iteration'])==i],'owner_compare')
  for x,key in ((host,'host_mismatches'),(gpucheck,'owner_mismatches')):
   require(num(x,'owner','s','d','bytes','checked_words')==(owner,owner,owner,1048576,262144) and int(x['mismatches'])==int(d[key]) and int(x['valid'])==int(int(d[key])==0),'calibration_payload')
  valid=int(d['host_mismatches'])==int(d['owner_mismatches'])==0;require(int(d['valid'])==int(valid),'calibration_data_valid');calfail+=not valid
  require(c['line']<w['line']<end['line']<j['line']<host['line']<gpucheck['line']<d['line'],'calibration_compare_after_sampler_join')
  require(float(j['monotonic'])*1e9>=join-1,'sampler_joined_monotonic')
  calibration.append({'id':i,'owner':owner,'operation':op,'positive_counter_expected':'RX' if op=='HOST_TO_DEVICE' else 'TX','bytes_per_request':1048576,'submitted_host_payload_bytes':submitted,'duration_ns':duration,'duration_qualified':duration_valid,'data_valid':valid,**stats})
 done=one([x for x in phases if x['phase']=='data_done'],'data_done');free=[x for x in phases if x['phase']=='allocation_free_begin'];freed=[x for x in phases if x['phase']=='allocation_free_done'];cleanup=one([x for x in phases if x['phase']=='cleanup_done'],'cleanup_done')
 require(len(free)==len(freed)==4 and cd[-1]['line']<done['line']<min(x['line'] for x in free) and max(x['line'] for x in freed)<cleanup['line']<final['line'],'lifetime')
 rc=6 if qualified!=4 or calfail else 5 if failures else 0
 require(num(final,'protocol_complete','p2p_comparisons','p2p_failures','physical_completed','calibrations','calibration_failures','qualified_windows','direct_route_proven','rc')==(1,4,failures,2,4,calfail,qualified,0,rc),'final_counts')
 return {'status':'INDEPENDENT_PHYSICAL_PROTOCOL_AUDIT_PASS','protocol_complete':True,'p2p_solution_proven':False,'p2p_failures':failures,'physical_completed':2,'calibration_failures':calfail,'qualified_windows':qualified,'program_rc':rc,'p2p':p2p,'calibrations':calibration,'limits':['Physical addresses and method outputs must also match the independently reviewed kernel log and owned mapping chain.','Physical NONCOHERENT mode and privileged channel differ from the prior CUDA-copy path; translation is not the only isolated variable.','H2D/D2H controls are CPU/GPU calibration, not a P2P route or relay.','NVML aggregates endpoint traffic and cannot locate a TLP or demonstrate payload-specific routing.','Qualified sampling does not automatically prove counter sensitivity: inspect the positive-control delta.']}

def main():
 p=argparse.ArgumentParser();p.add_argument('log',type=Path);p.add_argument('--output',type=Path);a=p.parse_args();raw=a.log.read_bytes()
 try:result=audit(raw.decode())
 except (ValueError,KeyError,IndexError) as e:result={'status':'INDEPENDENT_PHYSICAL_PROTOCOL_AUDIT_FAIL','reason':str(e),'protocol_complete':False}
 result['result_sha256']=hashlib.sha256(raw).hexdigest();text=json.dumps(result,indent=2,ensure_ascii=False)+'\n'
 if a.output:a.output.write_text(text)
 print(text);return 0 if result['status'].endswith('_PASS') else 1
if __name__=='__main__':raise SystemExit(main())
