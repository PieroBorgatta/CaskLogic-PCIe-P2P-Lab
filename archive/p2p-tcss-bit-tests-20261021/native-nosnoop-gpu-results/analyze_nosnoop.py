#!/usr/bin/env python3
"""Rianalisi locale dei log già acquisiti; nessun accesso hardware."""
from pathlib import Path
import gzip, hashlib, json, re, statistics

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
rl = (HERE/'result.log').read_text().splitlines()
kl = (HERE/'kernel.log').read_text().splitlines()
manifest = json.loads((HERE/'build-manifest.json').read_text())
state = json.loads((HERE/'native-nosnoop-gpu-state.json').read_text())

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1<<20), b''): h.update(b)
    return h.hexdigest()

def fields(line):
    ms = list(re.finditer(r'(?:^|\s)([A-Za-z0-9_]+)=',line))
    return {m[1]:line[m.end():ms[i+1].start() if i+1<len(ms) else len(line)].strip() for i,m in enumerate(ms)}

def records(lines, prefix):
    return [dict(fields(l),line=n+1) for n,l in enumerate(lines) if l.startswith(prefix)]

def exactly(xs):
    assert len(xs)==1, (len(xs),xs)
    return xs[0]

def ktime(line): return float(re.search(r'\[\s*(\d+\.\d+)\]',line)[1])

hashes={}
for name, expected in json.loads((HERE/'collected-sha256.json').read_text()).items():
    actual=sha(HERE/name); assert actual==expected,name
    hashes[name]={'sha256':actual,'bytes':(HERE/name).stat().st_size}
for name, expected in state['files'].items():
    p=ROOT/'native-nosnoop-v2-probe-package'/name
    actual=sha(p);assert actual==expected,name
    hashes['../native-nosnoop-v2-probe-package/'+name]={'sha256':actual,'bytes':p.stat().st_size}
for name,key in [('peer_vmm_word_nosnoop.cu','native_source_sha256'),('cpubar_trace.h','cpu_header_sha256'),('pcie_diag.h','native_header_sha256'),('pci_attrs.h','attrs_header_sha256'),('trial_main.inc','trial_main_sha256'),('init-tcss-native.sh','init_sha256')]:
    p=ROOT/'native-nosnoop-probe'/name;actual=sha(p);assert actual==manifest[key],name
    hashes['../native-nosnoop-probe/'+name]={'sha256':actual,'bytes':p.stat().st_size}
assert state['files']['probe-initrd.img']==manifest['initrd_sha256']
assert state['files']['probe-kernel.efi']==manifest['kernel_sha256']

# Hash the actual selected files inside the gzip/newc initramfs, without extraction.
packed={}
with gzip.open(ROOT/'native-nosnoop-v2-probe-package/probe-initrd.img','rb') as f:
    while True:
        h=f.read(110); assert len(h)==110 and h[:6] in (b'070701',b'070702')
        v=[int(h[6+i*8:14+i*8],16) for i in range(13)]; size,namesize=v[6],v[11]
        name=f.read(namesize).rstrip(b'\0').decode();f.read((-(110+namesize))%4)
        if name=='TRAILER!!!': break
        wanted=name.endswith(('.ko','peer_word','libcuda.so.1')) or name in ('init','./init','bin/busybox','./bin/busybox','usr/bin/busybox','./usr/bin/busybox')
        d=hashlib.sha256(); remaining=size
        while remaining:
            b=f.read(min(1<<20,remaining));assert b;remaining-=len(b)
            if wanted:d.update(b)
        f.read((-size)%4)
        if wanted and size:packed[name]={'sha256':d.hexdigest(),'bytes':size}
for key in ['module_sha256','uvm_module_sha256','native_program_sha256','init_sha256','libcuda_sha256']:
    assert any(x['sha256']==manifest[key] for x in packed.values()),(key,packed)

