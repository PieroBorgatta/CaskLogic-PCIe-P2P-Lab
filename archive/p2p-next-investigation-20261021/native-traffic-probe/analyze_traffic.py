#!/usr/bin/env python3
"""Analisi esclusivamente offline; contatori aggregati, nessuna cattura TLP."""
import argparse,hashlib,json,re
from pathlib import Path

def fields(line):
    marks=list(re.finditer(r'(?:^|\s)([A-Za-z0-9_]+)=',line))
    return {m[1]:line[m.end():marks[i+1].start() if i+1<len(marks) else len(line)].strip() for i,m in enumerate(marks)}
def records(lines,prefix):return [dict(fields(x),line=i+1) for i,x in enumerate(lines) if x.startswith(prefix+' ')]
def require(ok,message):
    if not ok:raise ValueError(message)
def one(xs,message):require(len(xs)==1,message);return xs[0]
def num(x,*names):return tuple(int(x[k]) for k in names)
def means(values):
    return {'count':len(values),'mean_kBps':sum(values)/len(values) if values else None,'min_kBps':min(values) if values else None,'max_kBps':max(values) if values else None}

def audit_samples(samples,stats,end,begin_ns,end_ns):
    require(num(end,'samples')==(len(samples),),'sampler_count')
    require(int(end['started_ns'])<=begin_ns<=end_ns<int(end['joined_ns']),'sampler_time_order')
    bins={(stage,d,c):[] for stage in ('BASELINE_QUIET','ACTIVE_INTERIOR','TAIL') for d in (0,1) for c in ('TX','RX')}
    errors={k:0 for k in bins};selected=quiet_count=0;all_valid=True;last_begin=0
    for x in samples:
        stage=x['stage'];d=int(x['device']);counter=x['counter'];a,b=num(x,'begin_ns','end_ns');rc=int(x['rc']);value=int(x['value_kBps'])
        require(stage in ('BASELINE','ACTIVE','TAIL') and d in (0,1) and counter in ('TX','RX'),'sample_identity')
        require(a>=last_begin and a<=b<=int(end['joined_ns']),'sample_time_order');last_begin=a
        valid=rc==0;require(int(x['valid'])==int(valid),'sample_valid_rc')
        if not valid:require(value==4294967295,'invalid_counter_not_sentinel')
        require(0<=value<=4294967295,'counter_u32');all_valid &= valid
        interior=stage=='ACTIVE' and a>=begin_ns+40000000 and b<=end_ns
        quiet=stage=='BASELINE' and a>=int(end['started_ns'])+40000000 and b<=begin_ns
        require(num(x,'interior','baseline_quiet')==(int(interior),int(quiet)),'sample_window_classification')
        selected+=interior;quiet_count+=quiet
        bucket='ACTIVE_INTERIOR' if interior else 'BASELINE_QUIET' if quiet else 'TAIL' if stage=='TAIL' else None
        if bucket:
            if valid:bins[(bucket,d,counter)].append(value)
            else:errors[(bucket,d,counter)]+=1
    require(num(end,'interior_samples','baseline_quiet_samples')==(selected,quiet_count),'selected_counts')
    require(len(stats)==12,'stats_count');seen=set();reported={}
    for x in stats:
        key=(x['stage'],int(x['device']),x['counter']);require(key in bins and key not in seen,'stats_identity');seen.add(key)
        values=bins[key];count=len(values);result=means(values);reported[key]=result
        require(num(x,'valid_count','invalid_count','available')==(count,errors[key],int(bool(count))),'stats_counts')
        require(num(x,'min_kBps','max_kBps')==((min(values),max(values)) if count else (4294967295,4294967295)),'stats_minmax')
        require(abs(float(x['mean_kBps'])-(result['mean_kBps'] if count else -1))<=0.000501,'stats_mean')
    qualified=all_valid and end['overflow']=='0' and end['exception']=='0' and all(len(v)>=5 and not errors[k] for k,v in bins.items() if k[0]!='TAIL')
    require(int(end['valid'])==int(qualified),'sampler_qualification')
    require(end['aggregation']=='all_pcie_traffic' and end['payload_specific']=='0','scope_not_payload_specific')
    result={}
    for d in (0,1):
        result[str(d)]={}
        for c in ('TX','RX'):
            quiet=reported[('BASELINE_QUIET',d,c)];active=reported[('ACTIVE_INTERIOR',d,c)]
            result[str(d)][c]={'baseline_quiet':quiet,'active_interior':active,'tail':reported[('TAIL',d,c)],'active_minus_baseline_mean_kBps':active['mean_kBps']-quiet['mean_kBps'] if active['count'] and quiet['count'] else None}
    return {'qualified':bool(qualified),'sample_count':len(samples),'active_sample_count':selected,'baseline_quiet_sample_count':quiet_count,'devices':result}

