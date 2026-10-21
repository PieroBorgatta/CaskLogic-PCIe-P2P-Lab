#!/usr/bin/env python3
"""Fixture sintetiche: validatore offline, nessuna API CUDA o CUPTI eseguita."""
from pathlib import Path
import copy, hashlib, json
from analyze_ce import audit
P=Path(__file__).parent
rows=[]
def emit(prefix,**kw):rows.append((prefix,{k:str(v) for k,v in kw.items()}))
def gpu(i):emit('CE_GPU',index=i,bdf=['0000:01:00.0','0000:06:00.0'][i],uuid=['00000000000000000000000000000001','00000000000000000000000000000002'][i],name='fixture',valid=1)
def va(owner,role,mode):return format(0x700000000000+(0x4000000 if mode=="PULL" else 0)+owner*0x2000000+(0x1000000 if role=='receive' else 0),'x')
def access(stage,owner,role,mode):
 for device in (0,1):
  shared=(mode=='PUSH' and role=='receive') or (mode=='PULL' and role=='send')
  flags=0 if not shared and device!=owner else 3
  emit('CE_ACCESS',stage=stage,owner=owner,mode=mode,role=role,device=device,va=va(owner,role,mode),last_va=format(int(va(owner,role,mode),16)+8388607,'x'),first=flags,last=flags,expected=flags,allocation_type=1,location_type=1,location_id=owner,valid=1)
def rec(cid,kind,corr,**kw):
 x=dict(case=cid,kind=kind,corr=corr,device=0,context=0,stream_id=0,channel=0,channel_type=0,copy_kind=0,src_kind=0,dst_kind=0,src_device=0,dst_device=0,bytes=0,start=0,end=0,cbid=0,external=0,name='none');x.update(kw);emit('CUPTI_RECORD',**x)
emit('CUPTI_READY',version=24,memcpy_record=5,ptop_record=4,kernel_record=9)
for i in (0,1):gpu(i)
for mode in ('PUSH','PULL'):
 for i in (0,1):
  for role in ('send','receive'):
   emit('CE_ALLOCATION',nonce=f'00000000-0000-0000-0000-{(4 if mode=="PULL" else 0)+i*2+(role=="receive")+1:012d}',owner=i,mode=mode,role=role,va=va(i,role,mode),handle=(4 if mode=="PULL" else 0)+i*2+(role=='receive')+1,allocation_bytes=8388608,granularity=2097152);access('created',i,role,mode)
