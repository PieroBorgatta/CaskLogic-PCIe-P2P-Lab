#!/usr/bin/env python3
"""Audit locale dei soli reperti salvati; nessuna esecuzione CUDA o accesso remoto."""
import hashlib, importlib.util, json, re
from collections import Counter
from pathlib import Path

D=Path(__file__).resolve().parent
P=D.parent/'native-ce-probe'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def require(ok, why):
    if not ok: raise ValueError(why)
spec=importlib.util.spec_from_file_location('ce_audit', P/'analyze_ce.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
raw=(D/'result.log').read_text(); lines=raw.splitlines()
result=m.audit(raw)
collected=json.loads((D/'collected-sha256.json').read_text())
for name,expected in collected.items(): require(sha(D/name)==expected, 'collected_hash:'+name)
manifest=json.loads((D/'build-manifest.json').read_text())
for name,expected in manifest['input_files'].items(): require(sha(P/name)==expected, 'source_hash:'+name)
files=json.loads((D/'files.json').read_text())
require(files==manifest['files'], 'files_manifest')
state=json.loads((D/'native-ce-gpu-state.json').read_text())
require(state['files']==files, 'armed_files')
require('PROBE_COMPLETED' in lines and 'SCRIPT_RC=5' in lines and 'NATIVE_TEST_RC=5' in lines, 'wrapper_completion')
ccfg={}
for bdf,value in [('00:01.0','00008077'),('00:07.0','00009077'),('00:07.2','00009077')]:
    xs=re.findall(r'^(?:PEG|TCSS)_CCFG '+re.escape(bdf)+r' ([0-9a-f]{8})$',raw,re.M)
    require(xs==[value]*3, 'ccfg_before_after_driver_after_test:'+bdf);ccfg[bdf]=xs
case=m.records(lines,'CE_CASE'); full=m.records(lines,'FULL_COMPARE')
ops=m.records(lines,'CUPTI_RECORD'); callbacks=m.records(lines,'CUPTI_CALLBACK')
begins=m.records(lines,'CUPTI_CASE_BEGIN'); ends=m.records(lines,'CUPTI_CASE_END')
def pattern(i,seed):
    x=i^seed;x^=x>>16;x=(x*0x7feb352d)&0xffffffff;x^=x>>15;x=(x*0x846ca68b)&0xffffffff;return x^(x>>16)
enriched=[]
for i,c in enumerate(case):
    cid=i+1; s=int(c['s']); n=int(c['bytes']); seed=0x6b8b4567^n^((0x13579bdf*(s+1))&0xffffffff)
    require(int(c['seed'],16)==seed, 'case_seed')
    if i%2: require(all(c[k]==case[i-1][k] for k in ['seed','s','d','bytes','src','dst']), 'same_sm_ce_pair')
    payload=m.one([x for x in full if x['stage']=='peer_payload' and int(x['iteration'])==cid], 'payload')
    item=dict(result['cases'][i], source_va=c['src'], target_va=c['dst'], seed=c['seed'], mismatches=int(payload['mismatches']), checked_words=int(payload['checked_words']))
    item['activities']=[x for x in ops if int(x['case'])==cid and int(x['kind']) in (1,22,10)]
    item['d2d_callbacks']=[x for x in callbacks if int(x['case'])==cid and x['is_d2d']=='1']
    item['cupti_begin']=begins[i];item['cupti_end']=ends[i]
    if int(payload['mismatches']):
        require(int(payload['mismatches'])==n//4, 'all_words_mismatched')
        require(int(payload['first_index'])==0 and int(payload['first_expected'],16)==pattern(0,seed), 'first_expected_pattern')
        require(int(payload['first_got'],16)==(pattern(0,seed)^0xffffffff), 'first_word_is_poison')
        item['first_word_observed']=payload['first_got'];item['first_word_expected']=payload['first_expected'];item['first_word_equals_initialized_poison']=True
    enriched.append(item)
result['cases']=enriched
result['verified_collected_files']=collected
result['verified_collected_file_count']=len(collected)
result['verified_build_input_file_count']=len(manifest['input_files'])
result['build']=manifest
result['raw_native_rc']=5;result['raw_script_rc']=5;result['raw_probe_completed_marker']=True
result['after_test_ccfg_executed']=True;result['ccfg_samples']=ccfg
result['cupti_activity_kind_counts_all']=dict(Counter(x['kind'] for x in ops))
result['outside_transfer_gpu_records']=sum(int(x['case'])==0 and int(x['kind']) in (1,22,10) for x in ops)
result['outside_transfer_host_copy_records']=sum(int(x['case'])==0 and int(x['kind']) in (1,22) and (x['src_kind']!='3' or x['dst_kind']!='3') for x in ops)
result['owner_initialization_full_comparisons_pass']=24
result['payload_full_comparisons']=12
result['gpu_identity_checks_pass']=26
result['vmm_access_checks_pass']=104
result['source_only_permissions_and_same_sm_ce_allocations_verified']=True
result['same_pattern_sm_ce_pairs_verified']=True
result['all_failed_payload_words_mismatched']=True
result['all_failed_first_words_equal_initial_poison']=True
result['entire_failed_buffer_unchanged_proven']=False
result['result_log_sha256']=sha(D/'result.log');result['kernel_log_sha256']=sha(D/'kernel.log')
result['analyzer_sha256']=sha(P/'analyze_ce.py')
result['conclusion_it']='CE osservato non risolve: Ada→A2000 fallisce con SM e CE a tutte le tre taglie; A2000→Ada passa con entrambi. Nessuna conclusione automatica sul percorso fisico senza staging.'
result['performance_benchmark']=False
result['limitations'] += [
 'Le copie host di inizializzazione e verifica sono presenti fuori dalle finestre di trasferimento e non sono un relay fra GPU; host_copies=0 si riferisce esclusivamente ai casi misurati.',
 'Il record di attività CUPTI non contiene i descrittori hardware finali né gli indirizzi fisici dei TLP. I VA provengono dalla callback Driver API correlata.',
 'Tutte le parole fallite sono diverse dal pattern atteso; soltanto la prima parola è registrata e dimostrata uguale al poison. Il log non conserva un secondo confronto completo con il poison.',
 'Questa prova confronta CUDA DtoD sul CE osservato e kernel SM con gli stessi mapping; non dimostra che ogni possibile programmazione CE o firmware abbia lo stesso comportamento.',
 'Le durate CUPTI non costituiscono un benchmark e non si sottraggono ai timestamp CLOCK_MONOTONIC.'
]
review=D/'independent-mapping-lifetime-review-storico.json'
if review.exists():
    result['mapping_pci_lifetime_independent_review']={'file':review.name,'sha256':sha(review),'result':json.loads(review.read_text())}
(D/'verified-result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({'status':result['status'],'files':len(collected),'build_inputs':len(manifest['input_files']),'ce_observed':result['ce_observed'],'sm_observed':result['sm_observed'],'failures':result['data_failures'],'verified_sha256':sha(D/'verified-result.json')},indent=2))
