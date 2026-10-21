#!/usr/bin/env python3
"""Rianalisi locale dei log già acquisiti; nessun accesso hardware."""
from pathlib import Path
import gzip, hashlib, json, re, statistics

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
rl = (HERE/'result.log').read_text().splitlines()
kl = (HERE/'kernel.log').read_text().splitlines()
manifest = json.loads((HERE/'build-manifest.json').read_text())
state = json.loads((HERE/'state.json').read_text())

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
    p=ROOT/'native-cpubar-postwrite-probe-package'/name
    actual=sha(p);assert actual==expected,name
    hashes['../native-cpubar-postwrite-probe-package/'+name]={'sha256':actual,'bytes':p.stat().st_size}
for name,key in [('peer_vmm_word_cpubar_postwrite.cu','native_source_sha256'),('cpubar_trace.h','cpu_header_sha256'),('pcie_diag.h','native_header_sha256')]:
    p=ROOT/'native-cpubar-postwrite-probe'/name;actual=sha(p);assert actual==manifest[key],name
    hashes['../native-cpubar-postwrite-probe/'+name]={'sha256':actual,'bytes':p.stat().st_size}
assert state['files']['probe-initrd.img']==manifest['initrd_sha256']
assert state['files']['probe-kernel.efi']==manifest['kernel_sha256']

# Hash the actual selected files inside the gzip/newc initramfs, without extraction.
packed={}
with gzip.open(ROOT/'native-cpubar-postwrite-probe-package/probe-initrd.img','rb') as f:
    while True:
        h=f.read(110); assert len(h)==110 and h[:6] in (b'070701',b'070702')
        v=[int(h[6+i*8:14+i*8],16) for i in range(13)]; size,namesize=v[6],v[11]
        name=f.read(namesize).rstrip(b'\0').decode();f.read((-(110+namesize))%4)
        if name=='TRAILER!!!': break
        wanted=name.endswith(('.ko','peer_word','libcuda.so.1')) or name in ('init','./init')
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

cpu=records(rl,'CPUBAR_READ ');assert len(cpu)==4 and all(x['valid']=='1' and x['observed']==x['expected'] for x in cpu)
matches=records(rl,'CPUBAR_MATCH ');results=records(rl,'CPUBAR_RESULT ')
assert len(results)==2 and all(x['status']=='PASS' and x['restored']=='1' for x in results)
for m in matches:
    c=chains[int(m['window_id'])-1]
    assert m['gpu_va']==c['gpu_va'] and m['bdf']==c['owner_bdf'] and m['physical']==c['window']['window_phys']
    assert m['mapping']=='O_RDONLY_PROT_READ'
post=records(rl,'CPUBAR_POSTWRITE ');assert len(post)==2
assert [(x['owner'],x['writer'],x['status'],x['observed'],x['expected']) for x in post]==[('0','1','PASS','a5a42468','a5a42468'),('1','0','FAIL','00000000','a5a42468')]
post_summary=exactly(records(rl,'CPUBAR_POSTWRITE_SUMMARY '))
assert (post_summary['pass'],post_summary['fail'],post_summary['skip'])==('1','1','0')
for x in post:
    c=chains[int(x['window_id'])-1]
    assert x['owner']==c['owner'] and x['bdf']==c['owner_bdf']
    assert int(x['gpu_va'],16)==int(c['gpu_va'],16)
    assert x['physical']==c['window']['window_phys'] and x['mapping']=='O_RDONLY_PROT_READ'
    assert int(x['valid'])==int(x['observed']==x['expected'])
    init_owner=exactly([z for z in results if z['owner']==x['owner']])
    assert init_owner['line']<x['line']
owners=records(rl,'OWNER_CHECK ');assert len(owners)==10 and all(x['valid']=='1' and x['observed']==x['expected'] for x in owners)
ops=[]
for n,l in enumerate(rl):
    if l.startswith(('REMOTE_READ ','REMOTE_WRITE ')):
        ops.append(dict(fields(l),operation=l.split()[0],line=n+1,preceding_line=rl[n-1]))