allocs=records(rl,'CPUBAR_ALLOCATION ');assert len(allocs)==4
assert len({a['token'] for a in allocs})==4
chains=[]
for idx,a in enumerate(allocs,1):
    prefix=f"CaskLogicCPUBAR token={a['token']} alloc={idx} phase="
    begin=exactly([n for n,l in enumerate(kl) if prefix+'begin' in l])
    end=exactly([n for n,l in enumerate(kl) if prefix+'end' in l]);assert begin<end
    trace=[]
    for n in range(begin+1,end):
        if 'P2PTRC ' in kl[n]:
            kind=kl[n].split('P2PTRC ',1)[1].split()[0]
            trace.append(dict(fields(kl[n]),kind=kind,line=n+1,kernel_time=ktime(kl[n])))
    win=exactly([x for x in trace if x['kind']=='WINDOW_CREATE']);assert int(win['id'])==idx
    req=exactly([x for x in trace if x['kind']=='RM_REQUEST'])
    rm=exactly([x for x in trace if x['kind']=='RM_PTE'])
    dma=exactly([x for x in trace if x['kind']=='DMA_MAP'])
    allocation=exactly([x for x in trace if x['kind']=='UVM_ALLOCATION' and a['requester_uuid'] in x['gpu']])
    up=exactly([x for x in trace if x['kind']=='UVM_PTE' and a['requester_uuid'] in x['gpu']])
    submit=exactly([x for x in trace if x['kind']=='UVM_SUBMIT' and a['requester_uuid'] in x['gpu']])
    complete=exactly([x for x in trace if x['kind']=='UVM_MAP_COMPLETE' and x['line']>submit['line']][:1])
    assert allocation['gpu_va']==up['gpu_va']==submit['gpu_va']==complete['gpu_va']==a['gpu_va']
    assert allocation['rm_mem']==up['mem']==submit['mem']==req['mem']==win['mem']
    assert req['desc']==rm['desc']==win['desc'] and req['dynamic']==rm['dynamic']=='1'
    assert dma['src']==a['requester_bdf'] and dma['dst']==a['owner_bdf']
    assert int(win['bar1'],16)+int(win['bar1_off'],16)==int(win['window_phys'],16)
    assert win['window_phys']==win['dma']==dma['input']==dma['output']==rm['dma_base']==rm['phys_input']==rm['decoded']
    assert win['bar1']==dma['resource_start']==dma['bus_base']
    assert int(dma['resource_end'],16)+1==int(win['bar1'],16)+int(win['bar1_size'],16)
    assert win['size']==a['size']==rm['page']==up['page']=='200000'
    assert int(win['bar1_off'],16)%0x200000==0
    assert rm['raw0']==up['raw0'] and rm['raw1']==up['raw1']=='0000000000000000'
    decoded=((int(rm['raw0'],16)>>8)&((1<<46)-1))<<12
    assert decoded==int(win['dma'],16)
    assert rm['fmt']=='2' and rm['entry']=='16' and rm['aperture']=='3' and rm['valid']=='1' and rm['readonly']=='0'
    assert dma['status']==submit['status']==complete['status']=='0'
    assert begin+1<allocation['line']<dma['line']<win['line']<req['line']<rm['line']<up['line']<submit['line']<complete['line']<end+1
    destroy=exactly([n for n,l in enumerate(kl) if f'WINDOW_DESTROY_BEGIN id={idx} ' in l])
    assert destroy>end
    a=dict(a,window_id=idx,begin_kernel_line=begin+1,end_kernel_line=end+1,destroy_kernel_line=destroy+1,
           begin_kernel_time=ktime(kl[begin]),end_kernel_time=ktime(kl[end]),window=win,rm_request=req,rm_pte=rm,uvm_pte=up,dma_map=dma,
           request_submit=submit,request_complete=complete,chain_verified=True)
    chains.append(a)

# Reconstruct the experiment from individual records; do not trust summary flags alone.
attrs=records(rl,'ATTR_SNAPSHOT '); assert len(attrs)==282
original=records(rl,'ATTR_ORIGINAL '); assert [x['devctl'] for x in original]==['2930','2910']
assert all(x['mask']=='0810' and x['width']=='16' and x['cap']=='78' for x in original)
attr_writes=records(rl,'ATTR_WRITE ')
expected_writes=[('0','2930','2120'),('0','2120','2930'),('0','2930','2120'),('1','2910','2100'),('0','2120','2930'),('1','2100','2910')]
assert [(x['device'],x['before'],x['after']) for x in attr_writes]==expected_writes
for x in attr_writes:
    assert x['offset']=='80' and x['width']=='16' and x['mask']=='0810' and x['wanted']==x['after'] and x['valid']=='1'
    assert int(x['before'],16)^int(x['after'],16)==0x810
    assert x['bdf']==original[int(x['device'])]['bdf']
