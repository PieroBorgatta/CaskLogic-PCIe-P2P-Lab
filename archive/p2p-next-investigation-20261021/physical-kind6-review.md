> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# CE fisico: guardia KIND e permessi

La prima esecuzione si è fermata nella selezione del file descriptor UVM, prima di ogni confronto SM/CE e prima delle calibrazioni NVML. Non costituisce un fallimento del motore CE fisico. Il candidato v3 corregge due condizioni di ammissione troppo restrittive e aggiunge la diagnostica che mancava per individuare il primo controllo respinto.

## Risultato realmente acquisito

In `native-physical-ce-results/result.log`, la richiesta `13653417237` restituisce sul fd10 `rmStatus=40`, `flags=0`; sul fd11 `rmStatus=16`, `flags=0`. Questi campi sono esadecimali. Il programma termina con `PHYS_ABORT`, `protocol_complete=0`, RC27. `PROBE_COMPLETED` è il marcatore del wrapper, non attesta confronti eseguiti. Il kernel registra solo `operation=0` (VALIDATE), senza metodi CE.

SHA256 dei due log letti indipendentemente:

- result.log: `9850efcefda7311096954ba9660edf4ca1045506e5a9bd5eebdb50545ba37e5d`
- kernel.log: `91522b10f7422dbc8a0902a257a24d82cfde1527102281b40386c6b9203b4564`

Le sei mappe delle quattro allocazioni hanno il primo PTE che inizia con `06`, ossia KIND6 nei bit63:56. Le mappe peer e owner della destinazione hanno lo stesso oggetto RM, offset0 e dimensione8MiB; i mapping CUDA interrogati dal programma hanno i permessi previsti. Il log precedente non espone tutti i metadati usati dalla nuova guardia: non permette di identificare con certezza il primo ramo fallito. La condizione `cask_phys_kind != 0` è però incompatibile con KIND6, e la selezione che ammette soltanto ReadWrite/ReadWriteAtomic può respingere anche il valore Default legittimo.

## Perché KIND6 è pertinente

Sono stati letti i sorgenti primari NVIDIA dell'archivio595.99.02, tree locale `NVIDIA-open-gpu-kernel-modules-19f3b34`, già sottoposto a verifica dell'archivio. I collegamenti usano l'identificatore abbreviato dell'archivio; questa revisione non ha nuovamente risolto il commit remoto completo.

1. `dev_mmu.h` definisce PITCH=0, GENERIC_MEMORY=6 e i kind compressibili a partire da8. `kind_macros.h` classifica compressibili i valori8–14;6 è fuori da quell'intervallo. [Definizioni NVIDIA](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/19f3b34/src/common/inc/swref/published/turing/tu102/dev_mmu.h), [classificazione](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/19f3b34/src/common/inc/swref/published/turing/tu102/kind_macros.h).
2. `memmgrIsKind_TU102`, caso `FB_IS_KIND_SWIZZLED`, restituisce falso per GENERIC_MEMORY e PITCH. La selezione HAL generata usa questa funzione anche per Ampere/Ada; le alternative mostrate riguardano GB20x. Quindi KIND6 è non compresso e non swizzled secondo questa classificazione del driver. [Implementazione](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/19f3b34/src/nvidia/src/kernel/gpu/mem_mgr/arch/turing/mem_mgr_tu102_base.c), [selezione HAL](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/19f3b34/src/nvidia/generated/g_mem_mgr_nvoc.c).
3. Il generatore normale UVM `make_pte_turing` inserisce KIND_GENERIC_MEMORY. `uvm_mem.c` deriva l'indirizzo fisico locale da `chunk->address + chunk_offset` e usa lo stesso indirizzo per costruire le PTE. [PTE](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/19f3b34/kernel-open/nvidia-uvm/uvm_turing_mmu.c), [indirizzamento delle allocazioni](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/19f3b34/kernel-open/nvidia-uvm/uvm_mem.c).
4. Il test NVIDIA `uvm_ce_test.c` alloca VRAM posseduta, ottiene un indirizzo fisico con `uvm_mem_gpu_address_physical` e lo usa per copie CE su un canale idoneo. C6B5/C7B5 ereditano la routine `uvm_hal_turing_ce_memcopy`, che seleziona PITCH per entrambi gli operandi, senza remap o multiline. Il test stock può rinunciare al fisico su canali non idonei: il nostro candidato rifiuta quel ripiego. [Test](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/19f3b34/kernel-open/nvidia-uvm/uvm_ce_test.c), [ereditarietà CE](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/19f3b34/kernel-open/nvidia-uvm/uvm_hal.c), [metodi di copia](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/19f3b34/kernel-open/nvidia-uvm/uvm_turing_ce.c).

Il solo KIND6 non certifica il formato di ogni superficie grafica. Lo stesso driver determina separatamente il carattere block-linear dagli Attr dell'allocazione. L'ammissione proposta riguarda esclusivamente la prima parola di4byte delle allocazioni CUDA VMM del programma, con formatoDefault, offset0, VA all'origine e kind esattamente0 oppure6; non è una conversione di superfici e non ammette kind compressibili.

## Default non scavalca la verifica dei permessi

`nvGpuOpsGetExternalAllocMappingAttribute` tratta Default come lettura/scrittura/atomiche solo se il descrittore non è DEVICE_READ_ONLY. Su un descrittore readonly, una richiesta esplicita ReadWrite restituisce `NV_ERR_INVALID_ACCESS_TYPE`.

`nvGpuOpsGetExternalAllocPhysAddrs` invoca quella verifica prima di restituire gli indirizzi. Nel candidato v3, EXECUTE richiede ReadWrite esplicito per sorgente e destinazione peer, e controlla il successo di entrambe le query prima di aprire il canale e prima di emettere metodi CE. Default è dunque solo un valore ammesso nella selezione preliminare; non costituisce da solo una prova di scrivibilità. [Fonte RM](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/19f3b34/src/nvidia/src/kernel/rmapi/nv_gpu_ops.c).

## Revisione del candidato v3

Revisione statica limitata al delta KIND/permessi/diagnostica e all'ordine prima dell'invio CE: nessun difetto bloccante individuato. File inc e copia nell'overlay sono identici.

- inc SHA256: `35d3cb183d7bbef27aebdb626aea5835458dec0939a0c648e21dae3eea9973e7`
- patch SHA256: `34acdf3111d112f35358b4b549a4f1c9c55b76cce9ac2f4581354e783bc476af`

La revisione non certifica i metadati che saranno restituiti a runtime, l'esecuzione hardware, la correttezza fisica di ogni mapping o il funzionamento P2P. Nessun accesso remoto, workload GPU o scrittura hardware è stato effettuato durante questa analisi.
