> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# CaskLogic — Traffic2, baseline adeguata

**Quattro finestre qualificate, due payload falliti: RC 5.** L'unica modifica al programma precedente è la baseline da 200 a 2000 ms; header, soglie, allocazioni, payload, ordine e limiti restano invariati. Il parser precedente, senza modifiche, ricostruisce il risultato.

La baseline quieta ora contiene abbastanza campioni su tutti e quattro i contatori (TX/RX di entrambe le GPU). Le chiamate NVML hanno successo. Sono mantenute le guardie iniziali di 40 ms e almeno cinque campioni validi per ciascuna coppia endpoint/contatore nella baseline e nella finestra attiva.

| Fase | Direzione | Operazione richiesta | TX sorgente attivo, KB/s | RX destinazione attivo, KB/s | RX destinazione quieto, KB/s | Dati |
|---|---|---|---:|---:|---:|---|
| 1 | Ada → A2000 | SM | 1,567,417 | 297 | 298.4 | FAIL |
| 2 | Ada → A2000 | CUDA_COPY_REQUEST | 1,144,963 | 292 | 294.2 | FAIL |
| 3 | A2000 → Ada | SM | 4,600,195 | 4,132,226 | 292.0 | PASS |
| 4 | A2000 → Ada | CUDA_COPY_REQUEST | 4,065,670 | 4,101,329 | 296.3 | PASS |

Il TX Ada aumenta durante le scritture fallite, mentre RX A2000 rimane vicino al valore quieto. Nella direzione funzionante aumentano sia TX A2000 sia RX Ada. **Questo controllo positivo non calibra RX A2000.** Il codice di ritorno NVML positivo non prova la sensibilità di tale contatore al payload in ingresso: prima di concludere che il traffico venga bloccato a monte serve un controllo positivo separato, ad esempio H2D sostenuto verso il proprietario A2000. Tale controllo usa RAM soltanto per verificare il contatore di una singola GPU e non costituisce un relay P2P.

NVML fornisce traffico PCIe aggregato: nessuna cattura TLP, indirizzo, Requester ID o punto di scarto viene osservata. Le richieste software per batch non sono byte hardware misurati. `CUDA_COPY_REQUEST` non viene etichettato CE osservato, perché questo programma non usa CUPTI. Questi risultati non sono una misura della velocità P2P utilizzabile quando il confronto dei dati fallisce.

L'audit indipendente verifica i 17 raw contro `collected-sha256.json`; identità CUDA/NVML, quattro allocazioni da 8 MiB, diritti source-only/destination-shared, otto confronti completi del contenuto inizializzato e quattro confronti del payload. Il sampler viene fermato e atteso prima di D2H/snapshot e tutti i buffer restano vivi fino all'ultimo confronto. La finestra attiva usa soltanto richieste GPU e interrogazioni di eventi nel percorso del sorgente revisionato; le copie host di preparazione e verifica sono esterne. Questa proprietà del programma non è una traccia del comportamento interno del driver.

- `result.log`: `686a3f2abf808c7b0dd5fa8c0e54ccdd7c1791887c2129dc8269d02ddf49ecdd`
- `kernel.log`: `0925d382ed9a583b731e11fcd741e5879a34d940ca2ff31a899e9057472ebf4a`
- Ricostruzione per contatore: `independent-traffic-audit.json`.
- Esito e limiti: `verified-result.json`.

**P2P bidirezionale ancora non risolto.** Il nuovo discriminante previsto è l'emissione CE con indirizzi fisici ricavati da allocazioni vive del processo, senza fallback virtuale e senza payload inoltrato attraverso la RAM. Il controllo positivo dei contatori resterà distinto dai confronti P2P.
