#!/usr/bin/env python3
import hashlib,json,sys,re
from pathlib import Path
R=Path(__file__).resolve().parent;sys.path.insert(0,str(R.parent/'native-traffic-probe'))
from analyze_traffic import audit,records
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
manifest=json.loads((R/'collected-sha256.json').read_text());assert len(manifest)==17
for n,h in manifest.items():assert sha(R/n)==h,n
text=(R/'result.log').read_text();j=audit(text);j['collected_raw_hashes']=manifest
j['status']='PROTOCOL_VERIFIED_DATA_FAILED_BASELINE_NOT_QUALIFIED';j['p2p_solved']=False
j['uncalibrated_counter']='A2000_RX: reverse PASS calibrates A2000_TX and Ada_RX only; successful NVML return does not prove A2000_RX payload sensitivity.'
j['qualification_reason']='Ogni baseline quieta ha soltanto 1–2 campioni per endpoint/counter, meno dei5 richiesti. Le finestre attive hanno10–14 campioni per endpoint/counter.'
samples=records(text.splitlines(),'NVML_SAMPLE');assert all(x['rc']=='0' and x['valid']=='1' for x in samples)
lat=[int(x['end_ns'])-int(x['begin_ns']) for x in samples]
j['nvml_call_durations_ns']={'min':min(lat),'max':max(lat),'mean':sum(lat)/len(lat),'calls':len(lat)}
assert j['qualified_windows']==0 and j['data_failures']==2 and j['raw_program_rc']==6
j['raw_program_completed']='PROBE_COMPLETED' in text.splitlines();j['parser_sha256']=sha(R.parent/'native-traffic-probe/analyze_traffic.py')
(R/'verified-result.json').write_text(json.dumps(j,indent=2,ensure_ascii=False)+'\n')
rows=[]
for p in j['phases']:
 s=str(p['source']);d=str(p['destination']);tx=p['devices'][s]['TX'];rx=p['devices'][d]['RX']
 rows.append(f"| {p['id']} | {'Ada → A2000' if s=='0' else 'A2000 → Ada'} | {p['engine_requested']} | {tx['active_interior']['mean_kBps']:,.0f} | {rx['active_interior']['mean_kBps']:,.0f} | {'PASS' if p['data_valid'] else 'FAIL'} |")
report='''# CaskLogic — prima misura NVML durante PUSH

**Protocollo completato, baseline non qualificata: RC 6.** I quattro confronti numerici confermano Ada→A2000 fallito e A2000→Ada riuscito con entrambe le modalità. Tutte le chiamate NVML restituiscono successo, ma i 200 ms di baseline producono soltanto 1–2 campioni quieti per endpoint/contatore, meno dei cinque richiesti. Nessuna delle quattro finestre è quindi dichiarata qualificata.

Le chiamate ai contatori sono seriali e durano circa 20 ms ciascuna, anziché quattro chiamate quasi istantanee per ciclo. L'analizzatore ricostruisce correttamente `qualified_windows=0`. Il seguito proposto aumenta soltanto la baseline a due secondi, senza ridurre le soglie e senza riscrivere i risultati di questa prova.

## Valori osservati, da confermare con baseline adeguata

Le medie seguenti usano solamente i campioni attivi completamente dentro la guardia temporale prevista, in KB/s NVML. Non sono velocità di payload consegnato.

| Fase | Direzione | Operazione richiesta | TX sorgente, KB/s | RX destinazione, KB/s | Dati |
|---|---|---|---:|---:|---|
'''+ '\n'.join(rows)+f'''

Durante i due trasferimenti Ada→A2000 falliti, tutti i campioni RX A2000 attivi valgono 292 KB/s, come i pochi campioni di baseline. Contemporaneamente il TX Ada è molto superiore al valore quieto osservato. Nel verso riuscito entrambi gli endpoint mostrano un aumento consistente, coerente con la direzione attesa dei contatori. È un'asimmetria osservata nei contatori, da approfondire. Il controllo reverse calibra TX A2000 e RX Ada, ma **non calibra RX A2000**, il contatore decisivo nel verso fallito. Il suo codice di ritorno positivo non prova che risponda correttamente al payload di interesse. Prima di dedurre un blocco a monte dalla mancata crescita RX, serve un controllo positivo separato, per esempio H2D sostenuto verso la VRAM A2000. Anche la baseline troppo corta impedisce la qualificazione secondo il protocollo fissato.

NVML misura traffico PCIe aggregato, non singoli TLP, indirizzi, Requester ID o payload del test. L'indizio non localizza il punto di scarto fra PEG, TCSS e ASMedia. `CUDA_COPY_REQUEST` non significa CE osservato in questa prova, che non usa CUPTI. Le 64 copie/passaggi per batch sono richieste software; `submitted_payload_bytes` non è un contatore hardware di byte ricevuti.

## Integrità e ordinamento

Verificati 17 file raw contro `collected-sha256.json`. L'analizzatore indipendente conferma identità CUDA/NVML, quattro allocazioni VMM distinte, diritti source-only e destination-shared, proprietario fisico, esecutore sorgente, otto confronti completi dell'inizializzazione e quattro confronti del payload. Il sampler viene fermato e atteso prima della lettura D2H del proprietario. Tutti i buffer restano vivi fino all'ultimo confronto. La durata attiva delle quattro fasi è fra 1,21 e 1,26 s; il limite massimo non è raggiunto. L'insufficienza della baseline è la ragione della mancata qualificazione, non una chiamata NVML fallita.

I CCFG prima/dopo restano quelli originali: D1 `04008077`, D7 `0e009077`. Seguono `TRAFFIC_PROGRAM_END protocol_complete=1 comparisons=4 failures=2 qualified_windows=0 rc=6`, `PROBE_COMPLETED` e `SCRIPT_RC=6`. Nel kernel sono nuovamente presenti i quattro mapping IOVAS residui e gli otto assert, successivi a `context_exit_begin`; non sono stati riclassificati come errore che precede i confronti.

- `result.log` SHA256: `{sha(R/'result.log')}`
- `kernel.log` SHA256: `{sha(R/'kernel.log')}`
- Dettagli campione per campione: `independent-traffic-audit.json`.
- Ricostruzione e limiti: `verified-result.json`.

**P2P bidirezionale non risolto.** La seconda misura conserva lo stesso payload, gli stessi mapping e le stesse soglie; cambia soltanto il tempo disponibile per raccogliere una baseline adeguata.
'''
(R/'ANALISI.md').write_text(report)
print(json.dumps({k:j[k] for k in ('status','comparisons','data_failures','qualified_windows','raw_program_rc')},indent=2))