assert [(x['operation'],x['s'],x['d'],x['valid']) for x in ops]==[('REMOTE_READ','0','1','0'),('REMOTE_WRITE','1','0','1'),('REMOTE_READ','1','0','0'),('REMOTE_WRITE','0','1','0')]
phases=records(rl,'CaskLogicPeer ');assert all(float(a['monotonic'])<float(b['monotonic']) for a,b in zip(phases,phases[1:]))
data=exactly([x for x in phases if x['phase']=='data_done'])
cleanup=exactly([x for x in phases if x['phase']=='cleanup_begin'])
assert all(x['line']<data['line']<cleanup['line'] for x in ops)
free=[x for x in phases if x['phase']=='allocation_free_begin'];assert len(free)==4 and all(x['line']>cleanup['line'] for x in free)

for x in post:
    op=exactly([o for o in ops if o['operation']=='REMOTE_WRITE' and o['s']==x['writer'] and o['d']==x['owner']])
    begin=exactly([z for z in phases if z['phase']=='cpubar_postwrite_begin' and z['s']==x['owner']])
    done=exactly([z for z in phases if z['phase']=='cpubar_postwrite_done' and z['s']==x['owner']])
    assert begin['line']<done['line']<x['line']<op['line']<data['line']
    x['phase_begin']=begin;x['phase_done']=done;x['matching_peer_result']=op
    assert not any(l.startswith('OWNER_CHECK ') for l in rl[begin['line']:op['line']-1])
    if x['status']=='FAIL':assert op['preceding_line']=='CORRUPTION write i 0 got 00000000'
    else:assert op['valid']=='1'
snapshots=records(rl,'PCIE_SNAPSHOT ');assert len(snapshots)==126
groups=[snapshots[i:i+6] for i in range(0,len(snapshots),6)]
assert all(len({x['bdf'] for x in g})==6 and len({x['phase'] for x in g})==1 for g in groups)
assert all(x['CONFIG_BYTES']=='4096' and x['READ_ERRNO']=='0' and x['clock_ok']=='1' for x in snapshots)
delta=[]
ignored={'line','phase','monotonic'}
for before,after in zip(groups,groups[1:]):
    for b,a in zip(before,after):
        assert b['bdf']==a['bdf']
        changes={k:{'before':b[k],'after':a[k]} for k in b if k not in ignored and b[k]!=a[k]}
        if changes:delta.append({'phase':a['phase'],'bdf':a['bdf'],'line_before':b['line'],'line_after':a['line'],'changes':changes})
assert len(delta)==4 and all(x['changes']=={'PCI_STATUS':{'before':'0010','after':'2010'}} for x in delta)
assert [(x['phase'],x['bdf']) for x in delta]==[('read_0_to_1_after','0000:00:07.0'),('read_0_to_1_after','0000:06:00.0'),('read_1_to_0_after','0000:00:01.0'),('read_1_to_0_after','0000:01:00.0')]
for x in post:
    before=[z for z in snapshots if z['phase']==f"cpubar_postwrite_owner_{x['owner']}_before"]
    after=[z for z in snapshots if z['phase']==f"cpubar_postwrite_owner_{x['owner']}_after"]
    assert len(before)==len(after)==6
    assert max(z['line'] for z in before)<min(z['line'] for z in after)<x['line']
    x['cpu_read_monotonic_bracket']={'after':before[-1]['monotonic'],'before':after[0]['monotonic']}
kdata=exactly([n for n,l in enumerate(kl) if 'CaskLogicPeer phase=data_done ' in l])
kexit=exactly([n for n,l in enumerate(kl) if 'CaskLogicPeer phase=context_exit_begin ' in l])
errors=[{'line':n+1,'kernel_time':ktime(l),'text':l} for n,l in enumerate(kl) if 'left-over mappings' in l or 'nvAssertFailedNoLog' in l]
assert len(errors)==9 and all(x['line']>kexit+1 for x in errors)
assert all(c['destroy_kernel_line']>kdata+1 for c in chains)
offsets=[]
for l in kl:
    if 'CaskLogicPeer ' in l:
        f=fields(l);offsets.append(ktime(l)-float(f['monotonic']))
assert len(offsets)==len(phases)

