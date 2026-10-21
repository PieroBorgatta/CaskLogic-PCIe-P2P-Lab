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

