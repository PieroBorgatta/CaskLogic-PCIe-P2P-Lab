> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Cleanup dinamico BAR1 e residui IOVAS

Analisi solo locale della base strumentata effettivamente compilata. Nessun modulo caricato e nessuna modifica alla base dei test. Il candidato allegato corregge un ordine di rilascio nel percorso di emergenza; **non è dimostrato che elimini i quattro mapping residui osservati**.

## Evidenza dei due avvii

Le righe complete, i numeri di riga, gli hash dei log e la conversione fra CLOCK_MONOTONIC e clock del kernel sono conservati in [cleanup-evidence.json](cleanup-evidence.json).

| Avvio | Finestre create/rilasciate | Ultimo WINDOW_DESTROY_DONE, clock kernel | IOVAS 0x100: quattro residui | Ritardo rispetto a context_exit_begin, clock corretto |
|---|---:|---:|---:|---:|
| native-instrumented2 | 4/4, ID1–4 | 13.299326s | 13.568387s | 269,03ms |
| native-regalign | 4/4, ID1–4 | 13.317290s | 13.594235s | 276,91ms |

In entrambi gli avvii i quattro confronti e `data_done` precedono tutti i rilasci espliciti. Gli assert `pIOVAS != NULL` alle righe598/607 compaiono dopo la distruzione della IOVAS, ancora più tardi. La dispersione della correlazione temporale è rispettivamente circa13,5µs e20,9µs: non cambia questo ordine.

Le finestre ID1/4 appartengono alla IOVAS0x600; ID2/3 alla IOVAS0x100. Il numero quattro nei residui della sola IOVAS0x100 non basta a identificarli con le quattro finestre del probe.

## Percorso del rilascio normale

I riferimenti di riga seguenti riguardano `driver-instrumented/validated-complete-tree/source/NVIDIA-open-gpu-kernel-modules-19f3b34`, coerente con la copia `instrumented-subset` usata per il manifest.

1. `kernel-open/nvidia-uvm/uvm_map_external.c:1263` attende il tracker, invalida la cache se richiesto, cancella le PTE e libera le strutture della page table. Il rilascio differito mantiene vivo il GPU proprietario fino alla liberazione dell'handle.
2. Nello stesso file, `uvm_ext_gpu_map_free_internal:1232` decremente il riferimento; `uvm_release_rm_handle:586` chiama `nvUvmInterfaceFreeDupedHandle`.
3. `kernel-open/nvidia/nv_uvm_interface.c:779` inoltra la richiesta a RM.
4. `src/nvidia/src/kernel/rmapi/nv_gpu_ops.c:9759` ottiene il Memory associato all'handle duplicato, rilascia l'eventuale mapping IOMMU sysmem di `nvGpuOpsDupMemory`, chiama `_nvGpuOpsDynBar1Destroy`, poi libera l'handle RM.
5. `_nvGpuOpsDynBar1Destroy:3912` rimuove la finestra dall'elenco e libera nell'ordine: mapping IOMMU del descrittore finestra → descrittore finestra → mapping BAR1 sul proprietario → struttura di tracciamento.

Questo ordine IOMMU/descrittore è coerente: `memdescUnmapIommu` decrementa il riferimento alla mappatura mentre il descrittore esiste ancora; `memdescDestroy` libera il descrittore quando il suo RefCount arriva a zero. In `mem_desc.c:542` il distruttore rimuove anche eventuali mapping IOMMU residui del descrittore. Il `pWin` del percorso dinamico è creato con RefCount1 e il codice dinamico non aggiunge riferimenti a quel descrittore.

Le quattro coppie BEGIN/DONE dimostrano che il normale hook UVM è stato raggiunto e completato per tutte le finestre. **DONE non certifica il codice di ritorno di ogni operazione interna:** il codice attuale ignora il risultato dell'acquisizione del lock remoto e di `kbusUnmapFbAperture_HAL`. Non ci sono assert prima dei DONE nei log esaminati, ma questi valori non sono stampati.

## Che cosa significano realmente gli errori

`src/nvidia/src/kernel/mem_mgr/io_vaspace.c:60` conta oggetti di mapping ancora associati alla IOVAS quando questa viene distrutta. `iovaspaceFromMapping:589` e `iovaMappingDestroy:603` trovano successivamente una mappatura il cui spazio non esiste più. È un difetto di durata degli oggetti, non una misura del trasferimento PCIe.