# Follow actual writes in order and validate every captured control value against live mode.
control={0:0x2930,1:0x2910}
for n,line in enumerate(rl,1):
    if line.startswith('ATTR_WRITE '):
        x=fields(line);i=int(x['device']);assert int(x['before'],16)==control[i];control[i]=int(x['after'],16)
    if line.startswith('ATTR_SNAPSHOT '):
        x=fields(line);i=int(x['device']);assert int(x['devctl'],16)==int(x['expected'],16)==control[i]
        assert x['bdf']==original[i]['bdf'] and x['id']==original[i]['id'] and x['cap']=='78'
        assert x['valid']=='1' and x['pending']=='0' and x['devsta']=='0000'
        assert int(x['no_snoop'])==bool(control[i]&0x800) and int(x['relaxed'])==bool(control[i]&0x10)
assert control=={0:0x2930,1:0x2910}
for a,b in zip(attrs[::2],attrs[1::2]):
    assert a['device']=='0' and b['device']=='1' and a['label']==b['label'] and a['monotonic']==b['monotonic']
restores=records(rl,'ATTR_RESTORE ');assert len(restores)==8 and all(x['valid']=='1' and x['mask']=='0810' and x['original_bits']=='0810' and x['preserved_current_other_bits']=='1' for x in restores)
final_restore=exactly(records(rl,'ATTR_FINAL_RESTORE '));assert final_restore['valid']=='1'
program_end=exactly(records(rl,'ATTR_PROGRAM_END '));assert (program_end['protocol_complete'],program_end['restored'],program_end['rc'])==('1','1','5')
assert not any(l.startswith(('ATTR_TRIAL_ABORT ','ATTR_ABORT_SYNC ','ATTR_CLEANUP_ERROR ')) for l in rl)
assert 'NATIVE_TEST_RC=5' in rl and 'SCRIPT_RC=23' in rl and 'PROBE_COMPLETED' not in rl

begins=records(rl,'ATTR_PHASE_BEGIN ');ends=records(rl,'ATTR_PHASE_RESULT ')
assert len(begins)==len(ends)==5
names=['baseline_initial','ada_off','baseline_restored','both_off','baseline_final'];modes=[0,1,0,2,0]
operations=[];phase_details=[]
for i,(begin,end) in enumerate(zip(begins,ends)):
    assert begin['index']==end['index']==str(i) and begin['name']==end['name']==names[i]
    assert begin['mode']==end['mode']==str(modes[i]) and begin['allocations_unchanged']=='1'
    assert begin['line']<end['line'] and (i==0 or ends[i-1]['line']<begin['line'])
    assert end['comparisons']=='4' and end['valid_protocol']=='1'
    ops=[dict(fields(l),operation=l.split()[0],line=n+1) for n,l in enumerate(rl) if begin['line']<n+1<end['line'] and l.startswith(('REMOTE_READ ','REMOTE_WRITE '))]
    assert [(x['operation'],x['s'],x['d'],x['valid']) for x in ops]==[('REMOTE_READ','0','1','0'),('REMOTE_WRITE','1','0','1'),('REMOTE_READ','1','0','0'),('REMOTE_WRITE','0','1','0')]
    assert all(x['phase']==str(i) and x['name']==names[i] and x['bytes']=='4' and int(x['valid'])==int(x['observed']==x['expected']) for x in ops)
    assert [x['observed'] for x in ops]==['edcba987','a5a42468','edcba987','00000000']
    assert end['failures']==str(sum(x['valid']=='0' for x in ops))=='3'
    assert (end['cpu_post_pass'],end['cpu_post_fail'],end['cpu_post_skip'])==('1','1','0')
    pattrs=[x for x in attrs if begin['line']<x['line']<end['line']]
    expected=[0x2930,0x2910] if modes[i]==0 else ([0x2120,0x2910] if modes[i]==1 else [0x2120,0x2100])
    assert all(int(x['devctl'],16)==expected[int(x['device'])] for x in pattrs)
    boundaries=['owner_init_before','owner_init_after','cpubar_check_before','cpubar_check_after','read_before','read_after','read_compare_after','owner_zero_before','owner_zero_after','write_before','write_after','postwrite_cpu_after','write_compare_after']
    for owner in range(2):
        for suffix in boundaries:
            assert len([x for x in pattrs if x['label']==f'phase{i}_owner{owner}_{suffix}'])==2
    assert len([x for x in pattrs if x['label']==f'phase{i}_complete'])==2
    assert len(pattrs)==54
    phase_details.append({'begin':begin,'result':end,'operations':ops,'attribute_snapshot_count':len(pattrs),'devctl_expected':{str(j):f'{v:04x}' for j,v in enumerate(expected)}})
    operations+=ops
