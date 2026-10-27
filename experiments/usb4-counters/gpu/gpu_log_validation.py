"""Qualify payload protocol, calibration, counter windows and restoration separately."""
from pathlib import Path
import hashlib,importlib.util,re
BASE_SHA='f7fc3263877afb093a7ec6fc3be2b0b244e73fdb0674606e5509f42569abd9cc'
p=Path(__file__).resolve().parent/'base_log_validation.py'
if hashlib.sha256(p.read_bytes()).hexdigest()!=BASE_SHA:raise RuntimeError('Base validator changed')
s=importlib.util.spec_from_file_location('gpu_counter_base',str(p));base=importlib.util.module_from_spec(s);s.loader.exec_module(base)
POINTS=['HOST_PCIE','HOST_LANE','DOCK_LANE','DOCK_PCIE']
def need(ok,why):
 if not ok:raise ValueError(why)
def fields(line):return dict(re.findall(r'(\w+)=(\S+)',line))
def counter_row(x):
 b,a,d=[int(x[z]) for z in ['before','after','delta']]
 db,da,dd=[int(x[z]) for z in ['dropped_before','dropped_after','dropped_delta']]
 bt,at,dt=[int(x[z]) for z in ['before_ns','after_ns','elapsed_ns']]
 need(0<=b<=a<2**64-1 and a-b==d and 0<=db<=da<2**32-1 and da-db==dd,'Counter reset/saturation/delta')
 need(0<bt<at and at-bt==dt,'Counter interval invalid')
 return b,a,db,da,bt,at
