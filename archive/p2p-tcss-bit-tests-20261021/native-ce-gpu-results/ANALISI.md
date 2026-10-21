> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# CaskLogic — confronto nativo SM / Copy Engine con CUPTI

La prova ha completato tutti i **12 confronti**. **Ada→A2000 fallisce sia con il kernel SM sia con il Copy Engine, a 4 byte, 64 KiB e 1 MiB. A2000→Ada passa con entrambi i motori alle tre taglie.** CUPTI osserva effettivamente sei copie sul canale `ASYNC_MEMCPY`, oltre ai sei kernel SM: questa volta il motore non è dedotto dal nome dell'API CUDA. Il problema P2P bidirezionale resta irrisolto.

| Direzione | Dimensione | Kernel SM | Copy Engine osservato | Parole errate per ciascun trasferimento |
|---|---:|---|---|---:|
| Ada → A2000 | 4 B | FAIL | FAIL | 1 / 1 |
| Ada → A2000 | 64 KiB | FAIL | FAIL | 16.384 / 16.384 |
| Ada → A2000 | 1 MiB | FAIL | FAIL | 262.144 / 262.144 |
| A2000 → Ada | 4 B | PASS | PASS | 0 / 1 |
| A2000 → Ada | 64 KiB | PASS | PASS | 0 / 16.384 |
| A2000 → Ada | 1 MiB | PASS | PASS | 0 / 262.144 |

I 24 confronti completi eseguiti sulle GPU proprietarie prima dei trasferimenti sono tutti validi: sorgente inizializzata con il pattern atteso e destinazione con il suo complemento, entrambe sincronizzate. Per ogni coppia SM/CE sono identici allocazioni, VA, dimensione e pattern; i buffer restano vivi fino al termine di tutti i confronti. Nelle sei prove fallite tutte le parole differiscono dal pattern atteso e la prima parola registrata coincide ancora con il poison: `a56887da`, `b2046e0f`, `1d5b50fd`, rispettivamente. Il log non confronta nuovamente l'intero buffer con il poison, quindi non dimostra che ogni byte sia rimasto immutato.

Sono verificate 26 letture di identità GPU e 104 letture dei permessi VMM. GPU 0 è RTX 2000 Ada, `0000:01:00.0`, UUID `00000000000000000000000000000001`; GPU 1 è RTX A2000, `0000:06:00.0`, UUID `00000000000000000000000000000002`. I due buffer sorgente sono accessibili solo dalla rispettiva GPU proprietaria; i due buffer destinazione sono accessibili da entrambe. Le quattro allocazioni sono da 8 MiB con granularità di 2 MiB. La verifica VMM riguarda le proprietà e i permessi riportati dal driver; da sola non certifica il contenuto delle PTE hardware.

Per Ada→A2000 le callback riportano sempre `src=796e04e00000`, `dst=402800000`, contesto 1 e stream `0x609231f42f40` (CUPTI stream ID 14). Per A2000→Ada riportano sempre `src=402000000`, `dst=796e05600000`, contesto 2 e stream `0x609232e1c020` (CUPTI stream ID 23). L'esecutore delle copie coincide con la GPU sorgente. Ogni chiamata DtoD ha una callback di entrata e uscita con gli stessi VA/byte/stream, ritorno CUDA 0, un record Driver API `cbid=281` e un record PtoP della medesima correlazione.

| Caso CE | Correlation ID | Sorgente → destinazione CUPTI | Byte attività | Context / stream ID | Channel / type |
|---:|---:|---|---:|---|---|
| 2 | 802 | 0 → 1 | 4 | 1 / 14 | 14 / 2 |
| 4 | 905 | 0 → 1 | 65.536 | 1 / 14 | 14 / 2 |
| 6 | 1008 | 0 → 1 | 1.048.576 | 1 / 14 | 14 / 2 |
| 8 | 1111 | 1 → 0 | 4 | 2 / 23 | 14 / 2 |
| 10 | 1214 | 1 → 0 | 65.536 | 2 / 23 | 14 / 2 |
| 12 | 1317 | 1 → 0 | 1.048.576 | 2 / 23 | 14 / 2 |

Tutti i sei record CE sono `MEMCPY2` (kind 22), `PTOP` (copy kind 10), memoria DEVICE→DEVICE (3→3), `channel_type=2` (`ASYNC_MEMCPY`), senza kernel associato. I sei casi SM contengono ciascuno un `peer_push_kernel` sul canale di calcolo e nessuna copia associata. Il confronto indipendente ha ricostruito le associazioni tramite callback ed external correlation, controllando byte, dispositivo, contesto, stream e intervallo temporale CUPTI: sei CE osservati, sei SM osservati, zero attività non attribuite nelle finestre, zero record persi, zero errori della traccia.