assert 'TOTAL_FAILURES 15 phases=5 comparisons=20' in rl

owners=records(rl,'OWNER_CHECK ');assert len(owners)==60 and all(x['valid']=='1' and x['observed']==x['expected'] for x in owners)
cpu=records(rl,'CPUBAR_READ ');assert len(cpu)==20 and all(x['valid']=='1' and x['observed']==x['expected'] for x in cpu)
results=records(rl,'CPUBAR_RESULT ');assert len(results)==10 and all(x['status']=='PASS' and x['restored']=='1' for x in results)
matches=records(rl,'CPUBAR_MATCH ');post=records(rl,'CPUBAR_POSTWRITE ')
assert len(matches)==len(post)==10
for x in matches+post:
    c=chains[int(x['window_id'])-1];assert x['owner']==c['owner'] and x['bdf']==c['owner_bdf']
    assert int(x['gpu_va'],16)==int(c['gpu_va'],16) and x['physical']==c['window']['window_phys'] and x['mapping']=='O_RDONLY_PROT_READ'
for i in range(5):
    ps=post[i*2:i*2+2]
    assert [(x['owner'],x['writer'],x['status'],x['observed'],x['expected']) for x in ps]==[('0','1','PASS','a5a42468','a5a42468'),('1','0','FAIL','00000000','a5a42468')]
    for owner,x in enumerate(ps):
        b,e=begins[i]['line'],ends[i]['line'];assert b<x['line']<e
        peer=exactly([o for o in phase_details[i]['operations'] if o['operation']=='REMOTE_WRITE' and o['d']==str(owner)])
        after=exactly([a for a in attrs if a['label']==f'phase{i}_owner{owner}_write_after' and a['device']=='1'])
        post_after=exactly([a for a in attrs if a['label']==f'phase{i}_owner{owner}_postwrite_cpu_after' and a['device']=='0'])
        assert after['line']<x['line']<post_after['line']<peer['line']
        assert not any(l.startswith('OWNER_CHECK ') for l in rl[after['line']:peer['line']-1])
assert fields(exactly([x for x in rl if x.startswith('CPUBAR_POSTWRITE_SUMMARY ')]))=={'pass':'5','fail':'5','skip':'0'}
assert fields(exactly([x for x in rl if x.startswith('CPUBAR_SUMMARY ')]))=={'pass':'10','fail':'0','skip':'0'}

phases=records(rl,'CaskLogicPeer ');assert len(phases)==122 and all(float(a['monotonic'])<float(b['monotonic']) for a,b in zip(phases,phases[1:]))
data=exactly([x for x in phases if x['phase']=='data_done']);cleanup=exactly([x for x in phases if x['phase']=='cleanup_begin'])
assert ends[-1]['line']<data['line']<final_restore['line']<cleanup['line']<program_end['line']
assert max(a['line'] for a in allocs)<begins[0]['line']
assert len(records(rl,'PROBE_PTR '))==2
free=[x for x in phases if x['phase']=='allocation_free_begin'];assert len(free)==4 and all(x['line']>cleanup['line'] for x in free)
kdata=exactly([n for n,l in enumerate(kl) if 'CaskLogicPeer phase=data_done ' in l]);kexit=exactly([n for n,l in enumerate(kl) if 'CaskLogicPeer phase=context_exit_begin ' in l])
assert all(c['destroy_kernel_line']>kdata+1 for c in chains)
assert sum('P2PTRC WINDOW_CREATE ' in l for l in kl)==4 and sum('P2PTRC WINDOW_DESTROY_BEGIN ' in l for l in kl)==4
errors=[{'line':n+1,'kernel_time':ktime(l),'text':l} for n,l in enumerate(kl) if 'left-over mappings' in l or 'nvAssertFailedNoLog' in l]
assert len(errors)==9 and all(x['line']>kexit+1 for x in errors)

