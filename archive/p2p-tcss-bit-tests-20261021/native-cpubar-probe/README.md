> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Candidato diagnostico CPU BAR1 in sola lettura

Preparato localmente il 21 ottobre 2026, senza compilazione NVCC, accesso remoto o operazione hardware. La base `../native-instrumented2-probe/peer_vmm_word_sync.cu` è rimasta invariata, SHA256 `ee49e48897817534281741bcf8131a5b0123812636834ae60d5ca8f437826cb3`.

## Contenuto

- `peer_vmm_word_cpubar.cu`: i quattro confronti CUDA originali, preceduti da un controllo CPU separato per ciascuna allocazione sorgente. Le quattro deallocazioni restano differite. `CPUBAR_SUMMARY` distingue pass/fail/skip dai risultati P2P; il codice di uscita P2P rimane quello originale.
- `cpubar_trace.h`: parser della correlazione, identità dei dispositivi e mapping BAR1 in sola lettura.
- `pcie_diag.h`: copia identica del diagnostico PCIe esistente.
- `test_cpubar_trace.cpp` e `fixtures/`: test locali del parser, senza accesso hardware.

Il candidato non include installazione di moduli, preparazione initrd, riavvio o regolazioni BAR/firmware. Può essere integrato in una successiva prova solo dopo revisione e compilazione Linux. Non modificare una prova già in corso.

## Vincoli del controllo

Ogni allocazione riceve un nonce nuovo da `/proc/sys/kernel/random/uuid` e due marcatori nel log del kernel, prima di cuMemCreate e dopo cuMemSetAccess. Il runtime non apre file log salvati: legge il buffer corrente con klogctl READ_ALL, senza cancellarlo. Il nonce e la finestra fra i marcatori impediscono di riutilizzare una precedente associazione. Il probe registra GPU VA, dimensione e identità CUDA; la catena deve essere univoca:

GPU VA/UUID richiedente → handle RM UVM → RM_REQUEST descriptor → WINDOW_CREATE ID → DMA_MAP BDF → RM_PTE/UVM_PTE uguali → submission e completamento riusciti.

La completion viene associata alla submission selezionata prima del mapping successivo sulla stessa VA. È necessario perché i log reali contengono completion separate del proprietario e del richiedente. Descriptor indisponibile, righe troncate, duplicati, offset diverso da zero, status non nullo o evento di distruzione fanno saltare la diagnosi.

La BAR viene verificata contro `resource` dello stesso BDF e l'UUID CUDA contro `/proc/driver/nvidia/gpus/<BDF>/information`. Le identità e il mapping vengono ricontrollati prima di ciascuna lettura. Si apre soltanto `resource1` con O_RDONLY e si mappa una pagina con PROT_READ; nessun percorso `/dev/mem`, suffisso `_wc`, write PCI config, reset o scrittura alla BAR. L'unico accesso MMIO è un load volatile uint32_t all'offset esatto della word allocata. SIGBUS/SIGSEGV sono intercettati per terminare la diagnosi senza tentare altri indirizzi.

La geometria CPU usa la pagina del sistema, non quella GPU. Le finestre A2000 osservate a offset 2A0000/4A0000 non vengono arrotondate a 2 MiB. Il confronto della PTE decodificata è una correlazione software: non certifica la validità hardware di una pagina GPU disallineata. Questo candidato può leggere la finestra BAR1 esatta indipendentemente da tale problema.

Il proprietario scrive e verifica localmente 00003039, poi 6B2D91E7, con sincronizzazione prima di ogni lettura CPU. Infine ripristina e verifica 00003039 prima dei kernel peer. I pattern non vengono trasferiti alla seconda GPU tramite RAM. Il controllo CPU non è presentato come trasporto P2P né misura prestazionale.

## Verifiche locali completate

Compilazione C++17 del parser con Clang, `-Wall -Wextra -Werror`, AddressSanitizer e UndefinedBehaviorSanitizer. Risultato: **425 casi passati**, inclusi quattro frammenti autentici del nuovo `native-instrumented2-gpu-results/kernel.log`, duplicati, troncamenti, marker assenti, descriptor mancante, PTE discordanti, status errati e mapping distrutti.

I marker nelle fixture sono sintetici e dichiarati: servono soltanto al test offline. Non autorizzano alcun mmap e non sono letti dal runtime. Il ramo Linux dell'header è stato verificato sintatticamente su macOS usando solo una dichiarazione klogctl locale (`validation-shim`); questa verifica non sostituisce la compilazione NVCC/Linux. Nessuna funzione hardware è stata chiamata durante i test.

## Limiti

Un PASS verifica che quella finestra BAR1 viva raggiunga la word del proprietario attraverso il percorso CPU. Non prova la consegna delle richieste di un'altra GPU, non legge la page table hardware e non risolve il P2P da solo. Un FAIL numerico lascia da distinguere mapping e visibilità; uno SKIP significa che la correlazione o l'accesso non erano verificabili. Il controllo non forza SYNC_MEMOPS su VMM e non cambia le proprietà dell'allocazione rispetto alla base.

Compilazione candidata Linux, a cura del coordinatore: usare lo stesso comando NVCC e le stesse librerie del probe precedente, sostituendo solo il sorgente con `peer_vmm_word_cpubar.cu` e includendo entrambi gli header di questa cartella. Non usare gli eseguibili macOS delle fixture sul server. Gli hash dei sorgenti e i risultati locali sono in `local-validation.json`.
