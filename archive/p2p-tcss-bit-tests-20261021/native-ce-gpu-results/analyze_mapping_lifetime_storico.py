#!/usr/bin/env python3
"""Audit locale CE: provenienza, mapping receive, PCI e ordine vita allocazioni."""
from pathlib import Path
import hashlib,importlib.util,json,re,statistics,struct
root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('trace',root.parent/'driver-instrumented/analyze_p2ptrc.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
k=(root/'kernel.log').read_text();r=(root/'result.log').read_text();kl=k.splitlines();rl=r.splitlines()
d=m.analyze(k,r)
assert d['status']=='observed_software_mapping_chain_consistent' and len(d['chains'])==2
assert all(x['ok'] is True for x in d['checks'] if x['required']) and all(x['aligned'] is True for x in d['page_alignment'])
collected=json.loads((root/'collected-sha256.json').read_text());actual={n:sha(root/n) for n in collected};assert actual==collected and len(actual)==17
manifest=json.loads((root/'build-manifest.json').read_text());assert manifest==json.loads((root.parent/'native-ce-probe-package/build-manifest.json').read_text())
review=json.loads((root.parent/'native-ce-probe/independent-package-review-storico.json').read_text());assert review['status']=='PASS_STREAMED_CPIO_AND_INPUT_PROVENANCE'
files=json.loads((root/'files.json').read_text());state=json.loads((root/'native-ce-gpu-state.json').read_text());assert files==manifest['files']==review['files_sha256_verified']==state['files']
assert state['stage']=='armed' and state['automatic_return_seconds']==180
assert manifest['module_sha256']=='ab41b0a38e7ab92c0d1468b33c456c5c5c57501c67dfe5a666f49aed9fb6b1b5' and manifest['uvm_module_sha256']=='9b993671ef066c9d3e58fd52b0d70228861769a2e3dcf304bc3d80bca089c4d0'
assert manifest['native_program_sha256']=='7184d44dc039f662b21c86b1f20e644b21a3188bb7c028a8a0b12084bcdcfa4d'
assert manifest['libcuda_sha256']=='03271500dbda9456e3ba765270bd2609bef2631672809da50b19c67fb1f609a7'
rows=lambda prefix:[{'line':i,**m.fields(x)} for i,x in enumerate(rl,1) if x.startswith(prefix+' ')]
identity={0:('0000:01:00.0','00000000000000000000000000000001',0x28b010de),1:('0000:06:00.0','00000000000000000000000000000002',0x257110de)}
gpu=rows('CE_GPU');assert len(gpu)==26
for row in gpu:
 ident=identity[int(row['index'])];assert row['bdf']==ident[0] and row['uuid']==ident[1] and row['valid']=='1'
for bdf,uuid,pci_id in identity.values():assert struct.unpack_from('<I',(root/'before-driver'/(bdf.replace(':','_')+'.config')).read_bytes())[0]==pci_id
ccfg={}
for bdf,want in [('0000:00:01.0',0x8077),('0000:00:07.0',0x9077),('0000:00:07.2',0x9077)]:
 assert struct.unpack_from('<I',(root/'before-driver'/(bdf.replace(':','_')+'.config')).read_bytes(),0xd0)[0]==want
 vals=re.findall(r'^(?:PEG_CCFG|TCSS_CCFG) '+re.escape(bdf[5:])+r' ([0-9a-f]+)$',r,re.M);assert len(vals)==3 and all(int(v,16)==want for v in vals);ccfg[bdf]=vals
alloc=rows('CE_ALLOCATION');assert len(alloc)==4 and len({a['nonce'] for a in alloc})==4 and {(x['owner'],x['role']) for x in alloc}=={('0','send'),('0','receive'),('1','send'),('1','receive')}
for a in alloc:assert int(a['allocation_bytes'])==0x800000 and int(a['granularity'])==0x200000 and int(a['va'],16)%0x200000==0
access=rows('CE_ACCESS');assert len(access)==104
for a in access:
 expected='3' if a['role']=='receive' or a['owner']==a['device'] else '0'
 assert a['first']==a['last']==a['expected']==expected and a['valid']=='1' and a['location_id']==a['owner']
chains=[]
for c in d['chains']:
 p=d['events'][c['rm_pte_index']];w=d['events'][c['window_index']];u=d['events'][c['uvm_pte_index']]
 aa=[a for a in alloc if a['va']==c['gpu_va']];assert len(aa)==1 and aa[0]['role']=='receive';a=aa[0];owner=int(a['owner'])
 assert c['owner_bdf']==identity[owner][0] and c['source_bdf']==identity[1-owner][0]
 begin=[i for i,x in enumerate(kl,1) if 'CaskLogicCEAllocation nonce='+a['nonce']+' stage=begin ' in x];end=[i for i,x in enumerate(kl,1) if 'CaskLogicCEAllocation nonce='+a['nonce']+' stage=end ' in x]
 assert len(begin)==len(end)==1 and begin[0]<w['line']<p['line']<u['line']<end[0]
 pf=p['fields'];wf=w['fields'];uf=u['fields']
 assert int(wf['size'],16)==int(uf['map_size'],16)==0x800000 and int(wf['bar1_off'],16)==0x400000
 assert int(pf['page'],16)==int(uf['page'],16)==0x200000 and pf['entry']==uf['entry']=='16' and pf['pte_count']==uf['count']=='4'
 assert pf['aperture']=='3' and pf['valid']==pf['atomic']==pf['volatile']=='1' and pf['readonly']=='0'
 assert pf['raw0']==uf['raw0'] and pf['raw1']==uf['raw1']=='0000000000000000'
 phys=0x4000400000 if owner==0 else 0x4600400000
 assert all(int(pf[f],16)==phys for f in ['dma_base','phys_input','decoded'])
 chains.append({'role':'receive_only_peer_window','owner':owner,'requester':1-owner,'nonce':a['nonce'],'gpu_va':a['va'],'bytes':0x800000,'window_id':wf['id'],'bar1_base':wf['bar1'],'bar1_offset':wf['bar1_off'],'physical_dma_decoded':hex(phys),'page_bytes':0x200000,'pte_count':4,'entry_bytes':16,'software_aperture':3,'hardware_aperture':3,'readonly':0,'valid':1,'volatile':1,'atomic_permission':1,'raw0':pf['raw0'],'raw1':pf['raw1'],'nonce_begin_line':begin[0],'nonce_end_line':end[0],'rm_line':p['line'],'uvm_line':u['line']})
assert len([x for x in d['events'] if x['event']=='WINDOW_CREATE'])==2
cases=rows('CE_CASE');results=rows('CE_DATA_RESULT');compares=rows('FULL_COMPARE');assert len(cases)==len(results)==12 and len(compares)==36
for n,(case,result) in enumerate(zip(cases,results),1):
 assert int(case['id'])==int(result['id'])==n and all(case[f]==result[f] for f in ['engine','s','d','bytes'])
 src=[a for a in alloc if a['owner']==case['s'] and a['role']=='send'][0];dst=[a for a in alloc if a['owner']==case['d'] and a['role']=='receive'][0]
 assert case['src']==src['va'] and case['dst']==dst['va'] and case['allocations_unchanged']=='1'
 assert int(case['bytes']) in [4,65536,1048576] and int(case['bytes'])<=0x200000
 full=[a for a in compares if int(a['iteration'])==n];assert [x['stage'] for x in full]==['source_initialized','destination_poisoned','peer_payload']
 assert all(x['valid']=='1' and x['mismatches']=='0' for x in full[:2])
 assert full[2]['valid']==result['valid'] and full[2]['mismatches']==result['mismatches']
 assert result['valid']==('0' if case['s']=='0' else '1') and int(result['checked_words'])*4==int(case['bytes'])
 assert int(result['mismatches'])==(int(result['checked_words']) if case['s']=='0' else 0)
phase_rows=rows('CaskLogicCE');phase={x['phase']:x for x in phase_rows};assert len(phase_rows)==62
for n in range(12):
 segment=[x for x in phase_rows if x['phase'] in ['owners_ready','transfer_begin','transfer_complete','comparison_done']][n*4:n*4+4]
 assert [x['phase'] for x in segment]==['owners_ready','transfer_begin','transfer_complete','comparison_done']
 assert [float(x['monotonic']) for x in segment]==sorted(float(x['monotonic']) for x in segment)
 full=[a for a in compares if int(a['iteration'])==n+1]
 assert full[1]['line']<segment[0]['line']<segment[1]['line']<segment[2]['line']<full[2]['line']<segment[3]['line']
frees=[x for x in phase_rows if x['phase'].startswith('allocation_free_')];assert len(frees)==8 and all(float(x['monotonic'])>float(phase['data_done']['monotonic']) for x in frees)
assert float(phase['data_done']['monotonic'])<float(phase['cleanup_done']['monotonic'])<float(phase['context_exit_begin']['monotonic'])
kphases=[]
for i,x in enumerate(kl,1):
 if 'CaskLogicCE phase=' in x:
  t=float(re.search(r'\[\s*([0-9.]+)\]',x)[1]);v=m.fields(x);kphases.append({'line':i,'kernel_time':t,**v})
assert len(kphases)==62
kphase={x['phase']:x for x in kphases};errors=[]
for e in d['kernel_errors']:
 assert e['line']>kphase['context_exit_begin']['line'] and e['kernel_time']>kphase['context_exit_begin']['kernel_time']
 errors.append({'line':e['line'],'raw':e['raw'],'after_context_exit_ms':(e['kernel_time']-kphase['context_exit_begin']['kernel_time'])*1000})
assert len(errors)==9
wd=[e for e in d['events'] if e['event']=='WINDOW_DESTROY_DONE'];assert len(wd)==2 and {e['fields']['id'] for e in wd}=={'1','2'} and all(kphase['data_done']['line']<e['line']<kphase['cleanup_done']['line'] for e in wd)
offsets=[x['kernel_time']-float(x['monotonic']) for x in kphases]
snaps=rows('PCIE_SNAPSHOT');assert len(snaps)==150 and all(x['CONFIG_BYTES']=='4096' and x['READ_ERRNO']=='0' and x['clock_ok']=='1' for x in snaps)
last={};deltas=[]
for s in snaps:
 old=last.get(s['bdf']);last[s['bdf']]=s
 if old:
  for key in set(s)|set(old):
   if key not in {'monotonic','phase','line'} and s.get(key)!=old.get(key):deltas.append({'bdf':s['bdf'],'field':key,'before':old.get(key),'after':s.get(key),'phase':s['phase']})
assert not deltas
assert all(x in r for x in ['NATIVE_TEST_RC=5','SCRIPT_RC=5','PROBE_COMPLETED','CE_PROGRAM_END protocol_complete=1 comparisons=12 failures=6 trace_complete=1'])
assert 'RM64KBBAR1Mappings=0' in r and 'RMCaskPeerCoherent=1' not in r
out={'status':'PASS_INDEPENDENT_PROVENANCE_MAPPING_PCI_LIFETIME_AUDIT','collected_sha256_verified':actual,'package_review':'../native-ce-probe/independent-package-review-storico.json','package_files':files,'payload_files':manifest['payload_files'],'GPU_identities':identity,'CCFG_before_after_driver_after_test':ccfg,'allocation_count':4,'allocation_bytes_each':8388608,'receive_only_peer_windows':chains,'software_mapping_failed_checks':0,'software_mapping_missing_checks':0,'all_send_buffers_inaccessible_to_other_gpu':True,'access_checks':104,'local_owner_checks':24,'local_owner_checks_pass':24,'data_results':results,'all_test_sizes_within_first_logged_PTE':True,'pcie_snapshots':150,'all_pcie_config_reads_valid':True,'all_sequential_pcie_deltas':deltas,'data_done_monotonic':phase['data_done']['monotonic'],'context_exit_begin_monotonic':phase['context_exit_begin']['monotonic'],'all_frees_deferred_until_after_data':True,'window_destroy_done_ids':[x['fields']['id'] for x in wd],'kernel_clock_alignment_samples':len(offsets),'kernel_minus_monotonic_median':statistics.median(offsets),'kernel_minus_monotonic_spread_seconds':max(offsets)-min(offsets),'cleanup_errors':errors,'Xid_count':sum('Xid ' in x for x in kl),'program_and_wrapper_rc':5,'PROBE_COMPLETED':True,'hardware_operations':False,'limits':['RM/UVM equality is software trace, not hardware page-table readback or TLP capture.','Each 8 MiB mapping logs only its first PTE; all tested payloads are at most 1 MiB and therefore fall within that first 2 MiB page.','CUPTI route and activity interpretation is independently documented by cupti-independent-log-audit.json; no direct PCIe route is proven by this report.','No PCI status change does not prove absence of undetected transaction rejection or loss.','Four residual IOVAS mappings and eight asserts remain a separate cleanup defect after all twelve comparisons.']}
(root/'independent-mapping-lifetime-review-storico.json').write_text(json.dumps(out,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({'status':out['status'],'files':len(actual),'receive_windows':len(chains),'snapshots':len(snaps),'deltas':len(deltas),'first_cleanup_after_exit_ms':errors[0]['after_context_exit_ms']}))
