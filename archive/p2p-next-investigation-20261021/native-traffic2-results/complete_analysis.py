#!/usr/bin/env python3
import hashlib,json,sys
from pathlib import Path
R=Path(__file__).resolve().parent;sys.path.insert(0,str(R.parent/'native-traffic-probe'))
from analyze_traffic import audit,records
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
manifest=json.loads((R/'collected-sha256.json').read_text());assert len(manifest)==17
for n,h in manifest.items():assert sha(R/n)==h,n
j=audit((R/'result.log').read_text());assert j['qualified_windows']==4 and j['data_failures']==2 and j['raw_program_rc']==5
j.update(status='PROTOCOL_AND_SAMPLING_VERIFIED_DATA_FAILED',p2p_solved=False,collected_raw_hashes=manifest,uncalibrated_counter='A2000_RX: reverse PASS calibrates A2000_TX and Ada_RX only. Positive owner-H2D control is still needed before inferring no ingress from flat RX.',parser_sha256=sha(R.parent/'native-traffic-probe/analyze_traffic.py'))
(R/'verified-result.json').write_text(json.dumps(j,indent=2,ensure_ascii=False)+'\n')
rows=[]
for p in j['phases']:
 s=str(p['source']);d=str(p['destination']);tx=p['devices'][s]['TX'];rx=p['devices'][d]['RX'];rows.append(f"| {p['id']} | {'Ada → A2000' if s=='0' else 'A2000 → Ada'} | {p['engine_requested']} | {tx['active_interior']['mean_kBps']:,.0f} | {rx['active_interior']['mean_kBps']:,.0f} | {rx['baseline_quiet']['mean_kBps']:.1f} | {'PASS' if p['data_valid'] else 'FAIL'} |")
report='''# CaskLogic — Traffic2, baseline adeguata

**Quattro finestre qualificate, due payload falliti: RC 5.** L'unica modifica al programma precedente è la baseline da 200 a 2000 ms; header, soglie, allocazioni, payload, ordine e limiti restano invariati. Il parser precedente, senza modifiche, ricostruisce il risultato.

La baseline quieta ora contiene abbastanza campioni su tutti e quattro i contatori (TX/RX di entrambe le GPU). Le chiamate NVML hanno successo. Sono mantenute le guardie iniziali di 40 ms e almeno cinque campioni validi per ciascuna coppia endpoint/contatore nella baseline e nella finestra attiva.

| Fase | Direzione | Operazione richiesta | TX sorgente attivo, KB/s | RX destinazione attivo, KB/s | RX destinazione quieto, KB/s | Dati |
|---|---|---|---:|---:|---:|---|
'''+ '\n'.join(rows)+f'''

Il TX Ada aumenta durante le scritture fallite, mentre RX A2000 rimane vicino al valore quieto. Nella direzione funzionante aumentano sia TX A2000 sia RX Ada. **Questo controllo positivo non calibra RX A2000.** Il codice di ritorno NVML positivo non prova la sensibilità di tale contatore al payload in ingresso: prima di concludere che il traffico venga bloccato a monte serve un controllo positivo separato, ad esempio H2D sostenuto verso il proprietario A2000. Tale controllo usa RAM soltanto per verificare il contatore di una singola GPU e non costituisce un relay P2P.

NVML fornisce traffico PCIe aggregato: nessuna cattura TLP, indirizzo, Requester ID o punto di scarto viene osservata. Le richieste software per batch non sono byte hardware misurati. `CUDA_COPY_REQUEST` non viene etichettato CE osservato, perché questo programma non usa CUPTI. Questi risultati non sono una misura della velocità P2P utilizzabile quando il confronto dei dati fallisce.

L'audit indipendente verifica i 17 raw contro `collected-sha256.json`; identità CUDA/NVML, quattro allocazioni da 8 MiB, diritti source-only/destination-shared, otto confronti completi del contenuto inizializzato e quattro confronti del payload. Il sampler viene fermato e atteso prima di D2H/snapshot e tutti i buffer restano vivi fino all'ultimo confronto. La finestra attiva usa soltanto richieste GPU e interrogazioni di eventi nel percorso del sorgente revisionato; le copie host di preparazione e verifica sono esterne. Questa proprietà del programma non è una traccia del comportamento interno del driver.

- `result.log`: `{sha(R/'result.log')}`
- `kernel.log`: `{sha(R/'kernel.log')}`
- Ricostruzione per contatore: `independent-traffic-audit.json`.
- Esito e limiti: `verified-result.json`.

**P2P bidirezionale ancora non risolto.** Il nuovo discriminante previsto è l'emissione CE con indirizzi fisici ricavati da allocazioni vive del processo, senza fallback virtuale e senza payload inoltrato attraverso la RAM. Il controllo positivo dei contatori resterà distinto dai confronti P2P.
'''
(R/'ANALISI.md').write_text(report)
print(json.dumps({k:j[k] for k in ('status','data_failures','qualified_windows','raw_program_rc')},indent=2))