for idx in range(24):
 cid=idx+1;mode='PUSH' if idx<12 else 'PULL';s=(idx%12)//6;d=1-s;ex=s if mode=='PUSH' else d;ce=(idx%2==1) if mode=='PUSH' else (idx%2==0);engine='CE_REQUEST' if ce else 'SM';size=[4,4,65536,65536,1048576,1048576][idx%6];corr=1000+cid
 if idx in (0,12):emit('CE_MODE_BEGIN',mode=mode,first_case=cid)
 gpu(s);gpu(d);access('before_case',s,'send',mode);access('before_case',d,'receive',mode)
 emit('CE_CASE',id=cid,engine=engine,mode=mode,executor=ex,s=s,d=d,bytes=size,seed='aabbccdd',src=va(s,'send',mode),dst=va(d,'receive',mode),allocations_unchanged=1)
 for stage,owner in [('source_initialized',s),('destination_poisoned',d)]:emit('FULL_COMPARE',stage=stage,owner=owner,s=s,d=d,bytes=size,iteration=cid,checked_words=size//4,mismatches=0,valid=1)
 emit('CE_EXECUTOR',id=cid,device=ex,current=f'0x{10+ex:x}',stream_context=f'0x{10+ex:x}',stream=f'0x{30+ex:x}',valid=1)
 emit('CUPTI_CASE_BEGIN',id=cid,engine=engine,mode=mode,executor=ex,s=s,d=d,device=10+ex,source_device=10+s,target_device=10+d,context=20+ex,stream_id=30+ex,stream=f'0x{30+ex:x}',src=va(s,'send',mode),dst=va(d,'receive',mode),bytes=size,timestamp=cid*100)
 emit('CUPTI_CASE_END',id=cid,timestamp=cid*100+90)
 emit('FULL_COMPARE',stage='peer_payload',owner=d,s=s,d=d,bytes=size,iteration=cid,checked_words=size//4,mismatches=0,valid=1)
 emit('CE_DATA_RESULT',id=cid,engine=engine,mode=mode,executor=ex,s=s,d=d,bytes=size,checked_words=size//4,mismatches=0,valid=1,direct_route_proven=0)
 access('after_case',s,'send',mode);access('after_case',d,'receive',mode)
 if idx in (11,23):emit('CE_MODE_END',mode=mode,last_case=cid)
emit('CaskLogicCE',phase='data_done',monotonic='9.0',s=-1,d=-1)
for idx in range(24):
 cid=idx+1;mode='PUSH' if idx<12 else 'PULL';s=(idx%12)//6;d=1-s;ex=s if mode=='PUSH' else d;ce=(idx%2==1) if mode=='PUSH' else (idx%2==0);size=[4,4,65536,65536,1048576,1048576][idx%6];corr=1000+cid
 rec(cid,39,corr,external=cid)
 if ce:
  for site in (0,1):emit('CUPTI_CALLBACK',case=cid,corr=corr,cbid=281,site=site,context=20+ex,is_d2d=1,src=va(s,'send',mode),dst=va(d,'receive',mode),bytes=size,stream=f'0x{30+ex:x}',result=0 if site else -1)
  rec(cid,4,corr,cbid=281,start=cid*100+1,end=cid*100+10)
  rec(cid,22,corr,device=10+ex,context=20+ex,stream_id=30+ex,channel=42,channel_type=2,copy_kind=10,src_kind=3,dst_kind=3,src_device=10+s,dst_device=10+d,bytes=size,start=cid*100+20,end=cid*100+80)
 else:rec(cid,10,corr,device=10+ex,context=20+ex,stream_id=30+ex,channel=43,channel_type=1,start=cid*100+20,end=cid*100+80,name='peer_push_kernel')
for idx in range(24):
 cid=idx+1;mode='PUSH' if idx<12 else 'PULL';s=(idx%12)//6;ex=s if mode=='PUSH' else 1-s;ce=(idx%2==1) if mode=='PUSH' else (idx%2==0);size=[4,4,65536,65536,1048576,1048576][idx%6]
 emit('CUPTI_CASE_RESULT',id=cid,engine='CE_REQUEST' if ce else 'SM',mode=mode,executor=ex,copies=int(ce),kernels=int(not ce),copy_bytes=size if ce else 0,host_copies=0,unattributed=0,d2d_entries=int(ce),d2d_exits=int(ce),d2d_driver=int(ce),metadata_valid=1,coverage_complete=1,ce_observed=int(ce),direct_route_proven=0)
emit('CUPTI_SUMMARY',trace_complete=1,cases=24,ce_cases=12,ce_observed=12,sm_observed=12,dropped=0,errors=0,direct_route_proven=0)
for j in range(8):
 emit('CaskLogicCE',phase='allocation_free_begin',monotonic='10.0',s=j//2,d=-1);emit('CaskLogicCE',phase='allocation_free_done',monotonic='10.1',s=j//2,d=-1)
emit('CaskLogicCE',phase='cleanup_done',monotonic='11.0',s=-1,d=-1)
emit('CE_PROGRAM_END',protocol_complete=1,comparisons=24,failures=0,trace_complete=1,ce_cases=12,ce_observed=12,sm_observed=12,dropped=0,trace_errors=0,direct_route_proven=0,rc=0)
def text(rs):return '\n'.join(p+' '+' '.join(f'{k}={v}' for k,v in d.items()) for p,d in rs)+'\n'
def mutate(prefix,key,value,predicate=lambda d:True):
 rs=copy.deepcopy(rows)
 for p,d in rs:
  if p==prefix and predicate(d):d[key]=str(value);return rs
 raise AssertionError(prefix)
cases=[('complete_ce_and_sm',rows,True)]
for name,prefix,key,value,predicate in [
 ('source_shared_with_peer','CE_ACCESS','last',3,lambda d:d['role']=='send' and d['first']=='0'),
 ('pull_destination_exposed','CE_ACCESS','last',3,lambda d:d['mode']=='PULL' and d['role']=='receive' and d['first']=='0'),
 ('pull_source_wrongly_private','CE_ACCESS','last',0,lambda d:d['mode']=='PULL' and d['role']=='send' and d['owner']!=d['device']),
 ('pull_wrong_executor','CE_EXECUTOR','device',0,lambda d:d['id']=='13'),
 ('pull_source_confused_executor','CUPTI_RECORD','src_device',11,lambda d:d['kind']=='22' and d['case']=='13'),
 ('pull_activity_executes_source','CUPTI_RECORD','device',10,lambda d:d['kind']=='22' and d['case']=='13'),
 ('wrong_handle_owner','CE_ACCESS','location_id',1,lambda d:d['owner']=='0'),
 ('wrong_gpu_uuid','CE_GPU','uuid','ffffffffffffffffffffffffffffffff',lambda d:True),
 ('allocation_changed','CE_CASE','src','deadbeef',lambda d:d['id']=='2'),
 ('owner_mismatch','FULL_COMPARE','mismatches',1,lambda d:d['stage']=='source_initialized'),
 ('wrong_executor_context','CE_EXECUTOR','stream_context','0xdead',lambda d:True),
 ('callback_wrong_va','CUPTI_CALLBACK','dst','deadbeef',lambda d:True),
 ('callback_wrong_bytes','CUPTI_CALLBACK','bytes',8,lambda d:True),
 ('callback_wrong_stream','CUPTI_CALLBACK','stream','0xbad',lambda d:True),
 ('callback_wrong_result','CUPTI_CALLBACK','result',1,lambda d:d['site']=='1'),
 ('callback_ambiguous_case','CUPTI_CALLBACK','case',4,lambda d:d['case']=='2'),
 ('activity_wrong_executor','CUPTI_RECORD','device',11,lambda d:d['kind']=='22' and d['case']=='2'),
 ('activity_wrong_owner','CUPTI_RECORD','dst_device',10,lambda d:d['kind']=='22' and d['case']=='2'),
 ('activity_wrong_context','CUPTI_RECORD','context',99,lambda d:d['kind']=='22'),
 ('activity_wrong_stream','CUPTI_RECORD','stream_id',99,lambda d:d['kind']=='22'),
 ('activity_not_ce','CUPTI_RECORD','channel_type',1,lambda d:d['kind']=='22'),
 ('activity_wrong_bytes','CUPTI_RECORD','bytes',8,lambda d:d['kind']=='22' and d['bytes']=='4'),
 ('activity_host_endpoint','CUPTI_RECORD','dst_kind',1,lambda d:d['kind']=='22'),
 ('activity_zero_timestamp','CUPTI_RECORD','start',0,lambda d:d['kind']=='22'),
 ('activity_outside_case','CUPTI_RECORD','end',999999,lambda d:d['kind']=='22'),
 ('sm_wrong_kernel','CUPTI_RECORD','name','other_kernel',lambda d:d['kind']=='10'),
 ('trace_records_lost','CUPTI_SUMMARY','dropped',1,lambda d:True),
 ('premature_direct_claim','CE_PROGRAM_END','direct_route_proven',1,lambda d:True),
 ('inconsistent_failure_count','CE_PROGRAM_END','failures',1,lambda d:True),
 ('wrong_final_rc','CE_PROGRAM_END','rc',5,lambda d:True),
]:cases.append((name,mutate(prefix,key,value,predicate),False))
for prefix,name,pred in [('CUPTI_CALLBACK','missing_callback',lambda d:d['site']=='1'),('CUPTI_RECORD','missing_activity',lambda d:d['kind']=='22'),('CUPTI_RECORD','missing_driver_activity',lambda d:d['kind']=='4'),('CE_PROGRAM_END','missing_final',lambda d:True),('CaskLogicCE','missing_lifetime_marker',lambda d:d['phase']=='data_done')]:
 rs=copy.deepcopy(rows);index=next(i for i,(p,d) in enumerate(rs) if p==prefix and pred(d));rs.pop(index);cases.append((name,rs,False))
for name,rs,valid in cases:
 try:result=audit(text(rs));actual=True
 except (ValueError,KeyError,IndexError):actual=False
 assert actual==valid,(name,actual,valid)
out={'status':'PASS','cases':len(cases),'case_names':[x[0] for x in cases],'analyzer_sha256':hashlib.sha256((P/'analyze_ce.py').read_bytes()).hexdigest(),'runtime_source_unchanged':True,'hardware_or_remote_operations':False}
(P/'offline-analysis-fixtures.json').write_text(json.dumps(out,indent=2)+'\n');(P/'fixture-complete.log').write_text(text(rows));print(json.dumps(out,indent=2))