def complete(raw,ccfg,kernel):
 result=base.validate_log(raw,ccfg)
 lines=raw.splitlines()
 markers=['GPU_COUNTER_RUN_BEGIN version=1 cpu_control_before_gpu=1','USB4_COUNTER_DATA_DISKS unmounted',
  'COUNTER_MODULE_LOAD_RC=0','TB_MMIO_PROBE_BEGIN version=1 gpu_program_executed=0 mmio_writes=0 command_mask=0002',
  'TB_MMIO_COMMAND_BEGIN original=0000 requested=0002 bus_master_enable=0','TB_MMIO_COMMAND_ACTIVE observed=0002',
  'TB_MMIO_COMMAND_RESTORED observed=0000 bus_master_enable=0',
  'TB_MMIO_PROBE_END protocol_complete=1 positive_controls=2 idle_controls=2 points=4 source_reads=16448 command_restored=1',
  'COUNTER_CONTROL_RC=0','TB_GPU_DRIVER_LOAD_BEGIN','GPU_COUNTER_PROGRAM_BEGIN',
  'GPU_COUNTER_NO_COMPUTE_JOBS=1','TB_GPU_DRIVER_UNLOADED=1','COUNTER_MODULE_UNLOADED=1',
  'TB_COUNTER_RESTORED original_module=1 four_paths=1',
  'GPU_COUNTER_RUN_END original_module_restored=1 gpu_driver_unloaded=1 data_disks_unmounted=1']
 for m in markers:need(lines.count(m)==1,'Missing/duplicate lifecycle marker: '+m)
 need([lines.index(m) for m in markers]==sorted(lines.index(m) for m in markers),'Lifecycle reordered')
 need(lines.count('USB4_INSPECTION_GPU_MODULES absent')==2,'Initial/final GPU guards missing')
 need('WATCHDOG_REBOOT' not in raw+kernel and 'TB_MMIO_RESTORE_FAILED' not in raw and 'TB_MMIO_ABORT' not in raw,'Watchdog/CPU control failed')
 need('module_blacklist=nouveau ' in raw,'Kernel module policy differs')
 need(kernel.strip() and 'CASKTB_GPU_DRIVER_LOAD_BEGIN' in kernel and 'CASKTB_GPU_DRIVER_UNLOADED' in kernel,'Kernel lifecycle evidence missing')
 plans=[fields(x) for x in kernel.splitlines() if 'CASKTB_COUNTER_PLAN ' in x]
 need(len(plans)==4 and {(x.get('route'),x.get('port'),x.get('index')) for x in plans}=={('0','8','0'),('0','1','1'),('1','1','1'),('1','3','0')},'Counter plan changed')
 need(all(x.get('hop')=='8' and x.get('path_inactive')=='1' and x.get('standard_activation')=='1' for x in plans),'Live path modification')
 paths=[fields(x) for x in lines if x.startswith('TB_COUNTER_PATH ')]
 need(len(paths)==300 and [x.get('point') for x in paths]==POINTS*75 and
      [x.get('enabled') for x in paths]==['1']*296+['0']*4 and
      [x.get('index') for x in paths]==['0','1','1','0']*75 and all(x.get('valid')=='1' for x in paths),'Path validation/restoration differs')
 cpu=[fields(x) for x in lines if x.startswith('TB_MMIO_SAMPLE ')]
 need(len(cpu)==16 and [x.get('point') for x in cpu]==POINTS*4,'CPU samples incomplete')
 data=[fields(x) for x in lines if x.startswith('TB_MMIO_DATA ')]
 need(len(data)==4 and [x.get('reads') for x in data]==['0','64','16384','0'] and
      [x.get('group') for x in data]==['1','2','3','4'] and
      all(x.get('reads')==x.get('checked') and x.get('expected')=='b76000a1' and x.get('valid')=='1' for x in data),'CPU reference data incomplete')
 for k,x in enumerate(cpu):
  need(x.get('group')==str(k//4+1) and x.get('reads')==str([0,64,16384,0][k//4]),'CPU sample identity')
  counter_row(x)
 calibrated=[]
 for point in POINTS:
  rows=[x for x in cpu if x['point']==point]
  idle=max(int(rows[i]['delta'])/int(rows[i]['elapsed_ns']) for i in (0,3))
  excess=int(rows[2]['delta'])-idle*int(rows[2]['elapsed_ns'])
  if excess>8192:calibrated.append(point)
 need(set(['HOST_PCIE','HOST_LANE','DOCK_LANE'])<=set(calibrated),'Three CPU controls not distinct from measured idle')
 cases=[fields(x) for x in lines if x.startswith('CE_CASE ')]
 results=[fields(x) for x in lines if x.startswith('CE_DATA_RESULT ')]
 need(len(cases)==36 and [int(x['id']) for x in cases]==list(range(1,37)),'Cases incomplete')
 samples=[fields(x) for x in lines if x.startswith('TB_GPU_SAMPLE ')]
 need(len(samples)==288,'GPU samples incomplete/duplicate')
 previous={};drops=[]
 for k,x in enumerate(samples):
  uid=k//8+1;stage='IDLE' if k%8<4 else 'TRANSFER';point=POINTS[k%4]
  case=cases[uid-1]
  need(x.get('id')==str(uid) and x.get('stage')==stage and x.get('point')==point and
       x.get('bytes')==('0' if stage=='IDLE' else case['bytes']),'GPU sample identity')
  b,a,db,da,bt,at=counter_row(x)
  if point in previous:
   pa,pd,pt=previous[point];need(b>=pa and db>=pd and bt>=pt,'GPU counter reset between windows')
  previous[point]=(a,da,at)
  if da>db:drops.append({'id':uid,'stage':stage,'point':point,'delta':da-db})
 for uid in range(1,37):
  group=(uid-1)//3;step=(uid-1)%3;executor=1 if group<6 else 0
  engine='CE_REQUEST' if group%2==0 else 'SM';size=[4,65536,1048576][(group%6)//2]
  mode='PULL' if step==1 else 'PUSH';source=1-executor if step==1 else executor;destination=1-source
  wanted={'engine':engine,'mode':mode,'executor':str(executor),'s':str(source),'d':str(destination),'bytes':str(size)}
  for row in [cases[uid-1],results[uid-1]]:need(all(row.get(k)==v for k,v in wanted.items()),'Fixed executor/group changed')
  need(results[uid-1].get('checked_words')==str(size//4),'Partial payload comparison')
  for stage,owner in [('source_initialized',source),('destination_poisoned',destination)]:
   found=[fields(x) for x in lines if x.startswith('FULL_COMPARE stage='+stage+' ') and fields(x).get('iteration')==str(uid)]
   need(len(found)==1 and found[0].get('owner')==str(owner) and found[0].get('valid')=='1' and
        found[0].get('checked_words')==str(size//4) and found[0].get('mismatches')=='0','Owner/sentinel control failed')
  starts=[i for i,x in enumerate(lines) if x.startswith('CUPTI_CASE_BEGIN ') and fields(x).get('id')==str(uid)]
  ends=[i for i,x in enumerate(lines) if x.startswith('CUPTI_CASE_END ') and fields(x).get('id')==str(uid)]
  positions=[i for i,x in enumerate(lines) if x.startswith('TB_GPU_SAMPLE ') and fields(x).get('id')==str(uid)]
  need(len(starts)==len(ends)==1 and len(positions)==8 and starts[0]<min(positions)<=max(positions)<ends[0],'Counter window outside transfer trace bracket')
 result.update(status='complete_gpu_counter_measurement',protocol_complete=True,gpu_program_executed=True,
   cpu_calibrated_points=calibrated,cpu_calibration_limit='Empirical excess over two idle intervals; no PCIe opcode/requester trace.',
   cpu_counter_samples=cpu,gpu_counter_samples=samples,counter_drops=drops,original_thunderbolt_module_restored=True,
   gpu_driver_unloaded=True,vm_data_disks_mounted=False,P2P_solution_claimed=False,hardware_packet_trace=False)
 return result
def validate_log(raw,ccfg,kernel=''):
 try:return complete(raw,ccfg,kernel)
 except (ValueError,KeyError,TypeError) as e:
  return {'status':'incomplete_preserved','protocol_complete':False,'counter_error':str(e),'P2P_solution_claimed':False,'hardware_packet_trace':False,'logs_are_partial_evidence':True}
