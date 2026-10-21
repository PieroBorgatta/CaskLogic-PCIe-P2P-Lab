> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Snapshot VT-d in sola lettura

Il modulo osserva lo stato VT-d nel boot Linux RAM nativo della macchina già identificata. Non scrive GCMD, GSTS, PMEN, config PCI o altri registri; non modifica traduzione, protezioni DMA, bus mastering, driver o firmware. La costruzione/caricamento dell'immagine resta al coordinatore.

Il profilo è CPU 906a3 senza hypervisor. Acquisisce DMAR mediante `acpi_get_table`, copia la tabella e ne valida firma, lunghezza, checksum, record DRHD, scope, basi allineate e duplicati. Elenca tutti i DRHD, ma il percorso ACPI dereferenzia soltanto FED91000, se dichiarato in segmento0. Le altre unità dichiarate vengono segnalate come non campionate, non interpretate come disabilitate. Non segue RTADDR e non legge le tabelle di traduzione.

Per il controllo Thunderbolt aggiuntivo, attivo per default (`tcss=1`), richiede il PCI host 8086:4641 e MCHBAR64 esattamente 00000000fedc0001, entrambi già osservati sulla macchina. Mappa solo la pagina fedc7000 per leggere MCHBAR+7888,7890,7898,78a0. Il decoding è quello Alder Lake di coreboot, commit `0efe0567e794af09037e6c3841f5ea1885cd4112`: enable bit0 e base mask 7ffffff000. Lo stesso sorgente associa i quattro BAR ai root port D7:F0–3. Rilegge MCHBAR dopo l'acquisizione. Le copie e gli hash sono in `../reference/vtd-linux7/coreboot-sources.json`.

Non dereferenzia un BAR disabilitato; rifiuta FFFFFFFFFFFFFFFF, base zero, bit non documentati e basi fuori dall'apertura FED00000–FEDFFFFF di questo profilo. Questa restrizione è intenzionale e non è una regola generale della specifica VT-d. Con `tcss=0` legge soltanto il DRHD ACPI noto.

Per ogni unità campionata legge VER(00/32), CAP(08/64), ECAP(10/64), GSTS(1c/32) prima e dopo, RTADDR(20/64), FSTS(34/32), PMEN(64/32). Se CAP.PL(M)R bit5 è presente legge PLMBASE68/32 e PLMLIMIT6c/32; con CAP.PH(M)R bit6 legge PHMBASE70/64 e PHMLIMIT78/64. Le basi/limiti sono stampate raw. La decodifica di PMEN è qualificata da PMR_status_valid e dai bit di capability. Un PMEN non supportato o FFFFFFFF non dimostra protezione attiva/disattiva.

Gli accessi sono `readl`/`readq` allineati; su x86_64 `readq` è una lettura MMIO a64bit. GSTS deve essere uguale prima e dopo, altrimenti l'esito diagnostico fallisce. Ciò non rende atomica l'intera fotografia: i BAR TCSS non sono riletti dopo il loro snapshot, e RTADDR/PMEN/bounds vengono letti in sequenza. Non è previsto alcun writer concorrente nei due punti isolati del wrapper.

TES è il bit31 di GSTS. Il valore viene riportato direttamente, senza dedurlo dalla sola riga di comando `intel_iommu=off`. PMR è osservato separatamente dalla traduzione. Fonti Linux v7.0 e hash si trovano in `../reference/vtd-linux7/sources.json`; il kernel target esporta `acpi_get_table`, `acpi_put_table`, `ioremap`, `iounmap` e le API PCI usate.

Build CPU sul kernel target, dalla cartella contenente i tre input `cask_vtd_snapshot.c`, `dmar_parse.inc`, `Makefile`:

```sh
make -C /lib/modules/7.0.0-38-generic/build M="$PWD" W=1 KCFLAGS=-Werror modules
```

Il modulo non trattiene mappe MMIO dopo init ed è scaricabile. Il wrapper può caricarlo/scaricarlo prima di NVIDIA e ripetere dopo il test. Gli esiti normali sono `drhd_tcss_snapshot_ok` o `declared_drhd_snapshot_ok`; indicano una fotografia acquisita, non che TES o PMR siano disabilitati. Un errore diagnostico deve essere registrato separatamente, senza trasformarlo in fallimento del confronto CUDA. Conservare i log `CaskVTdRO` e, per la copia ACPI completa, `/sys/firmware/acpi/tables/DMAR`. Il log del modulo include al massimo i primi4096byte raw, con la lunghezza completa dichiarata.

159 fixture CPU della vera `dmar_parse.inc` passano con Clang `-std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined`. Coprono checksum, ogni troncamento della tabella minima, basi/scope/record invalidi, duplicati e limite dei record. Non sono una prova MMIO hardware. Due revisioni statiche indipendenti non hanno trovato difetti bloccanti. Nessun caricamento hardware è stato effettuato dal revisore.