cfg={}
for bdf in ['00:01.0','00:07.0','00:07.2','01:00.0','06:00.0']:
    p=HERE/'before-driver'/('0000_'+bdf.replace(':','_')+'.config');b=p.read_bytes()
    cfg[bdf]={'pci_id':f'{int.from_bytes(b[:2],"little"):04x}:{int.from_bytes(b[2:4],"little"):04x}',
              'ccfg_d0':f'{int.from_bytes(b[0xd0:0xd4],"little"):08x}'}
    if bdf in ['01:00.0','06:00.0']:cfg[bdf]['bar1']=hex((int.from_bytes(b[0x14:0x18],'little')&~15)|(int.from_bytes(b[0x18:0x1c],'little')<<32))
assert cfg['00:01.0']['ccfg_d0']=='00008077' and cfg['00:07.0']['ccfg_d0']==cfg['00:07.2']['ccfg_d0']=='00009077'
for key,val in [('PEG_CCFG 00:01.0','00008077'),('TCSS_CCFG 00:07.0','00009077'),('TCSS_CCFG 00:07.2','00009077')]:assert sum(l==key+' '+val for l in rl)==3
assert 'TOTAL_FAILURES 3' in rl and 'NATIVE_TEST_RC=5' in rl and 'PROBE_COMPLETED' in rl
out={'esito':'CPU_POSTWRITE_ADA_PASS_A2000_ZERO_FAIL; P2P_3_FALLIMENTI_SU_4',
 'ambito':'Solo rianalisi locale; nessuna nuova esecuzione o modifica hardware',
 'identita_config_pre_driver':cfg,'kernel':'7.0.0-38-generic','driver':'595.99.02',
 'iommu_disabled_verified':any('DMAR: IOMMU disabled' in l for l in kl),
 'registry_override':'RM64KBBAR1Mappings=0','payload_bytes':4,'mapping_bytes_per_allocation':0x200000,
 'cpu_postwrite':post,'cpu_postwrite_summary':post_summary,
 'allocazioni_e_catene':chains,'cpu_matches':matches,'cpu_reads':cpu,'cpu_results':results,'owner_checks':owners,'peer_operations':ops,
 'fasi_programma':phases,'pcie_snapshot_count':len(snapshots),'pcie_group_count':len(groups),'pcie_snapshots':snapshots,'pcie_deltas':delta,
 'timing':{'data_done_program_monotonic':data['monotonic'],'cleanup_begin_program_monotonic':cleanup['monotonic'],
  'context_exit_kernel_time':ktime(kl[kexit]),'first_cleanup_diagnostic_kernel_time':errors[0]['kernel_time'],
  'first_cleanup_diagnostic_delay_from_context_exit_ms':1000*(errors[0]['kernel_time']-ktime(kl[kexit])),
  'common_markers':len(offsets),'kernel_minus_monotonic_seconds':{'median':statistics.median(offsets),'min':min(offsets),'max':max(offsets)}},
 'cleanup_diagnostics':errors,'no_xid_recorded':not any('NVRM: Xid' in l for l in kl),
 'low_mmio_helper_executed':False,
 'integrita':{'collected_checksums_all_match':True,'packaged_files_match_manifest':True,'files_hashed_locally':hashes,'files_hashed_inside_initrd':packed,'build_manifest':manifest},
 'limiti':['CPU BAR1 PASS verifies the selected four-byte physical window against two owner patterns, not every byte of the allocation.',
 'CPU postwrite and subsequent owner D2H agree in this run: no observed divergence that would isolate owner D2H cache visibility. Both see zero for A2000; this does not by itself localize why the peer write was not visible.',
 'The CPU read adds latency and a PCIe transaction; it may affect ordering and completion, so it is an observation under this protocol.',
 'The address chain and submitted PTE words are traced in software; no hardware PTE-table readback or PCIe TLP capture is available.',
 'CPU-originated traffic does not exercise the peer requester path. CPU PASS does not certify routing, ATS/IOMMU handling, cache attributes or hardware interpretation of a peer PTE.',
 'RMA is sticky: unchanged after subsequent writes does not prove that no new error occurred. AER unchanged does not mean PCIe clean.',
 'Cleanup errors are genuine and follow the comparisons. Their late timestamps do not establish that every earlier driver operation was correct.',
 'The build manifest hardware_boot_started=false is build-time metadata; completed runtime evidence is result.log and kernel.log.']}
(HERE/'verified-result.json').write_text(json.dumps(out,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({'status':out['esito'],'chains':len(chains),'owner_checks':len(owners),'snapshots':len(snapshots),'deltas':delta,'packaged_files':packed,'timing':out['timing']},indent=2))
