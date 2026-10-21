> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Candidato diagnostico CE fisico, sola parola di quattro byte

Il candidato aggiunge un ingresso sperimentale a **UVM**, mantenendo byte per byte il modulo RM strumentato `ab41b0a3…b1b5`. Non modifica il mapping BAR1, le PTE esistenti, la politica di cache o il cleanup ordinario. Prima della compilazione è soltanto codice locale: non costituisce una prova hardware riuscita.

L'ingresso accetta soltanto i due UUID della macchina, due VA del processo chiamante e una lunghezza esatta di 4 byte. Non accetta indirizzi fisici, handle RM o testi dei log. Il processo usa il proprio FD CUDA già inizializzato, individuato solo in `/proc/self/fd`; una nuova apertura UVM avrebbe uno spazio virtuale diverso e viene rifiutata dalla verifica dei mapping.

## Identità, mapping e durata

Sono richiesti CPU Intel 906A3 senza hypervisor, GPU Ada 28B0 su 01:00.0 e A2000 2571 su 06:00.0, UUID esatti, classi CE C6B5/C7B5, memoria locale lineare non EGM/fabric e mapping esterni originali non suddivisi. L'opzione `uvm_cask_physical_ce=1` è di sola lettura e disabilitata per default; occorrono inoltre `uvm_enable_builtin_tests=1` e `CAP_SYS_ADMIN`.

I metadati aggiunti alla struttura privata di UVM sono copiati soltanto da una duplicazione RM validata: offset dell'allocazione, VA originale, dimensioni, permessi e handle utente di origine. Il flag di validità viene posto soltanto dopo la riuscita della mappatura. Una suddivisione lascia i nuovi metadati a zero nel pezzo nuovo; il pezzo vecchio non coincide più con l'intervallo originale. Entrambi sono esclusi dalla diagnostica.

L'ioctl risolve tre mappe nello spazio virtuale del FD: sorgente locale dell'esecutore, destinazione peer vista dall'esecutore e la medesima destinazione vista dal proprietario. Le due mappe della destinazione devono avere identici handle utente di origine, offset e dimensioni. La VA-space lock in scrittura esclude modifiche concorrenti mentre si ricavano gli indirizzi e si attende la copia.

La coppia pubblicata dal driver è **PCIE_BAR1**, distinta da PCIE. Due helper UVM circoscritti trattengono solo una coppia BAR1 già presente con riferimento non nullo; riutilizzano `peers_retain`/`peers_release` senza creare una nuova coppia. La coppia e le due GPU vengono trattenute sotto `global_lock` prima della VA lock e rilasciate dopo averla lasciata. I tre handle duplicati ricevono riferimenti ulteriori prima della submission. In caso di completamento incerto restano trattenuti coppia, GPU, handle e modulo fino al riavvio. Il processo di prova deve restare vivo senza altre API CUDA o liberazioni; il watchdog del sistema nativo è il limite operativo.

## Indirizzi e comandi

`nvUvmInterfaceGetExternalAllocPhysAddrs` viene interrogata su una sola pagina da 4 KiB contenente la parola. Per memoria locale VID restituisce l'offset fisico della VRAM; per la destinazione dinamica restituisce già `dynBar1DmaBase + allocation_offset`. Non viene aggiunta una seconda volta la base BAR1.

Il tipo pubblico documenta `physAddrBufferSize` in byte, e il callsite stock usa byte; l'implementazione RM di questa versione lo confronta invece con un numero di elementi. Il candidato conserva `sizeof(NvU64)=8` secondo l'interfaccia. La richiesta rigida `size/page=4096/4096=1` limita comunque `min(8,1)` a un solo elemento, e vengono verificati esattamente un elemento scritto e zero rimanenti.

L'indirizzo locale è limitato alla VRAM della sorgente. Quello remoto deve ricadere nella BAR1 PCI attuale della destinazione. Si richiede `dma_addressable_start==0` sull'esecutore e indirizzo finale entro `dma_addressable_limit`, senza scrivere registri DMA. Il canale viene scelto esplicitamente con `uvm_push_begin_gpu_to_gpu(source_manager, destination)`, quindi deve risultare P2P, privilegiato, CE e non proxy. Non si usa il classificatore di indirizzi peer, che può non riconoscere le finestre dinamiche con capacità BAR1 globali 0/0.

Sono emessi `SET_SRC_PHYS_MODE=LOCAL_FB(0)`, `SET_DST_PHYS_MODE=NONCOHERENT_SYSMEM(2)`, indirizzi fisici, lunghezza 4 e `LAUNCH_DMA` con SRC/DST PHYSICAL, pitch, non pipelined, flush SYS e la politica PLC HAL della classe. Non c'è fallback virtuale o copia del payload in RAM. Il comando non usa `uvm_gpu_address_copy`, che può convertire una richiesta fisica in virtuale.

La scelta esplicita **NONCOHERENT** corrisponde all'apertura della PTE esterna della baseline. Il normale helper CE UVM per `UVM_APERTURE_SYS` seleziona invece **COHERENT(1)**: questa prova identifica una transazione fisica precisa e non consente di affermare che rispetto a ogni copia CUDA vari soltanto la traduzione. `COMPLETED` indica il completamento del tracker CE, non la consegna corretta dei dati; resta necessario confrontare la parola sul proprietario.

## ABI e consegna

`cask_phys_ce_ioctl.h` è ABI v1: ioctl Linux 315, struttura 144 byte allineata a 8. I primi 72 byte sono input; gli output sono azzerati dal kernel. `VALIDATE` non invia un'operazione GPU. `EXECUTE` ripete le verifiche, ricava gli indirizzi da RM e invia solo la copia fisica. Successo atteso: syscall 0, `rmStatus=0`, flag `0x77`; `RETAINED` oppure SUBMITTED senza COMPLETED richiedono attesa del riavvio senza liberare risorse.

`manifest.json` fissa preimmagine e postimmagine di nove file UVM; `overlay/` contiene tutte le postimmagini e `physical-ce.patch` lo stesso delta. `prepare_overlay.py` ricostruisce la consegna dalla baseline locale immutata. `build_uvm.py`, gestito dal coordinatore, clona la build verificata e ricompila soltanto UVM; il modulo RM copiato viene confrontato con il suo hash baseline. Nessuna installazione è parte del candidato.

Fonti locali primarie nella baseline: `uvm_gpu.c` (lifetime coppia e GPU), `uvm_map_external.c` (duplicazione e tracker), `nv_gpu_ops.c` (query fisica e finestra dinamica), `uvm_ampere_ce.c`/`uvm_turing_ce.c` e `clc6b5.h`/`clc7b5.h` (comandi). Le API del ramo pubblico sono consultabili nei [sorgenti NVIDIA 595.99.02](https://github.com/NVIDIA/open-gpu-kernel-modules/tree/595.99.02/kernel-open/nvidia-uvm); il delta dynamic della baseline è distinto dal codice stock e resta identificato dagli hash locali.