Sono presenti anche **60 attività di copia host fuori dalle finestre dei trasferimenti**, usate per inizializzare e verificare gli owner. `host_copies=0` si riferisce ai dodici casi osservati, non all'intero programma. Nel codice la CPU non inoltra il payload da una GPU all'altra. CUPTI però non espone i descrittori hardware finali del CE, gli indirizzi fisici dei TLP o necessariamente ogni dettaglio interno del driver: il report mantiene quindi `direct_route_proven=false`, anche per i trasferimenti riusciti. I VA provengono dalle callback correlate, non dai record di attività che ne sono privi.

Il programma termina con `protocol_complete=1`, `comparisons=12`, `failures=6`, `trace_complete=1`, `ce_observed=6`, `sm_observed=6`, `dropped=0`, `trace_errors=0`, **RC 5**. Anche wrapper e `NATIVE_TEST_RC` riportano 5; `PROBE_COMPLETED` è presente. CCFG è rilevato prima del driver, dopo il driver e dopo il programma: D1 `00008077`, D7:F0 e D7:F2 `00009077`, sempre invariati. Il parametro effettivo è `RM64KBBAR1Mappings=0`, con RM/UVM di baseline non coerente; non si tratta della variante SYS_COH.

L'audit indipendente delle catene nonce→VA→RM→UVM ricostruisce due sole finestre peer, entrambe destinate alla ricezione, da 8 MiB: Ada a `4000400000`, A2000 a `4600400000`. Le tracce RM/UVM concordano, con pagine da 2 MiB, quattro PTE da 16 byte per mapping, aperture 3, `readonly=0`, indirizzi allineati. La strumentazione conserva il primo PTE; tutte le taglie provate, al massimo 1 MiB, ricadono interamente in quella pagina. L'uguaglianza delle tracce software non equivale a una rilettura delle PTE hardware.

I **150 snapshot PCI** hanno letture valide e nessuna variazione dei campi registrati rispetto al baseline, compresi PCI status e AER. Questa prova contiene esclusivamente trasferimenti di scrittura: non riproduce il nuovo RMA visto nelle prove di lettura precedenti. Non sono presenti Xid. L'assenza di variazioni non esclude rifiuti o perdite di transazioni non segnalati nei registri letti.

La liberazione inizia dopo `data_done`, a monotonic `13.839001765`; tutti e quattro i buffer vengono liberati, entrambe le finestre raggiungono `WINDOW_DESTROY_DONE` e `cleanup_done` precede `context_exit_begin`. Restano quattro mapping IOVAS residui, segnalati 369,011 ms dopo il marker di uscita nel medesimo log kernel, e otto assert di distruzione, il primo a 384,607 ms. Sono un difetto di cleanup successivo a tutti i confronti; non sono stati usati come spiegazione dimostrata del fallimento dei trasferimenti. L'audit `independent-mapping-lifetime-review-storico.json`, SHA `56939c5fa81bccde991d78aa7d024528615fbcdf45d578d22acad7a55e235937`, è incorporato integralmente nel JSON principale.

Sono stati ricalcolati e confrontati gli hash di **17 reperti raccolti** e di tutti i **50 input di build**, compresi sorgente, header CUPTI, librerie e binario. Il manifest di build conserva il campo storico `built_not_booted=true`, scritto prima dell'avvio: l'esecuzione è provata dai log completi, non da quel campo.

- `result.log`: `b903e87590f3fd769a978838d4e8b2705a1d53893444027b2e84de6f5714f4c4`
- `kernel.log`: `5e71c958311705404135094682b2d8eec708b95edeacabb8c3ea385337b06357`
- initrd eseguito: `2f912fcfca5f69616b4f18159e777b28b60023ebe4e24d3e53a9d4ff7193fd72`
- binario: `7184d44dc039f662b21c86b1f20e644b21a3188bb7c028a8a0b12084bcdcfa4d`
- sorgente: `89f1639244b589ef89dfb3231c84b278b5c8caedef5c74e9d76d5a16da3d309c`
- header traccia: `0de1f3097fbe22c775d4c603615cfd9f0a69c328e9e7da55d50389e60ed5b468`
- CUPTI effettivo: `76dcad94420820ea9aee9094c346cc34c6cb1ff630cef9b14e04db298a86305d`

Questo è un collaudo di correttezza e osservazione del motore. Non è un benchmark. La prova esclude che passare al CE tramite questa API, con questi mapping e driver, risolva la scrittura Ada→A2000; non dimostra che ogni possibile programmazione CE o modifica firmware abbia necessariamente lo stesso esito.
