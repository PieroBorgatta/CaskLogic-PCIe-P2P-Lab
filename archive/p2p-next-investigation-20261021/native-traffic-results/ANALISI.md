> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# CaskLogic — prima misura NVML durante PUSH

**Protocollo completato, baseline non qualificata: RC 6.** I quattro confronti numerici confermano Ada→A2000 fallito e A2000→Ada riuscito con entrambe le modalità. Tutte le chiamate NVML restituiscono successo, ma i 200 ms di baseline producono soltanto 1–2 campioni quieti per endpoint/contatore, meno dei cinque richiesti. Nessuna delle quattro finestre è quindi dichiarata qualificata.

Le chiamate ai contatori sono seriali e durano circa 20 ms ciascuna, anziché quattro chiamate quasi istantanee per ciclo. L'analizzatore ricostruisce correttamente `qualified_windows=0`. Il seguito proposto aumenta soltanto la baseline a due secondi, senza ridurre le soglie e senza riscrivere i risultati di questa prova.

## Valori osservati, da confermare con baseline adeguata

Le medie seguenti usano solamente i campioni attivi completamente dentro la guardia temporale prevista, in KB/s NVML. Non sono velocità di payload consegnato.

| Fase | Direzione | Operazione richiesta | TX sorgente, KB/s | RX destinazione, KB/s | Dati |
|---|---|---|---:|---:|---|
| 1 | Ada → A2000 | SM | 1,597,753 | 292 | FAIL |
| 2 | Ada → A2000 | CUDA_COPY_REQUEST | 1,140,722 | 292 | FAIL |
| 3 | A2000 → Ada | SM | 4,553,890 | 4,107,393 | PASS |
| 4 | A2000 → Ada | CUDA_COPY_REQUEST | 4,085,442 | 4,133,558 | PASS |

Durante i due trasferimenti Ada→A2000 falliti, tutti i campioni RX A2000 attivi valgono 292 KB/s, come i pochi campioni di baseline. Contemporaneamente il TX Ada è molto superiore al valore quieto osservato. Nel verso riuscito entrambi gli endpoint mostrano un aumento consistente, coerente con la direzione attesa dei contatori. È un'asimmetria osservata nei contatori, da approfondire. Il controllo reverse calibra TX A2000 e RX Ada, ma **non calibra RX A2000**, il contatore decisivo nel verso fallito. Il suo codice di ritorno positivo non prova che risponda correttamente al payload di interesse. Prima di dedurre un blocco a monte dalla mancata crescita RX, serve un controllo positivo separato, per esempio H2D sostenuto verso la VRAM A2000. Anche la baseline troppo corta impedisce la qualificazione secondo il protocollo fissato.

NVML misura traffico PCIe aggregato, non singoli TLP, indirizzi, Requester ID o payload del test. L'indizio non localizza il punto di scarto fra PEG, TCSS e ASMedia. `CUDA_COPY_REQUEST` non significa CE osservato in questa prova, che non usa CUPTI. Le 64 copie/passaggi per batch sono richieste software; `submitted_payload_bytes` non è un contatore hardware di byte ricevuti.

## Integrità e ordinamento

Verificati 17 file raw contro `collected-sha256.json`. L'analizzatore indipendente conferma identità CUDA/NVML, quattro allocazioni VMM distinte, diritti source-only e destination-shared, proprietario fisico, esecutore sorgente, otto confronti completi dell'inizializzazione e quattro confronti del payload. Il sampler viene fermato e atteso prima della lettura D2H del proprietario. Tutti i buffer restano vivi fino all'ultimo confronto. La durata attiva delle quattro fasi è fra 1,21 e 1,26 s; il limite massimo non è raggiunto. L'insufficienza della baseline è la ragione della mancata qualificazione, non una chiamata NVML fallita.

I CCFG prima/dopo restano quelli originali: D1 `04008077`, D7 `0e009077`. Seguono `TRAFFIC_PROGRAM_END protocol_complete=1 comparisons=4 failures=2 qualified_windows=0 rc=6`, `PROBE_COMPLETED` e `SCRIPT_RC=6`. Nel kernel sono nuovamente presenti i quattro mapping IOVAS residui e gli otto assert, successivi a `context_exit_begin`; non sono stati riclassificati come errore che precede i confronti.

- `result.log` SHA256: `fba2c012e7364be8ef35002823e05158afa63818c53978e8acab688bf459a6e6`
- `kernel.log` SHA256: `d1f8ce2d9b9ff35a09c1260203ee9b3f97626d59bde7f9c7e7020cfd9ae2565d`
- Dettagli campione per campione: `independent-traffic-audit.json`.
- Ricostruzione e limiti: `verified-result.json`.

**P2P bidirezionale non risolto.** La seconda misura conserva lo stesso payload, gli stessi mapping e le stesse soglie; cambia soltanto il tempo disponibile per raccogliere una baseline adeguata.