def audit(text):
    lines=text.splitlines();cases=records(lines,'TRAFFIC_CASE');windows=records(lines,'TRAFFIC_WINDOW');data=records(lines,'TRAFFIC_DATA_RESULT');sampler=records(lines,'NVML_SAMPLER_END')
    final=one(records(lines,'TRAFFIC_PROGRAM_END'),'final_count')
    for xs in (cases,windows,data):require([int(x['id']) for x in xs]==[1,2,3,4],'ordered_four_phases')
    require([int(x['phase']) for x in sampler]==[1,2,3,4],'ordered_samplers')
    require(not any(l.startswith(('TRAFFIC_ABORT ','CUDA_ERROR ','DRIVER_ERROR ','FATAL ')) for l in lines),'runtime_abort')
    gpu=records(lines,'TRAFFIC_GPU');require(len(gpu)==10,'gpu_check_count')
    expected_ids={0:('0000:01:00.0','00000000000000000000000000000001'),1:('0000:06:00.0','00000000000000000000000000000002')}
    for g in gpu:require((g['bdf'],g['uuid'])==expected_ids[int(g['index'])] and g['valid']=='1','cuda_identity')
    ids=records(lines,'NVML_IDENTITY');require(len(ids)==2,'nvml_identity_count')
    for x in ids:
        d=int(x['device']);u=x['uuid'];require(u.startswith('GPU-') and (x['bdf'],u[4:].replace('-',''))==expected_ids[d] and num(x,'handle_rc','uuid_rc','valid')==(0,0,1),'nvml_identity')
    pre=records(lines,'NVML_PREFLIGHT');require(len(pre)==4 and {(x['device'],x['counter']) for x in pre}=={(str(d),c) for d in (0,1) for c in ('TX','RX')},'nvml_preflight_count')
    require(all(num(x,'rc','valid')==(0,1) for x in pre),'nvml_preflight_available')
    alloc=records(lines,'TRAFFIC_ALLOCATION');require(len(alloc)==4 and len({x['va'] for x in alloc})==4 and len({x['nonce'] for x in alloc})==4,'allocations_unique')
    buffers={(int(x['owner']),x['role']):x for x in alloc};require(set(buffers)=={(d,r) for d in (0,1) for r in ('send','receive')},'allocation_identity')
    for x in alloc:require(int(x['allocation_bytes'])==8388608 and int(x['granularity'])>0 and 8388608%int(x['granularity'])==0,'allocation_geometry')
    require(max(x['line'] for x in alloc)<cases[0]['line'],'allocation_before_phases')
    access=records(lines,'TRAFFIC_ACCESS');require(len(access)==40,'rights_count')
    for x in access:
        owner=int(x['owner']);device=int(x['device']);a=buffers[(owner,x['role'])];expected=0 if x['role']=='send' and owner!=device else 3
        require(num(x,'first','last','expected','valid')==(expected,expected,expected,1),'access_expected')
        require(x['va']==a['va'] and int(x['last_va'],16)==int(a['va'],16)+8388607,'access_range')
        require(num(x,'allocation_type','location_type','location_id')==(1,1,owner),'allocation_device')
    full=records(lines,'FULL_COMPARE');require(len(full)==12,'full_compare_count')
    phases=records(lines,'CaskLogicTraffic');joined=[x for x in phases if x['phase']=='sampler_joined'];require(len(joined)==4,'sampler_join_markers')
    failures=qualified=0;details=[]
    for i,(c,w,d,e,j) in enumerate(zip(cases,windows,data,sampler,joined),1):
        source=(i-1)//2;destination=1-source;engine='SM' if i%2 else 'CUDA_COPY_REQUEST'
        require(num(c,'s','d','executor','bytes','batch_copies','max_batches','target_ns','limit_ns')==(source,destination,source,1048576,64,4096,1200000000,5000000000),'case_contract')
        require(c['engine']==engine and c['allocations_unchanged']=='1' and c['ce_observed']=='0','case_engine_contract')
        require(c['src']==buffers[(source,'send')]['va'] and c['dst']==buffers[(destination,'receive')]['va'],'same_allocation_operands')
        exe=one([x for x in records(lines,'TRAFFIC_EXECUTOR') if int(x['id'])==i],'executor_count')
        require(int(exe['device'])==source and exe['valid']=='1' and exe['current']==exe['stream_context'],'executor_identity')
        require(w['engine']==d['engine']==engine and num(w,'s','d')==num(d,'s','d')==(source,destination),'phase_identity')
        begin,end,join,duration,batches,submitted=num(w,'begin_ns','end_ns','sampler_joined_ns','duration_ns','batches','submitted_payload_bytes')
        require(end-begin==duration and begin<end<join<=int(e['joined_ns']),'window_times')
        require(1<=batches<=4096 and submitted==batches*64*1048576,'submitted_bytes_arithmetic')
        require(w['no_host_payload_ops_during_window']=='1','host_ops_source_contract')
        s=audit_samples([x for x in records(lines,'NVML_SAMPLE') if int(x['phase'])==i],[x for x in records(lines,'NVML_STATS') if int(x['phase'])==i],e,begin,end)
        duration_valid=1200000000<=duration<=5000000000 and w['budget_exhausted']=='0'
        require(num(d,'sampling_valid','duration_valid')==(int(s['qualified']),int(duration_valid)),'data_qualification')
        require(num(d,'bytes','checked_words')==(1048576,262144),'data_size')
        require(int(d['valid'])==int(int(d['mismatches'])==0) and d['direct_route_proven']==d['ce_observed']=='0','data_claim')
        qualified+=s['qualified'] and duration_valid;failures+=d['valid']=='0'
        payload=one([x for x in full if x['stage']=='peer_payload' and int(x['iteration'])==i],'payload_compare')
        require(num(payload,'mismatches','valid')==num(d,'mismatches','valid'),'payload_data_match')
        require(c['line']<exe['line']<w['line']<e['line']<j['line']<payload['line']<d['line'],'phase_event_order')
        require(float(j['monotonic'])*1e9>=join-1,'sampler_joined_clock')
        for role,owner in [('source_initialized',source),('destination_poisoned',destination)]:
            x=one([x for x in full if x['stage']==role and int(x['iteration'])==i],'owner_count')
            require(num(x,'owner','s','d','bytes','checked_words','mismatches','valid')==(owner,source,destination,1048576,262144,0,1),'owner_correctness')
            require(c['line']<x['line']<exe['line'],'owner_before_sampling')
        details.append({'id':i,'engine_requested':engine,'ce_observed':False,'source':source,'destination':destination,'begin_ns':begin,'end_ns':end,'duration_ns':duration,'batches':batches,'submitted_payload_bytes':submitted,'duration_qualified':duration_valid,'data_valid':d['valid']=='1','mismatches':int(d['mismatches']),**s})
    done=one([x for x in phases if x['phase']=='data_done'],'data_done');frees=[x for x in phases if x['phase']=='allocation_free_begin'];freed=[x for x in phases if x['phase']=='allocation_free_done']
    require(len(frees)==len(freed)==4 and data[-1]['line']<done['line']<min(x['line'] for x in frees),'all_comparisons_before_frees')
    cleanup=one([x for x in phases if x['phase']=='cleanup_done'],'cleanup_marker');require(max(x['line'] for x in freed)<cleanup['line']<final['line'],'cleanup_order')
    rc=6 if qualified!=4 else 5 if failures else 0
    require(num(final,'protocol_complete','comparisons','failures','qualified_windows','nvml_only','ce_observed','direct_route_proven','rc')==(1,4,failures,qualified,1,0,0,rc),'final_counts')
    return {'status':'INDEPENDENT_TRAFFIC_AUDIT_PASS','protocol_complete':True,'p2p_solution_proven':False,'comparisons':4,'data_failures':failures,'qualified_windows':qualified,'raw_program_rc':rc,'ce_observed':False,'direct_route_proven':False,'phases':details,'limits':['NVML measures aggregate endpoint PCIe traffic, not payload-specific TLPs or an address-specific route.','CUDA_COPY_REQUEST is not a CE observation in this probe.','submitted_payload_bytes counts software requests; it is not measured traffic or delivered data.','No H2D/D2H during the observation window is a property of the reviewed source path; this probe has no CUPTI trace of internal staging.','Baseline and active means are unweighted sample means; serial queries are timestamped, not simultaneous.']}

def main():
    p=argparse.ArgumentParser();p.add_argument('log',type=Path);p.add_argument('--output',type=Path);a=p.parse_args();raw=a.log.read_bytes()
    try:result=audit(raw.decode())
    except (ValueError,KeyError,IndexError) as e:result={'status':'INDEPENDENT_TRAFFIC_AUDIT_FAIL','reason':str(e)}
    result['result_sha256']=hashlib.sha256(raw).hexdigest();text=json.dumps(result,indent=2,ensure_ascii=False)+'\n'
    if a.output:a.output.write_text(text)
    print(text);return 0 if result['status'].endswith('_PASS') else 1
if __name__=='__main__':raise SystemExit(main())