snapshots=records(rl,'PCIE_SNAPSHOT ');assert len(snapshots)==606
groups=[snapshots[i:i+6] for i in range(0,len(snapshots),6)]
assert all(len({x['bdf'] for x in g})==6 and len({x['phase'] for x in g})==1 for g in groups)
assert all(x['CONFIG_BYTES']=='4096' and x['READ_ERRNO']=='0' and x['clock_ok']=='1' for x in snapshots)
deltas=[]
for before,after in zip(groups,groups[1:]):
    for b,a in zip(before,after):
        assert b['bdf']==a['bdf']
        changes={k:{'before':b[k],'after':a[k]} for k in b if k not in {'line','phase','monotonic'} and b[k]!=a[k]}
        if changes:deltas.append({'phase':a['phase'],'bdf':a['bdf'],'line_before':b['line'],'line_after':a['line'],'changes':changes})
assert len(deltas)==4 and all(x['changes']=={'PCI_STATUS':{'before':'0010','after':'2010'}} for x in deltas)
assert [(x['phase'],x['bdf']) for x in deltas]==[('phase0_owner0_read_after','0000:00:07.0'),('phase0_owner0_read_after','0000:06:00.0'),('phase0_owner1_read_after','0000:00:01.0'),('phase0_owner1_read_after','0000:01:00.0')]

cfg={}
for bdf in ['00:00.0','00:01.0','00:07.0','00:07.2','01:00.0','06:00.0']:
    p=HERE/'before-driver'/('0000_'+bdf.replace(':','_')+'.config');b=p.read_bytes()
    cfg[bdf]={'pci_id':f'{int.from_bytes(b[:2],"little"):04x}:{int.from_bytes(b[2:4],"little"):04x}','ccfg_d0':f'{int.from_bytes(b[0xd0:0xd4],"little"):08x}'}
    if bdf in ['01:00.0','06:00.0']:cfg[bdf]['bar1']=hex((int.from_bytes(b[0x14:0x18],'little')&~15)|(int.from_bytes(b[0x18:0x1c],'little')<<32))
