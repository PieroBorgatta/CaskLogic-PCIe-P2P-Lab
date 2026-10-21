> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Prova nativa NoSnoop / Relaxed Ordering

**La modifica dei due bit PCIe non cambia il risultato: tre confronti falliscono su quattro in ciascuna delle cinque fasi.** Le quattro allocazioni e le finestre BAR1 restano le stesse dall'inizio alla fine; non sono ricreate fra le fasi. Il programma CUDA termina correttamente il protocollo e ripristina i registri. Successivamente il validatore del wrapper produce un falso negativo, riprodotto senza usare le GPU.

| Fase | DEVCTL Ada | DEVCTL A2000 | Lettura Ada→A2000 | Lettura A2000→Ada | Scrittura A2000→Ada | Scrittura Ada→A2000 |
|---|---:|---:|---|---|---|---|
| Baseline iniziale | 2930 | 2910 | FAIL | FAIL | PASS | FAIL |
| NoSnoop/RO spenti sulla Ada | 2120 | 2910 | FAIL | FAIL | PASS | FAIL |
| Baseline ripristinata | 2930 | 2910 | FAIL | FAIL | PASS | FAIL |
| NoSnoop/RO spenti su entrambe | 2120 | 2100 | FAIL | FAIL | PASS | FAIL |
| Baseline finale | 2930 | 2910 | FAIL | FAIL | PASS | FAIL |

Le frecce nelle colonne lettura indicano owner della sorgente→GPU che legge. Le due letture restituiscono `edcba987` dopo XOR, equivalente a una parola remota `ffffffff`; era atteso `12346641`. La scrittura verso Ada restituisce `a5a42468`, quella verso A2000 restituisce zero. Totale: 15 fallimenti su 20 confronti.

## Controlli indipendenti

`analyze_nosnoop.py` ricostruisce i risultati dai record individuali, verifica i 17 hash dei file raccolti e gli hash del pacchetto realmente armato. Legge direttamente l'initramfs gzip/newc e verifica driver RM, UVM, programma CUDA, libcuda, init e BusyBox contro il manifest.

- **282 letture DEVCTL** coerenti con il valore richiesto, prima e dopo ciascuna operazione; nessun Transactions Pending osservato.
- **Sei scritture a 16 bit**, tutte all'offset `0x80`, modifica esclusiva della maschera `0x0810`. Otto record di ripristino validi; valori originali presenti nella baseline finale e nel controllo prima del cleanup.
- **Quattro sole finestre**, tutte da 2 MiB e allineate: Ada `4000400000` / `4000600000`; A2000 `4600400000` / `4600600000`. Verificate catene nonce→GPU VA→handle/descriptor→window→DMA→PTE RM/UVM→submit/complete; nessuna distruzione fino al completamento dei venti confronti.
- **60 controlli locali owner validi**, 20 letture CPU dei due pattern valide, dieci controlli BAR1 completi. Dopo ciascuna scrittura peer, la CPU osserva la stessa parola della successiva lettura owner: Ada PASS, A2000 zero, nessuno SKIP.
- **606 snapshot PCIe**, su sei funzioni. Alla prima lettura in ogni direzione compare Received Master Abort (`PCI_STATUS 0010→2010`) sulla GPU richiedente e sul relativo root port. Nessuna variazione AER: questo non significa percorso PCIe privo di errori. RMA è persistente e non viene azzerato dal test.

I messaggi IOVAS/asserzioni iniziano a 14,570944 s, **359,815 ms dopo** il marker di uscita del contesto e dopo tutti i confronti. Restano difetti reali di cleanup; il loro ritardo non certifica ogni operazione precedente del driver.

## Falso negativo del validatore

Il log originale resta immutato: `NATIVE_TEST_RC=5`, `ATTR_PROGRAM_END protocol_complete=1 restored=1 rc=5`, poi **`SCRIPT_RC=23`**. Non contiene `PROBE_COMPLETED` e il controllo CCFG successivo al test non è stato eseguito. I valori D1=`00008077`, D7F0/F2=`00009077` sono verificati prima e dopo il caricamento del driver, non alla fine di questa prova.

La riproduzione CPU eseguita dal coordinatore usa esattamente il BusyBox incorporato nell'initramfs (`df12634c17fcdca839ae5dc47d7627b7558511f7645de7c99ccf097a0f28ed5b`) e il log acquisito. Il gate originale fallisce al primo `ATTR_PHASE_BEGIN index=0`, con contatori `n`/`begun` non inizializzati. Inizializzando esclusivamente `n=0;begun=0` nel blocco BEGIN, lo stesso gate passa sullo stesso log. Predicate e dati restano invariati. Evidenza in `busybox-gate-reproduction.json`; corrispondenza del binario e diff del gate verificati nell'analisi indipendente. Non è stata necessaria una ripetizione hardware per questa diagnosi.

## Limiti della conclusione

Il risultato esclude un miglioramento con questi due permessi PCIe disabilitati nella configurazione provata. Non equivale a catturare gli attributi effettivi dei TLP e non dimostra dove la transazione venga scartata. NoSnoop e Relaxed Ordering sono stati modificati insieme. I PTE sono verificati tramite log software, senza rilettura delle tabelle hardware. I controlli CPU BAR1 non certificano l'instradamento di richieste originate dalla GPU. Il P2P resta irrisolto.

Hash dei log: `result.log` **b60182ce923b8a4857c574b8768371b0fc20cd976b508341d66688d0febac4a7**; `kernel.log` **e7f47d8c2ef070d923a2c60c018cb6da8deaeebbb48be5684ab5e378ee9f0237**. Dati completi, hash e limiti in `verified-result.json`.
