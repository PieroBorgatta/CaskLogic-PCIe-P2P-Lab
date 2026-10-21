#!/usr/bin/env python3
"""Audit offline dei log CE; non esegue CUDA, CUPTI, SSH o accessi hardware."""
import argparse, hashlib, json, re
from pathlib import Path

def fields(line):
    marks=list(re.finditer(r'(?:^|\s)([A-Za-z0-9_]+)=',line))
    return {m[1]:line[m.end():marks[i+1].start() if i+1<len(marks) else len(line)].strip() for i,m in enumerate(marks)}
def records(lines,prefix):return [dict(fields(l),line=i+1) for i,l in enumerate(lines) if l.startswith(prefix+' ')]
def ensure(ok,reason):
    if not ok:raise ValueError(reason)
def one(xs,reason):ensure(len(xs)==1,reason);return xs[0]
def numeric(x,*keys):return tuple(int(x[k]) for k in keys)
def audit(text):
    lines=text.splitlines();case=records(lines,'CE_CASE');data=records(lines,'CE_DATA_RESULT');begin=records(lines,'CUPTI_CASE_BEGIN');end=records(lines,'CUPTI_CASE_END');classified=records(lines,'CUPTI_CASE_RESULT')
    final=one(records(lines,'CE_PROGRAM_END'),'final_marker_cardinality');summary=one(records(lines,'CUPTI_SUMMARY'),'trace_summary_cardinality')
    ready=one(records(lines,'CUPTI_READY'),'trace_ready_cardinality');ensure(numeric(ready,'version','memcpy_record','ptop_record','kernel_record')==(24,5,4,9),'cupti_abi')
    ensure(all(len(xs)==12 for xs in [case,data,begin,end,classified]),'twelve_case_records')
    for xs in [case,data,begin,end,classified]:ensure([int(x['id']) for x in xs]==list(range(1,13)),'ordered_unique_cases')
    ensure(not any(l.startswith(('CE_ABORT ','CUDA_ERROR ','DRIVER_ERROR ','CUPTI_ERROR ','FATAL ')) for l in lines),'runtime_error')
    alloc=records(lines,'CE_ALLOCATION');ensure(len(alloc)==4,'four_allocations')
    by_buffer={}
    for a in alloc:
        key=(int(a['owner']),a['role']);ensure(key not in by_buffer and key[0] in (0,1) and key[1] in ('send','receive'),'allocation_identity');by_buffer[key]=a
        ensure(int(a['allocation_bytes'])==8*1024*1024 and int(a['granularity'])>0 and int(a['allocation_bytes'])%int(a['granularity'])==0,'allocation_geometry')
        ensure(re.fullmatch('[0-9a-f-]{36}',a['nonce']) is not None,'allocation_nonce')
    ensure(len({a['va'] for a in alloc})==4 and len({a['nonce'] for a in alloc})==4,'unique_allocations')
    ensure(max(x['line'] for x in alloc)<case[0]['line'],'all_mappings_before_cases')
    access=records(lines,'CE_ACCESS');ensure(len(access)==104,'vmm_access_count')
    for x in access:
        owner=int(x['owner']);device=int(x['device']);a=by_buffer[(owner,x['role'])]
        expected=0 if x['role']=='send' and owner!=device else 3
        ensure(numeric(x,'first','last','expected')==(expected,expected,expected) and x['valid']=='1','vmm_rights')
        ensure(x['va']==a['va'] and int(x['last_va'],16)==int(a['va'],16)+int(a['allocation_bytes'])-1,'vmm_range')
        ensure(numeric(x,'allocation_type','location_type','location_id')==(1,1,owner),'vmm_device_allocation')
    gpu=records(lines,'CE_GPU');expected_ids={0:('0000:01:00.0','00000000000000000000000000000001'),1:('0000:06:00.0','00000000000000000000000000000002')}
    ensure(len(gpu)==26,'identity_checks_count')
    for g in gpu:ensure((g['bdf'],g['uuid'])==expected_ids[int(g['index'])] and g['valid']=='1','gpu_identity')
    ops=records(lines,'CUPTI_RECORD');callbacks=records(lines,'CUPTI_CALLBACK');correlation={}
    def associate(corr,cid):
        ensure(corr not in correlation or correlation[corr]==cid,'ambiguous_correlation');correlation[corr]=cid
    for x in ops:
        if int(x['kind'])==39:associate(int(x['corr']),int(x['external']))
    for x in callbacks:associate(int(x['corr']),int(x['case']))
    for x in ops:ensure(int(x['case'])==correlation.get(int(x['corr']),0),'record_case_not_derived_from_correlation')
    for i,b in enumerate(begin):
        c=case[i];ensure(numeric(b,'s','d','bytes')==numeric(c,'s','d','bytes') and b['engine']==c['engine'],'trace_case_identity')
        ensure(b['src']==c['src'] and b['dst']==c['dst'],'trace_case_addresses')
    device_ids={s:int(one([b for b in begin if int(b['s'])==s][:1],'source_cupti_id')['device']) for s in (0,1)}
    ensure(device_ids[0]!=device_ids[1],'distinct_cupti_devices')
    full=records(lines,'FULL_COMPARE');ensure(len(full)==36,'full_comparison_count')
    failures=0;ce_observed=0;sm_observed=0;all_coverage=True;details=[]
    for i,(c,d,b,e,claim) in enumerate(zip(case,data,begin,end,classified)):
        cid=i+1;source=0 if i<6 else 1;target=1-source;ce=i%2==1;engine='CE_REQUEST' if ce else 'SM';size=[4,4,65536,65536,1048576,1048576][i%6]
        ensure(numeric(c,'s','d','bytes')==(source,target,size) and c['engine']==engine and c['allocations_unchanged']=='1','case_contract')
        ensure(c['src']==by_buffer[(source,'send')]['va'] and c['dst']==by_buffer[(target,'receive')]['va'],'same_allocations_sm_ce')
        ensure(numeric(d,'s','d','bytes','checked_words')==(source,target,size,size//4) and d['engine']==engine and d['direct_route_proven']=='0','data_contract')
        ensure(int(d['valid'])==int(int(d['mismatches'])==0),'data_result_consistency');failures+=int(d['valid'])==0
        ensure(c['line']<b['line']<e['line']<d['line'],'case_sequence')
        executor=one([x for x in records(lines,'CE_EXECUTOR') if int(x['id'])==cid],'executor_record')
        ensure(executor['current']==executor['stream_context'] and executor['stream']==b['stream'] and int(executor['device'])==source and executor['valid']=='1','executor_context')
        ensure(c['line']<executor['line']<b['line'],'executor_query_order')
        ensure(numeric(b,'device','target_device')==(device_ids[source],device_ids[target]),'cupti_device_assignment')
        for role in ('source_initialized','destination_poisoned'):
            owner=source if role=='source_initialized' else target
            q=one([x for x in full if x['stage']==role and int(x['iteration'])==cid],'owner_full_compare')
            ensure(numeric(q,'owner','s','d','bytes','checked_words','mismatches','valid')==(owner,source,target,size,size//4,0,1),'owner_initialization')
            ensure(c['line']<q['line']<b['line'],'owner_happens_before_transfer')
        q=one([x for x in full if x['stage']=='peer_payload' and int(x['iteration'])==cid],'payload_full_compare')
        ensure(numeric(q,'mismatches','valid')==numeric(d,'mismatches','valid') and e['line']<q['line']<d['line'],'payload_report')
        before=[x for x in access if x['stage']=='before_case' and (data[i-1]['line'] if i else alloc[-1]['line'])<x['line']<c['line']]
        after=[x for x in access if x['stage']=='after_case' and d['line']<x['line']<(case[i+1]['line'] if i<11 else final['line'])]
        ensure(len(before)==len(after)==4,'rights_each_case')
        current=[x for x in callbacks if int(x['case'])==cid and x['is_d2d']=='1'];entries=[x for x in current if x['site']=='0'];exits=[x for x in current if x['site']=='1'];corr=int(entries[-1]['corr']) if entries else 0
        metadata=True
        for x in current:
            metadata &= x['src']==c['src'] and x['dst']==c['dst'] and int(x['bytes'])==size and x['stream']==b['stream'] and x['context']==b['context'] and int(x['corr'])==corr and (x['site']!='1' or x['result']=='0')
        driver=sum(int(x['kind'])==4 and int(x['corr'])==corr and int(x['cbid']) in (281,423) for x in ops)
        copies=kernels=host=unattributed=total=0;engines=True
        for x in ops:
            kind=int(x['kind']);mem=kind in (1,22);kernel=kind==10
            if not mem and not kernel:continue
            actual_case=correlation.get(int(x['corr']),0)
            if actual_case!=cid:
                if actual_case==0 and int(b['timestamp'])<=int(x['start'])<=int(e['timestamp']):unattributed+=1
                continue
            metadata &= numeric(x,'device','context','stream_id')==numeric(b,'device','context','stream_id') and 0<int(x['start'])<=int(x['end']) and int(b['timestamp'])<=int(x['start']) and int(x['end'])<=int(e['timestamp'])
            if mem:
                copies+=1;total+=int(x['bytes']);host+=numeric(x,'src_kind','dst_kind')!=(3,3);engines &= int(x['channel_type'])==2
                metadata &= int(x['copy_kind']) in (8,10) and (not ce or int(x['corr'])==corr)
                if kind==22:metadata &= numeric(x,'src_device','dst_device')==(device_ids[source],device_ids[target])
            else:kernels+=1;metadata &= 'peer_push_kernel' in x['name']
        coverage=bool(metadata and not unattributed and ((copies+kernels>0 and len(entries)==len(exits)==driver==1) if ce else (kernels==1 and copies==0)))
        observed=bool(ce and coverage and copies>0 and kernels==0 and engines and not host and total==size)
        all_coverage &= coverage;ce_observed+=observed;sm_observed+=not ce and coverage
        ensure(numeric(claim,'copies','kernels','copy_bytes','host_copies','unattributed','d2d_entries','d2d_exits','d2d_driver','metadata_valid','coverage_complete','ce_observed')==(copies,kernels,total,host,unattributed,len(entries),len(exits),driver,int(metadata),int(coverage),int(observed)),'classifier_claim_matches_independent_reconstruction')
        ensure(claim['direct_route_proven']=='0','no_automatic_direct_claim')
        details.append({'id':cid,'engine':engine,'source':source,'destination':target,'bytes':size,'data_valid':bool(int(d['valid'])),'coverage':coverage,'ce_observed':observed,'host_copies':host,'copies':copies,'kernels':kernels})
    phases=records(lines,'CaskLogicCE');done=one([x for x in phases if x['phase']=='data_done'],'data_done_marker')
    frees=[x for x in phases if x['phase']=='allocation_free_begin'];finished=[x for x in phases if x['phase']=='allocation_free_done']
    cleanup=one([x for x in phases if x['phase']=='cleanup_done'],'cleanup_done_marker')
    ensure(len(frees)==len(finished)==4 and data[-1]['line']<done['line']<min(x['line'] for x in frees) and max(x['line'] for x in finished)<cleanup['line']<final['line'],'allocations_live_until_all_comparisons')
    complete=all_coverage and int(summary['dropped'])==0 and int(summary['errors'])==0
    ensure(numeric(summary,'cases','ce_cases','ce_observed','sm_observed','trace_complete')==(12,6,ce_observed,sm_observed,int(complete)),'summary_counts')
    ensure(numeric(final,'protocol_complete','comparisons','failures','trace_complete','ce_cases','ce_observed','sm_observed','dropped','trace_errors')==(1,12,failures,int(complete),6,ce_observed,sm_observed,int(summary['dropped']),int(summary['errors'])),'final_counts')
    expected_rc=6 if not complete or ce_observed!=6 or sm_observed!=6 else (5 if failures else 0)
    ensure(int(final['rc'])==expected_rc and final['direct_route_proven']==summary['direct_route_proven']=='0','final_rc_and_route_limit')
    return {'status':'INDEPENDENT_LOG_AUDIT_PASS','protocol_complete':True,'trace_complete':complete,'data_failures':failures,'comparisons':12,'ce_observed':ce_observed,'sm_observed':sm_observed,'direct_route_proven':False,'raw_program_rc':expected_rc,'cases':details,'allocations':alloc,'limitations':['CUPTI does not expose final hardware memcpy descriptors or all possible internal staging. An observed CE PASS is not itself proof of direct no-host-payload P2P.','The external BAR1 mapping/PTE chains require a separate audit of kernel.log; this log analyzer does not certify them.']}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('log',type=Path);ap.add_argument('--output',type=Path);args=ap.parse_args()
    raw=args.log.read_bytes()
    try:result=audit(raw.decode());result['result_log_sha256']=hashlib.sha256(raw).hexdigest()
    except (ValueError,KeyError,IndexError) as e:result={'status':'INDEPENDENT_LOG_AUDIT_FAIL','reason':str(e),'result_log_sha256':hashlib.sha256(raw).hexdigest()}
    text=json.dumps(result,indent=2,ensure_ascii=False)+'\n'
    if args.output:args.output.write_text(text)
    print(text);return 0 if result['status'].endswith('_PASS') else 1
if __name__=='__main__':raise SystemExit(main())
