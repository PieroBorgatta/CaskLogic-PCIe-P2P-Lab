#!/usr/bin/env python3
"""Analisi offline del collaudo 4K; nessun accesso a rete o hardware."""
from pathlib import Path
import hashlib,importlib.util,json,re
root=Path(__file__).resolve().parent
parser_path=root.parent/'driver-instrumented/analyze_p2ptrc.py'
spec=importlib.util.spec_from_file_location('p2ptrc',parser_path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
k=(root/'kernel.log').read_text();r=(root/'result.log').read_text();d=m.analyze(k,r)
collected=json.loads((root/'collected-sha256.json').read_text());actual={n:sha(root/n) for n in collected};assert actual==collected
assert d['status']=='observed_software_mapping_chain_consistent'
assert len(d['chains'])==4 and len(d['data_operations'])==4
assert all(x['ok'] is True for x in d['checks'] if x['required'])
assert all(x['aligned'] is True for x in d['page_alignment'])
assert len(d['owners'])==10 and all(x['valid']=='1' for x in d['owners'])
chains=[]
for c in d['chains']:
 pte=d['events'][c['rm_pte_index']];w=d['events'][c['window_index']];u=d['events'][c['uvm_pte_index']]
 assert int(pte['fields']['page'],16)==4096 and int(pte['fields']['entry'])==8 and int(pte['fields']['pte_count'])==512
 assert c['probe_role_source']=='direct PROBE_PTR address within UVM mapping'
 chains.append({'window_id':int(w['fields']['id']),'owner':c['owner_bdf'],'requester':c['source_bdf'],'gpu_va':c['gpu_va'],'role':c['probe_allocation_role'],'page_bytes':4096,'pte_entry_bytes':8,'reported_pte_count':512,'bar':w['fields']['bar1'],'bar_offset':w['fields']['bar1_off'],'physical':pte['fields']['phys_input'],'decoded':pte['fields']['decoded'],'dma_base':pte['fields']['dma_base'],'raw_first_pte':pte['fields']['raw0'],'aperture':int(pte['fields']['aperture']),'readonly':int(pte['fields']['readonly']),'volatile':int(pte['fields']['volatile']),'line_rm':pte['line'],'line_uvm':u['line']})
post=[{'line':i,**m.fields(x)} for i,x in enumerate(r.splitlines(),1) if x.startswith('CPUBAR_POSTWRITE ')]
assert len(post)==2 and [x['observed'] for x in post]==['a5a42468','00000000']
phase={p['phase']:float(p['monotonic']) for p in d['phases']}
errors=[{'line':x['line'],'raw':x['raw'],'estimated_monotonic':x['monotonic_estimate'],'after_context_exit_ms':1000*(x['monotonic_estimate']-phase['context_exit_begin'])} for x in d['kernel_errors']]
assert all(x['after_context_exit_ms']>0 for x in errors)
destroys=[e for e in d['events'] if e['event']=='WINDOW_DESTROY_DONE'];assert len(destroys)==4
assert {e['fields']['id'] for e in destroys}=={'1','2','3','4'}
manifest=json.loads((root/'build-manifest.json').read_text())
out={'status':'eseguito_4K_confermato_P2P_non_risolto','collected_files_sha256_verified':len(actual),'checks_failed':0,'checks_missing':0,'GPU_identity':{'0':{'name':'RTX 2000 Ada','BDF':'0000:01:00.0','UUID':'GPU-00000000-0000-0000-0000-000000000001'},'1':{'name':'RTX A2000','BDF':'0000:06:00.0','UUID':'GPU-00000000-0000-0000-0000-000000000002'}},'parameter_observed':'UVM_PEER_SMALL_PAGES=Y','registry_override':'RM64KBBAR1Mappings=0','CCFG_before_and_after':{'D1':'00008077','D7F0':'00009077','D7F2':'00009077'},'software_mapping_chains':chains,'owner_checks':{'count':10,'pass':10},'peer_operations':d['data_operations'],'failures':3,'native_return_code':5,'cpu_postwrite':post,'pcie_changes':d['pcie_changes'],'data_done_monotonic':phase['data_done'],'context_exit_begin_monotonic':phase['context_exit_begin'],'clock_alignment':d['clock_alignment'],'kernel_errors':errors,'window_destroy_done_ids':[e['fields']['id'] for e in destroys],'xid_count':sum('Xid ' in x for x in k.splitlines()),'build_manifest_hashes':{x:manifest[x] for x in ['module_sha256','uvm_module_sha256','native_program_sha256','native_source_sha256','cpu_header_sha256']},'evidence_sha256':{'result.log':sha(root/'result.log'),'kernel.log':sha(root/'kernel.log'),'build-manifest.json':sha(root/'build-manifest.json'),'parser':sha(parser_path),'analyzer':sha(Path(__file__))},'limits':['Le 512 PTE per mapping sono il conteggio dichiarato; il log espone soltanto il primo raw PTE, non tutte le entry né il readback hardware.','Coerenza della catena software non dimostra il contenuto del TLP effettivamente emesso.','CPU postwrite e D2H concordano in questo collaudo; ciò non prova che ogni problema di visibilità sia escluso.','Moduli e binario sono identificati dal manifest raccolto; nessuna nuova lettura dei binari caricati da questo agente.','Analisi VT-d separata dell’agente audit; nessuna conclusione VT-d duplicata qui.']}
assert 'UVM_PEER_SMALL_PAGES=Y' in r and 'NATIVE_TEST_RC=5' in r and 'PROBE_COMPLETED' in r
(root/'verified-result.json').write_text(json.dumps(out,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({'status':out['status'],'chains':len(chains),'files_verified':len(actual),'first_cleanup_error_after_context_exit_ms':errors[0]['after_context_exit_ms']}))
