> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# CaskLogic — verifica AOOSTAR e compatibilità Ampere/Ada

21 ottobre 2026. **Il P2P bidirezionale resta non risolto.** Questa fase aggiunge una verifica del supporto ufficiale del dock e delle architetture effettivamente rilevate. Non contiene nuove prove di trasferimento, modifiche al driver, scritture firmware o riavvii del server. Lo storico sperimentale rimane nel [rapporto precedente](../p2p-next-investigation-20261021/ESITO.md).

## Risultato della verifica AOOSTAR

L'utente ha confermato un alimentatore da **800 W**, non il modello stampato né la revisione del circuito. La [pagina ufficiale AG02](https://aoostar.com/collections/egpu-series/products/aoostar-ag01-egpu-dock-with-oculink-port-built-in-huntkey-400w-power-supply-supports-tgx-interface-hot-swap?variant=49246191223082) descrive una variante USB4 + OCuLink da 800 W e indica ASM2464PDX nelle FAQ. Il nome AG01/400W rimasto nell'URL non è il titolo attuale del prodotto. AG02 è quindi un'identificazione plausibile, ancora da confermare sull'etichetta; la potenza non prova la revisione della scheda.

**Sì, il controller prevede firmware:** la [scheda ufficiale ASMedia ASM2464PDX](https://www.asmedia.com.tw/product/bDFzXa0ip1YI7Wj1/C64ZX59yu4sY1GW5.html) dichiara un'interfaccia SPI con ROM esterna per codice personalizzato. Questo documenta la capacità del controller, non una procedura universale per aggiornare ogni dock che lo monta. ASMedia descrive inoltre il tunneling PCIe per eGPU; non fornisce in quella pagina una garanzia di P2P fra una GPU interna e una esterna, né un aggiornamento specifico per il problema osservato.

La lettura dell'host alle **09:13 CEST** rileva due bridge PCI `1b21:2461`, ai BDF `0000:04:00.0` e `0000:05:00.0`, con sottosistema `1b21:2461` e revisione PCI `00`. Questi dati non sono una versione firmware e non identificano in modo sufficiente modello e revisione del dock. In questo avvio XCP-ng manca `/sys/bus/thunderbolt/devices`: non è stato possibile leggere `nvm_version`. L'assenza dell'interfaccia non prova l'assenza di firmware nel dispositivo. Inventario host *(artefatto locale non pubblicato)*.

Nel [supporto ufficiale AOOSTAR](https://aoostar.com/pages/drives-systems), la voce AG01/AG02/MG02 contiene soltanto un collegamento etichettato **“NVIDIA EGPU has error 43”**. Non è presentato come aggiornamento firmware, non indica una versione né revisioni compatibili. Il collegamento pubblico è stato interrogato senza scaricare o eseguire software: MEGA ha restituito `-9`, definito `API_ENOENT` nel [suo SDK ufficiale](https://github.com/meganz/sdk/blob/master/include/mega/types.h). Non è stato quindi possibile accertare nome o contenuto del file. [Verbale della richiesta](aoostar-download-check.json).

**Non è stato trovato un pacchetto firmware ufficiale AG02 pubblicamente verificabile e applicabile a questo esemplare.** Non equivale ad affermare che AOOSTAR non abbia firmware da fornire su richiesta. Non è possibile stabilire se il dock sia aggiornato senza conoscerne la versione corrente e quella approvata dal produttore per la stessa revisione. Non è stato installato firmware generico ASM2464 o destinato a prodotti diversi.

Il firmware del bridge resta una possibile causa del comportamento, perché il bridge è nel percorso che fallisce. Questa è un'ipotesi, non una localizzazione del difetto: i risultati disponibili non separano bridge ASMedia, percorso Intel e comportamento della GPU richiedente. La [documentazione Linux USB4/Thunderbolt](https://www.kernel.org/doc/html/latest/admin-guide/thunderbolt.html) descrive l'aggiornamento NVM e richiede un'immagine adatta al dispositivo; non certifica che l'interfaccia di aggiornamento sia disponibile su questo dock e questo avvio XCP-ng.

## Architetture rilevate e significato della direzione

L'inventario NVIDIA conferma direttamente le architetture. Le compute capability sono verificate sulla [tabella ufficiale NVIDIA](https://developer.nvidia.com/cuda/gpus).

| GPU | Collegamento già documentato | Architettura | Compute capability | VBIOS rilevato |
|---|---|---|---|---|
| RTX A2000 12 GB | Esterna, USB4/AOOSTAR | Ampere | 8.6 | 94.06.32.00.18 |
| RTX 2000 Ada Generation 16 GB | Interna, PCIe PEG | Ada Lovelace | 8.9 | 95.07.4D.00.01 |

Il driver e il firmware GSP dichiarati da entrambe sono `595.99.02`. Le versioni VBIOS diverse sono dati di inventario: non dimostrano un'incompatibilità da correggere. Inventario GPU e servizi *(artefatto locale non pubblicato)*.

**L'ipotesi dell'architettura diversa è plausibile, ma non è dimostrata su questa coppia.** In una [risposta NVIDIA del 2021](https://forums.developer.nvidia.com/t/clarification-on-requirements-for-gpudirect-rdma/188114), Robert Crovella segnala che il P2P fra architetture diverse generalmente non è supportato. Il caso discusso riguardava A100 e Quadro P1000: non è una matrice di compatibilità attuale per A2000/Ada 2000. Una [successiva spiegazione NVIDIA del 2023](https://forums.developer.nvidia.com/t/how-can-i-tell-which-nvidia-gpus-will-have-p2p-access-to-the-same-gpu-on-pcie/248378/4) distingue capacità della GPU e funzionamento effettivo sulla piattaforma, che può dipendere anche da BIOS e driver.

Non è stata trovata una regola documentata secondo cui una GPU più vecchia possa sempre scrivere in una più nuova, ma non viceversa. Le [API CUDA](https://docs.nvidia.com/cuda/cuda-runtime-api/cuda_runtime_api/group__CUDART__PEER.html) trattano l'accesso peer come direzionale: l'abilitazione in una direzione non abilita automaticamente l'altra. Questo requisito non è una soluzione nuova per le prove già svolte.

Nel nostro montaggio età e posizione coincidono: Ampere è sempre esterna e Ada sempre interna. Il risultato sperimentale A2000→Ada corretto e Ada→A2000 errato è perciò compatibile sia con una differenza fra GPU sia con un'asimmetria del percorso. Non permette da solo di scegliere una delle due spiegazioni.

## Confronto con le prove già eseguite

I risultati qui sotto sono precedenti, non ripetuti in questa fase. Riguardano l'ambiente sperimentale documentato e non qualificano il driver per l'uso in produzione.

| Ipotesi o proposta | Evidenza già disponibile |
|---|---|
| Fare scrivere l'A2000 nella memoria Ada | PUSH A2000→Ada: 6/6 confronti corretti nel confronto nativo qualificato. |
| Fare scrivere l'Ada nella memoria A2000 | PUSH Ada→A2000: 6/6 confronti errati. |
| Far avviare all'A2000 una lettura dei dati Ada per trasferirli verso l'A2000 | Anche il PULL è stato provato: tutti i 12 confronti PULL nelle due direzioni sono falliti, con percorsi CE e SM distinti e osservati. |
| Evitare la sola traduzione virtuale CUDA | Le copie fisiche CE verso BAR1, nelle due modalità di destinazione provate, conservano forward errato e reverse corretto. |
| Abilitare il controllo firmware peer già individuato | I bit CCFG individuati sono stati effettivamente modificati e riletti nel lavoro precedente, senza sbloccare Ada→A2000; lo span FSP è stato poi ripristinato. |

Fonti locali: [PUSH/PULL](../p2p-next-investigation-20261021/native-pushpull-results/ANALISI.md), [copie fisiche PHYS2](../p2p-next-investigation-20261021/native-physical2-ce-results/ANALISI.md), [PHYS3](../p2p-next-investigation-20261021/native-physical3-ce-results/ANALISI.md), [verifica firmware](../p2p-next-investigation-20261021/firmware-review.md).

Di conseguenza, un adattatore software che si limiti a far iniziare tutte le copie alla GPU vecchia non ha una base sperimentale positiva. Neppure dichiarare supportata la coppia basta: il dato deve arrivare corretto. Queste osservazioni non provano l'impossibilità di una futura correzione del produttore.

## Prossimo intervento fondato e stato operativo

Per la pista AOOSTAR serve un'immagine ufficiale associata alla revisione reale del dock, insieme alla versione installata, alle note delle modifiche e alla procedura prevista. La richiesta tecnica utile al produttore riguarda specificamente scritture e letture PCIe peer provenienti da un altro ramo del root complex, non il semplice riconoscimento della eGPU. Per NVIDIA serve invece una conferma sul supporto della coppia Ampere A2000 / Ada 2000 e sulle condizioni del percorso PCIe. Nessuna di queste informazioni è sostituita dalla sola potenza di 800 W.

Non è disponibile, al termine di questa verifica, una nuova correzione verificata da applicare. Non sono stati cambiati collegamenti, firmware, driver, avvio o dati del server. Alle 09:13 CEST entrambe le GPU risultano presenti, senza processi compute, a 29 °C e 35 °C; Docker, persistenza NVIDIA e ventole sono attivi, training inattivo. Questa è una verifica operativa limitata, non un controllo integrale dei dati.

Le precedenti attività di modifica personalizzata firmware/driver avevano ricevuto un rifiuto automatico per possibile rischio di cybersecurity. Non sono state ritentate attraverso questa ricerca sul supporto ufficiale. Le letture e ricerche di questa fase sono riuscite, ma non certificano la rimozione del precedente blocco.

La condizione richiesta per pubblicare un repository e presentare una soluzione non è soddisfatta. Nessun repository, post o messaggio esterno è stato pubblicato o inviato.
