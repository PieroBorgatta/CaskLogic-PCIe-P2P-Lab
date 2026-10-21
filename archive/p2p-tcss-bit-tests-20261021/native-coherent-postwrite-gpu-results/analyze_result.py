#!/usr/bin/env python3
"""Verifica locale ripetibile del risultato SYS_COH; nessuna operazione hardware."""
from pathlib import Path
import hashlib,importlib.util,json,re,struct
root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('trace',root.parent/'driver-instrumented/analyze_p2ptrc.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
k=(root/'kernel.log').read_text();r=(root/'result.log').read_text();d=json.loads((root/'coherent-chain-validation.json').read_text())
collected=json.loads((root/'collected-sha256.json').read_text());actual={n:sha(root/n) for n in collected};assert actual==collected and len(actual)==17
assert d['status']=='observed_software_mapping_chain_consistent' and d['coherent_aperture_validation']['exact_four_coherent_writable_valid_PTEs']
assert len(d['chains'])==4 and all(x['ok'] is True for x in d['checks'] if x['required']) and all(x['aligned'] is True for x in d['page_alignment'])
comparison=d['comparison_to_baseline']['mappings'];assert len(comparison)==4
assert all(x['physical_input_unchanged'] and x['only_raw_aperture_bit_changed_if_same_address'] and all(y['same'] for y in x['fields'].values()) for x in comparison)
manifest=json.loads((root/'build-manifest.json').read_text());assert manifest==json.loads((root.parent/'native-coherent-postwrite-probe-package/build-manifest.json').read_text())
expected_hashes={'module_sha256':'c89df9beff8ee414e020a46d8860ec8b198b896d262bd49d89811d03e052e7eb','uvm_module_sha256':'9b993671ef066c9d3e58fd52b0d70228861769a2e3dcf304bc3d80bca089c4d0','native_program_sha256':'f5918b04fd9416d8378f962f0f772968dd877ac1a21153b82a9f4abe0ce1ad5b','native_source_sha256':'c05a9ccd05dfc3488457c0bcf9c2eba8736406a0c6ff1011c020bafa09990006','cpu_header_sha256':'b5a4627e692b929eda5689622b884b12f41e8e44259ca36585179915fe6c1170'}
assert all(manifest[x]==v for x,v in expected_hashes.items())
package_review=json.loads((root.parent/'native-coherent-postwrite-probe/independent-package-review-storico.json').read_text());assert package_review['status']=='PASS_PACKAGE_SOURCE_INIT_ALIGNMENT' and package_review['native_program_sha256']==manifest['native_program_sha256']
for name,value in json.loads((root/'files.json').read_text()).items():assert value==package_review['files_sha256_verified'][name]
identity={0:('0000:01:00.0','GPU-00000000-0000-0000-0000-000000000001',0x28b010de),1:('0000:06:00.0','GPU-00000000-0000-0000-0000-000000000002',0x257110de)}
for dev,(bdf,uuid,expected_id) in identity.items():
 raw=(root/'before-driver'/(bdf.replace(':','_')+'.config')).read_bytes();assert struct.unpack_from('<I',raw)[0]==expected_id
 assert uuid in r and bdf.replace('0000:','00000000:') in r
ccfg={}
for bdf,expected in [('0000:00:01.0',0x8077),('0000:00:07.0',0x9077),('0000:00:07.2',0x9077)]:
 raw=(root/'before-driver'/(bdf.replace(':','_')+'.config')).read_bytes();assert struct.unpack_from('<I',raw,0xd0)[0]==expected
 pattern=r'^(?:PEG_CCFG|TCSS_CCFG) '+re.escape(bdf[5:])+r' ([0-9a-f]+)$';values=re.findall(pattern,r,re.M);assert len(values)==3 and all(int(v,16)==expected for v in values);ccfg[bdf]=values
alloc=[m.fields(x) for x in r.splitlines() if x.startswith('CPUBAR_ALLOCATION ')];assert len(alloc)==4 and len({x['token'] for x in alloc})==4
chains=[]
for c in d['chains']:
 pte=d['events'][c['rm_pte_index']];win=d['events'][c['window_index']];uvm=d['events'][c['uvm_pte_index']]
 assert c['probe_role_source']=='direct PROBE_PTR address within UVM mapping'
 meta=[a for a in alloc if int(a['gpu_va'],16)==int(c['gpu_va'],16)];assert len(meta)==1;meta=meta[0];owner=int(meta['owner']);assert meta['owner_bdf']==identity[owner][0] and meta['owner_uuid']==identity[owner][1] and meta['requester_bdf']==identity[1-owner][0] and meta['requester_uuid']==identity[1-owner][1]
 begin=[i for i,line in enumerate(k.splitlines(),1) if 'CaskLogicCPUBAR token='+meta['token'] in line and 'phase=begin' in line];end=[i for i,line in enumerate(k.splitlines(),1) if 'CaskLogicCPUBAR token='+meta['token'] in line and 'phase=end' in line];assert len(begin)==len(end)==1 and begin[0]<win['line']<pte['line']<uvm['line']<end[0]
 assert int(pte['fields']['page'],16)==0x200000 and int(pte['fields']['entry'])==16 and int(pte['fields']['pte_count'])==1
 chains.append({'window_id':int(win['fields']['id']),'owner':c['owner_bdf'],'requester':c['source_bdf'],'gpu_va':c['gpu_va'],'role':c['probe_allocation_role'],'nonce':meta['token'],'page_bytes':0x200000,'entry_bytes':16,'bar':win['fields']['bar1'],'bar_offset':win['fields']['bar1_off'],'physical_dma_decoded':pte['fields']['phys_input'],'raw0':pte['fields']['raw0'],'software_enum':4,'hardware_encoding':2,'readonly':0,'volatile':1,'atomic':1,'line_rm':pte['line'],'line_uvm':uvm['line']})
assert len(d['owners'])==10 and all(x['valid']=='1' for x in d['owners'])
operations=d['data_operations'];assert len(operations)==4 and [x['valid'] for x in operations]==['0','1','0','0']
post=[{'line':i,**m.fields(x)} for i,x in enumerate(r.splitlines(),1) if x.startswith('CPUBAR_POSTWRITE ')];assert len(post)==2 and [x['observed'] for x in post]==['a5a42468','00000000'] and [x['status'] for x in post]==['PASS','FAIL']
cpu_before=[m.fields(x) for x in r.splitlines() if x.startswith('CPUBAR_RESULT ')];assert len(cpu_before)==2 and all(x['status']=='PASS' and x['restored']=='1' for x in cpu_before)
for x in post:
 matches=[c for c in chains if c['window_id']==int(x['window_id'])];assert len(matches)==1 and int(matches[0]['gpu_va'],16)==int(x['gpu_va'],16) and matches[0]['physical_dma_decoded']==x['physical']
phase={p['phase']:float(p['monotonic']) for p in d['phases']}
for p in d['phases']:
 if p['phase'].startswith('allocation_free_'):assert float(p['monotonic'])>phase['data_done']
errors=[{'line':x['line'],'raw':x['raw'],'estimated_monotonic':x['monotonic_estimate'],'after_context_exit_ms':1000*(x['monotonic_estimate']-phase['context_exit_begin'])} for x in d['kernel_errors']];assert len(errors)==9 and all(x['after_context_exit_ms']>0 for x in errors)
destroys=[e for e in d['events'] if e['event']=='WINDOW_DESTROY_DONE'];assert len(destroys)==4 and {x['fields']['id'] for x in destroys}=={'1','2','3','4'}
snaps=[m.fields(x) for x in r.splitlines() if x.startswith('PCIE_SNAPSHOT ')];assert len(snaps)==126 and all(x['CONFIG_BYTES']=='4096' and x['READ_ERRNO']=='0' and x['clock_ok']=='1' for x in snaps)
last={};deltas=[]
for s in snaps:
 old=last.get(s['bdf']);last[s['bdf']]=s
 if old:
  for key in set(s)|set(old):
   if key not in {'monotonic','phase'} and s.get(key)!=old.get(key):deltas.append({'bdf':s['bdf'],'field':key,'before':old.get(key),'after':s.get(key),'phase':s['phase']})
assert len(deltas)==4 and all(x['field']=='PCI_STATUS' and x['before']=='0010' and x['after']=='2010' for x in deltas)
assert r.count('REGISTRY_TEST_OVERRIDE=RM64KBBAR1Mappings=0;RMCaskPeerCoherent=1')==1
assert all(x in r for x in ['TOTAL_FAILURES 3','NATIVE_TEST_RC=5','SCRIPT_RC=5','PROBE_COMPLETED','CPUBAR_POSTWRITE_SUMMARY pass=1 fail=1 skip=0'])
out={'status':'SYS_COH_effettivo_confermato_P2P_ancora_3_fallimenti_su_4','collected_sha256_verified':actual,'package_and_source_review':'../native-coherent-postwrite-probe/independent-package-review-storico.json','build_hashes':expected_hashes,'source_identical_to_baseline':True,'CPU_parser_only_change':'software enum4->HW2; enum3->HW3; rejectPEER2','GPU_identity':{str(i):{'bdf':v[0],'uuid':v[1],'pci_id':hex(v[2])} for i,v in identity.items()},'CCFG_before_driver_after_driver_after_test':ccfg,'registry_override':'RM64KBBAR1Mappings=0;RMCaskPeerCoherent=1','software_mapping_chains':chains,'mapping_checks_failed':0,'mapping_checks_missing':0,'all_same_addresses_and_attributes_except_aperture':True,'raw0_XOR_vs_baseline':[x['raw0_xor'] for x in comparison],'owner_checks_count':10,'owner_checks_pass':10,'peer_operations':operations,'corruption_lines':[x for x in r.splitlines() if x.startswith('CORRUPTION ')],'CPU_before_peer':cpu_before,'CPU_postwrite':post,'native_and_script_RC':5,'PROBE_COMPLETED':True,'pcie_snapshots':126,'pcie_all_readable':True,'all_sequential_pcie_deltas':deltas,'operation_pcie_deltas':d['pcie_changes'],'data_done_monotonic':phase['data_done'],'context_exit_begin_monotonic':phase['context_exit_begin'],'clock_alignment':d['clock_alignment'],'cleanup_errors':errors,'window_destroy_done_ids':[x['fields']['id'] for x in destroys],'Xid_count':sum('Xid ' in x for x in k.splitlines()),'hardware_operations_by_reviewer':False,'limits':['Il PTE software e il submit completato non sono readback delle tabelle hardware né cattura TLP.','Le operazioni sono load/store ordinari: nessuna qualifica atomiche, managed memory o produzione.','La prova non cambia simultaneamente SYS_COH e DeviceControl; non esclude ogni combinazione futura.','Il codice non corregge il cleanup IOVAS; i residui/assert registrati seguono tutti i confronti.','L’esito negativo non identifica il componente finale che impedisce la consegna né prova impossibilità hardware assoluta.']}
(root/'verified-result.json').write_text(json.dumps(out,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({'status':out['status'],'files':len(actual),'chains':len(chains),'snapshots':len(snaps),'first_cleanup_after_exit_ms':errors[0]['after_context_exit_ms']}))
