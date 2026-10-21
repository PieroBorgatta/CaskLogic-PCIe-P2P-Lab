> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# CaskLogic — confronto nativo PUSH/PULL con CE e SM

Il nuovo percorso PULL non risolve: **18 confronti falliti su 24**, con protocollo completato e traccia CUPTI completa. Funziona soltanto PUSH A2000 → Ada. Anche il primo PULL, eseguito dal copy engine della A2000 prima di qualsiasi lettura peer SM del programma, fallisce.

| Percorso | Esecutore | SM | CE osservato | Taglie |
|---|---|---:|---:|---|
| PUSH Ada → A2000 | Ada | 0/3 PASS | 0/3 PASS | 4 B, 64 KiB, 1 MiB |
| PUSH A2000 → Ada | A2000 | 3/3 PASS | 3/3 PASS | 4 B, 64 KiB, 1 MiB |
| PULL Ada → A2000 | A2000 | 0/3 PASS | 0/3 PASS | 4 B, 64 KiB, 1 MiB |
| PULL A2000 → Ada | Ada | 0/3 PASS | 0/3 PASS | 4 B, 64 KiB, 1 MiB |

Sono confrontate tutte le parole di ogni payload. Nei sei PUSH falliti la prima parola conserva il poison iniziale, complemento dell'atteso; tutte le parole differiscono dall'atteso. Nei dodici PULL falliti tutte le parole differiscono dall'atteso e la prima è `ffffffff`. Il log non stampa tutte le parole: non estendiamo il valore della prima parola all'intero buffer.

## Nuovo discriminante effettivamente eseguito

Il caso 13 è PULL Ada → A2000, 4 byte, esecutore A2000. CUPTI collega la chiamata DtoD agli stessi indirizzi `403000000 → 404800000`, correlation `1412`, activity PtoP tipo 22, device 1/context 2/stream 23, channel 10/type 2 (copy engine), sorgente device 0 e destinazione device 1. La prima parola letta dalla destinazione è `ffffffff` anziché `5a977825`. Questo caso precede ogni lettura peer SM: non dipende da un precedente errore del kernel di lettura nella stessa esecuzione.

Gli otto buffer VMM sono distinti e creati prima dei casi. In PUSH, la sorgente è accessibile soltanto al suo proprietario e la destinazione a entrambe le GPU; in PULL, la sorgente è condivisa e la destinazione accessibile soltanto al proprietario. Di conseguenza un solo dispositivo può accedere a entrambi gli operandi. In PULL il permesso remoto della sorgente è RW, non R. I controlli di contesto e stream confermano l'esecutore richiesto.

## Verifiche indipendenti sui log

L'analizzatore ricostruisce correlazioni, indirizzi, byte, dispositivi, contesto, stream e intervalli CUPTI. Confermati **12 attività CE e 12 kernel SM**, un'attività di payload per caso, nessuna copia host attribuita ai casi, nessuna attività senza correlazione nei loro intervalli, `dropped=0`, `trace_errors=0`. Le 120 attività host osservate restano fuori dai casi e servono alle inizializzazioni e ai confronti. Questo non è una cattura dei descrittori hardware e non certifica l'assenza di qualsiasi staging interno non esposto da CUPTI: `direct_route_proven=0` resta esplicito.

Passano 48 controlli completi di inizializzazione del proprietario, 50 verifiche di identità GPU e 208 verifiche degli accessi VMM. Tutti gli otto rilasci iniziano dopo `data_done=14.083957633`; il primo è a `14.086142610`. L'audit indipendente delle catene RM/UVM/PTE è completato: quattro catene univoche nonce/VA, indirizzi allineati a 2 MiB e prime PTE coerenti. Tutti i payload ricadono nella prima pagina loggata. Sono log software, non una rilettura della MMU hardware. Vedi `ANALISI-MAPPING-FIRMWARE.md` e il JSON collegato.

Nei 294 snapshot PCIe cambiano soltanto quattro `PCI_STATUS 0010→2010` (Received Master Abort): root D7 e A2000 nel primo CE PULL, caso 13; root D1 e Ada nel primo CE PULL inverso, caso 19. Nessuna nuova variazione AER. Il bit è sticky: stabilità successiva non esclude nuovi errori. Non va descritto il PCIe come privo di errori. Gli avvisi di quattro mapping IOVAS residui e otto assert arrivano dopo il cleanup, il primo oltre 360 ms dopo `context_exit_begin`; zero Xid. Non precedono né invalidano per questo motivo i confronti già completati. I timestamp del prefisso kernel sono distinti dai marker CLOCK_MONOTONIC esplicitamente stampati dal programma.

Il firmware di questa prova conserva i valori originali prima e dopo il programma: PEG `04008077`, TCSS D7:F0 e D7:F2 `0e009077`. `CE_PROGRAM_END` dichiara `protocol_complete=1`, `trace_complete=1`, `rc=5`; seguono `PROBE_COMPLETED` e `SCRIPT_RC=5`. Il codice 5 indica i fallimenti numerici misurati, non un protocollo interrotto.

## Evidenze e limiti della raccolta

Aggiornamento della raccolta: **17 raw verificati localmente** contro tutti gli hash di `preliminary-collected-manifest.json`. Il confronto col server è riportato dal coordinatore; questa analisi esegue solo il confronto locale. Backup ESP e cleanup sono gestiti separatamente. I due log principali:

- `result.log`: `125d4a9b0be44bfb6f5b8c38fbf7c8d6a6de8a7b8aa3193e5e13f5b5976786e0`
- `kernel.log`: `de7f039113f37f81898ca6ac61f1a70f16e10a98577983bb5b8e8b597a46cdd8`
- Analizzatore: `../native-pushpull-probe/analyze_ce.py`, SHA `9cbb58cba5b644c9558b3aebf0e537be8e3087c4033f2eba143ce4c8b3b724c2`.
- Dettagli ricostruiti: `cupti-independent-log-audit.json` e `verified-result.json`.

**P2P bidirezionale ancora non risolto.** Il cambio di esecutore al copy engine della destinazione non ha aggirato il problema. Un successivo campionamento TX/RX potrà distinguere attività osservata sui due endpoint durante scritture prolungate; i contatori aggregati non identificano da soli il punto di scarto né i singoli TLP.