assert cfg['00:00.0']['pci_id']=='8086:4641'
assert cfg['00:01.0']['ccfg_d0']=='00008077' and cfg['00:07.0']['ccfg_d0']==cfg['00:07.2']['ccfg_d0']=='00009077'
for key,val in [('PEG_CCFG 00:01.0','00008077'),('TCSS_CCFG 00:07.0','00009077'),('TCSS_CCFG 00:07.2','00009077')]:assert sum(l==key+' '+val for l in rl)==2
assert 'TCSS CCFG after test:' not in rl
out={'esito':'CONFRONTO_COMPLETATO_5_FASI_3_FALLIMENTI_SU_4_IN_OGNUNA; GATE_SHELL_FALSO_NEGATIVO',
 'ambito':'Solo rianalisi locale dei log acquisiti; nessuna nuova esecuzione GPU o modifica hardware',
 'independent_protocol_validation':True,'raw_script_rc':23,'raw_native_rc':5,'raw_probe_completed_marker':False,
 'after_test_ccfg_executed':False,'attr_restore_verified':True,
 'identity_config_before_driver':cfg,'ccfg_verified_before_and_after_driver_only':True,
 'payload_bytes':4,'mapping_bytes_per_allocation':0x200000,'persistent_allocations':4,
 'registry_override':'RM64KBBAR1Mappings=0','iommu_disabled_logged':any('DMAR: IOMMU disabled' in l for l in kl),
 'phase_details':phase_details,'peer_operations':operations,'failure_count':15,'comparison_count':20,
 'attribute_originals':original,'attribute_writes':attr_writes,'attribute_snapshot_count':len(attrs),'attribute_snapshots':attrs,
 'attribute_restore_records':restores,'attribute_final_restore':final_restore,'program_end':program_end,
 'allocations_and_chains':chains,'owner_checks':owners,'cpu_reads':cpu,'cpu_matches':matches,'cpu_results':results,'cpu_postwrite':post,
 'pcie_snapshot_count':len(snapshots),'pcie_groups':len(groups),'pcie_deltas':deltas,'aer_deltas':[],
 'timing':{'data_done_program_monotonic':data['monotonic'],'cleanup_begin_program_monotonic':cleanup['monotonic'],'context_exit_kernel_time':ktime(kl[kexit]),'first_cleanup_diagnostic_kernel_time':errors[0]['kernel_time'],'first_cleanup_diagnostic_delay_from_context_exit_ms':1000*(errors[0]['kernel_time']-ktime(kl[kexit]))},
 'cleanup_diagnostics':errors,'no_xid_recorded':not any('NVRM: Xid' in l for l in kl),
 'gate_diagnostic':{'cause':'BusyBox awk compares initial string index 0 against uninitialized n/begun; first phase marks bad. Explicit n=0;begun=0 resolves the same raw log with the same BusyBox binary, according to parent CPU-only reproduction.',
 'local_awk_original_actual_log_rc':0,'exact_busybox_original_rc_reported_by_parent':1,'exact_busybox_explicit_zero_rc_reported_by_parent':0,
 'raw_log_unchanged':True,'after_test_root_ccfg_snapshot_missing':True},
 'integrity':{'collected_checksums_all_match':True,'packaged_files_match_manifest':True,'files_hashed_locally':hashes,'files_hashed_inside_initrd':packed,'build_manifest':manifest},
 'limits':['The experiment clears both documented PCIe Device Control permissions, not a direct wire-level observation of TLP attributes. The result does not prove that every peer transaction has or lacks NoSnoop/RelaxedOrdering.',
 'NoSnoop and RelaxedOrdering were changed together; the result is a negative result for these settings under this mapping and firmware configuration, not a diagnosis of the failing root/USB4 routing path.',
 'The CUDA comparison completed and registers were restored; the shell validation subsequently returned 23. No PROBE_COMPLETED marker or after-test CCFG snapshot was executed.',
 'PTE chain verification uses software logs, not hardware PTE-table readback or PCIe TLP capture.',
 'CPU BAR1 checks cover one allocated four-byte word and do not certify peer requester traffic.',
 'CPU postwrite reads can influence latency and completion; both CPU and owner D2H see zero on A2000 and the expected word on Ada.',
 'Legacy PCI_STATUS Received Master Abort changed during the first read in each direction. It remains sticky; AER unchanged and later unchanged RMA do not prove a clean path.',
 'Cleanup IOVAS errors follow all comparisons and context exit, but their timing does not certify every earlier driver operation.']}
# Verify the recorded CPU-only reproduction and the exact binary inside the tested initrd.
gate_repro=json.loads((HERE/'busybox-gate-reproduction.json').read_text())
assert gate_repro['result_sha256']==hashes['result.log']['sha256'] and not gate_repro['hardware_operations']
assert any(x['sha256']==gate_repro['busybox_sha256'] for n,x in packed.items() if n.endswith('bin/busybox'))
assert [x['exit_code'] for x in gate_repro['runs']]==[1,1,0]
for run in gate_repro['runs']: assert sha(HERE/run['gate'])==run['gate_sha256']
original_gate=(HERE/'root-gate-original.awk').read_text()
zero_gate=(HERE/'root-gate-explicit-zero.awk').read_text()
assert zero_gate==original_gate.replace('BEGIN {','BEGIN {n=0;begun=0;',1)
assert original_gate.strip()==(HERE/'actual-gate.awk').read_text().strip()
out['gate_diagnostic']['reproduction_artifact']=gate_repro
out['gate_diagnostic']['reproduction_artifact_sha256']=sha(HERE/'busybox-gate-reproduction.json')
out['gate_diagnostic']['exact_busybox_binary_matches_tested_initrd']=True
out['gate_diagnostic']['only_gate_change']='Initialize n=0;begun=0 in BEGIN; all predicates unchanged'
(HERE/'verified-result.json').write_text(json.dumps(out,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({'status':out['esito'],'chains':len(chains),'owner_checks':len(owners),'snapshots':len(snapshots),'attribute_snapshots':len(attrs),'writes':len(attr_writes),'timing':out['timing'],'deltas':deltas},indent=2))