`src/nvidia/arch/nvalloc/unix/src/osinit.c:1244`, `RmTeardownDeviceDma`, distrugge lo spazio DMA alla chiusura del dispositivo. La distruzione tardiva sotto GPU1 è compatibile con descrittori conservati su un GPU che referenziano la IOVAS dell'altro GPU, chiuso per primo. I log attuali non espongono il puntatore/tipo/proprietario dei quattro descrittori: questa identificazione resta aperta.

Esistono altri utilizzatori IOMMU: le allocazioni sysmem duplicate in `nvGpuOpsDupMemory`, i mapping di memoria virtuale, i descrittori di accesso BAR/mailbox di `kbusSetupPeerBarAccess` e le regioni BAR1 statiche. In questi due run entrambe le finestre sono dinamiche e tutti i quattro hook sono chiusi. Non si modifica uno degli altri percorsi soltanto perché produce lo stesso conteggio.

## Difetto concreto del fallback e candidato separato

In `nvGpuOpsDeviceDestroy:2362` il codice dinamico aggiunto esegueva `Free(subDeviceHandle)` prima di `_nvGpuOpsDynBar1DestroyAll`. L'eventuale elenco residuo contiene puntatori a descrittori e stato GPU che il rilascio RM può già avere eliminato. Il drenaggio deve precedere tale rilascio.

[subdevice-before-rm-free.patch](subdevice-before-rm-free.patch) sposta solo il drenaggio prima della rimozione del sottodispositivo e del `Free` RM, mantenendo il contesto del lock btree preesistente; la distruzione del mutex resta dopo il rilascio. Nessun cambiamento a PTE, indirizzi, modalità cache, geometria pagine, UVM o assert IOVAS. La verifica esatta avanti/indietro della patch passa e tutti i byte fuori da `nvGpuOpsDeviceDestroy` sono identici. Hash in [manifest.json](manifest.json).

**Preparato, non compilato e non eseguito.** Nei due avvii l'elenco normale era già drenato: questa correzione migliora il fallback, ma non spiega da sola i quattro residui. Non la si presenta come soluzione del trasporto o del leak osservato.

Altri difetti concreti da trattare separatamente: il risultato del lock remoto ignorato in `Destroy` e nel rollback di `Create`; il codice di ritorno dell'unmap BAR1 ignorato; eventuale cleanup di `dupMemory` su errori successivi all'acquisizione di un mapping IOMMU. Gli ultimi errori non sono stati osservati nei due run e una correzione completa richiede propagazione/ritenzione coerente degli oggetti, non la soppressione degli assert.

## Per identificare i quattro oggetti senza cambiare il mapping

Una successiva strumentazione separata può registrare in `io_vaspace.c` creazione/distruzione di root e submapping e variazione del refcount: puntatore IOVAMAPPING, `pPhysMemDesc`, proprietario GPU, IOVAS, tipo di memoria, Size, RefCount del memdesc, refcount del mapping, eventuale padre. Registrare anche `_memdescFreeIommuMappings` e `RmTeardownDeviceDma`. L'insieme CREATE meno DESTROY al momento dello shutdown identificherà i quattro oggetti; solo allora si può scegliere il proprietario del cleanup corretto. Questa strumentazione è una proposta, non una patch applicata.

## Attenzione ai risultati del fork originario

I confronti GitHub già archiviati mostrano che il fork Method3 disabilita il controllo `left-over mappings`, l'assert di `iovaspaceFromMapping` e quello di `iovaMappingDestroy`; il fork615 li trasforma in warning e ritorna se la IOVAS non esiste. Questi cambiamenti **non liberano** la mappatura rimasta viva.

Fonti locali: `../../gpu-followup-20261020/driver-reference/method3-comparison.json` e `615-comparison.json`, campo `files` dell'elemento `src/nvidia/src/kernel/mem_mgr/io_vaspace.c`. La base locale strumentata conserva il file stock: il suo hash è identico a quello dell'archivio pulito. Non viene importata la soppressione degli errori. Un'affermazione del fork di “dmesg pulito” non è quindi prova sufficiente di cleanup corretto.
