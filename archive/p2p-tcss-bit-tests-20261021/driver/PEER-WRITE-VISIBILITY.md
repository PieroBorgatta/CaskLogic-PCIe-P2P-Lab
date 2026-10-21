> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Visibilità della scrittura peer: cosa è documentato e cosa resta da misurare

Il controllo CPU-BAR1 superato prima del trasferimento non esclude un problema di visibilità dopo la scrittura peer. Non è però stata individuata una funzione CUDA obbligatoria mancante che spieghi già il fallimento Ada→A2000. Nessuna modifica o nuova prova è stata eseguita per questa nota.

La [guida CUDA 12.9.1, Memory Fence Functions](https://docs.nvidia.com/cuda/archive/12.9.1/cuda-c-programming-guide/index.html#memory-fence-functions) include la memoria dei dispositivi peer nell'ambito di `__threadfence_system()`. La fence impone un ordine agli accessi del thread; la guida separa questo effetto dalla visibilità e dalla sincronizzazione tra consumatore e produttore. Non è una garanzia generale di consegna per qualunque mapping PCIe costruito manualmente. Nel nostro kernel sono già presenti store volatile, fence di sistema e sincronizzazione del writer; la copia D2H sulla GPU proprietaria è avviata successivamente dalla CPU. Il nuovo push usa questa sequenza senza letture peer esplicite.

Il [contratto GPUDirect RDMA, §2.7](https://docs.nvidia.com/cuda/archive/12.9.1/gpudirect-rdma/index.html#synchronization-and-memory-ordering) tratta invece il percorso indipendente dei dispositivi esterni. `CU_POINTER_ATTRIBUTE_SYNC_MEMOPS` rende conservative le operazioni CUDA per una specifica allocazione e impedisce che ottimizzazioni asincrone anticipino il ritorno al chiamante rispetto all'accesso BAR. La documentazione richiede che le scritture DMA siano completate prima della successiva operazione CUDA che ne consuma i dati; un kernel concorrente può vedere dati vecchi o parziali. La prova presente sincronizza già esplicitamente inizializzazione/azzeramento e non esegue il consumatore contemporaneamente al kernel produttore. Aggiungere SYNC_MEMOPS non dimostrerebbe, da solo, che le scritture peer siano arrivate alla destinazione.

[`cuFlushGPUDirectRDMAWrites`](https://docs.nvidia.com/cuda/archive/12.9.1/cuda-driver-api/group__CUDA__DEVICE.html) è documentata per scritture RDMA nel contesto bersaglio tramite mapping creati da API come `nvidia_p2p_get_pages`. Attende la visibilità nello scope richiesto; può essere una no-op quando l'ordinamento dichiarato dal dispositivo copre già quello scope. Non è documentata come riparazione universale dei PTE del nostro percorso UVM/BAR1 modificato.

Per un eventuale esperimento motivato, prima interrogare gli attributi `CU_DEVICE_ATTRIBUTE_GPU_DIRECT_RDMA_SUPPORTED`, `CU_DEVICE_ATTRIBUTE_GPU_DIRECT_RDMA_FLUSH_WRITES_OPTIONS` e `CU_DEVICE_ATTRIBUTE_GPU_DIRECT_RDMA_WRITES_ORDERING`. I [tipi ufficiali NVIDIA](https://docs.nvidia.com/cuda/archive/12.8.2/cuda-driver-api/group__CUDA__TYPES.html) identificano l'opzione HOST che abilita la funzione, e lo scope `CU_FLUSH_GPU_DIRECT_RDMA_WRITES_TO_OWNER`. La chiamata, se pertinente e supportata, andrebbe effettuata nel contesto della GPU **proprietaria del buffer**, dopo la sincronizzazione del writer e prima del consumo locale. Si devono registrare valori, risultato API e possibile no-op; il semplice successo della funzione non prova che abbia effettuato un flush.

## Discriminante proposto prima di modificare il driver

Riutilizzare il controllo CPU in sola lettura sulla medesima finestra viva **dopo** il kernel peer_write e la sincronizzazione del writer, prima di reinizializzare o liberare il buffer. La catena nonce/GPUVA/UUID/handle/descrittore/window/DMA deve essere rivalidata dal log corrente. Leggere quattro byte, confrontare con il valore atteso e con la copia D2H della GPU proprietaria. Conservare entrambi i risultati e la loro sequenza; nessuna scrittura CPU nella BAR, nessun trasferimento del payload verso l'altra GPU tramite RAM.

| CPU legge BAR1 | CUDA proprietaria legge | Interpretazione |
|---|---|---|
| Valore nuovo | Valore vecchio | Evidenza concreta di una divergenza di visibilità/coerenza tra i due percorsi; non prova ancora quale cache/attributo sia responsabile. |
| Valore vecchio | Valore vecchio | La scrittura non è osservata da nessuno dei due controlli; restano routing, permessi, indirizzo o completamento. |
| Valore nuovo | Valore nuovo | La scrittura è visibile in questa sequenza; confrontare col test senza lettura CPU intermedia, perché la lettura MMIO potrebbe modificare il timing/ordinamento. |

Una lettura CPU non è un osservatore perfettamente neutro: potrebbe drenare traffico o alterare i tempi. Per questo un eventuale successo introdotto dalla lettura richiede un controllo causale prima di trasformarlo in workaround. Lo stato attuale resta: CPU-BAR1 iniziale corretta, P2P Ada→A2000 non risolto, nessuna prova che il responsabile sia L2.
