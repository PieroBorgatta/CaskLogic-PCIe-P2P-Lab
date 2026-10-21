> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Traccia reale e disallineamento delle pagine

La prova nativa con proprietari sincronizzati e puntatori espliciti termina con tre confronti errati su quattro. I quattro controlli locali dei proprietari passano. `pte-chain-validation.json` collega tutte e quattro le allocazioni a DMA, finestra BAR1, PTE RM, copia UVM e completamento del mapping.

L'uguaglianza fra indirizzo costruito e decodificato è verificata; l'allineamento alla dimensione effettiva della pagina presenta invece due violazioni. La precedente versione del parser verificava l'uguaglianza senza questo requisito: il risultato ora separa `chain_equality_status` e `page_alignment`, e lo stato complessivo segnala il disallineamento.

| ID finestra | Proprietario / ruolo dal puntatore | BAR1 offset | DMA / decoded PTE | Pagina RM | Resto rispetto alla pagina |
| --- | --- | --- | --- | --- | --- |
| 1 | Ada, `src` effettivamente letto/scritto dal peer | `0x400000` | `0x4000400000` | `0x200000`, entry16 | `0` |
| 2 | A2000, `dst` locale del kernel di lettura | `0x2a0000` | `0x46002a0000` | `0x200000`, entry16 | `0xa0000` |
| 3 | A2000, `src` effettivamente letto/scritto dal peer | `0x4a0000` | `0x46004a0000` | `0x200000`, entry16 | `0xa0000` |
| 4 | Ada, `dst` locale del kernel di lettura | `0x600000` | `0x4000600000` | `0x200000`, entry16 | `0` |

La GPU emittente è identificata dal BDF in `DMA_MAP`; gli ID1/9 di UVM non sono gli indici CUDA. Tutte e quattro le traduzioni DMA hanno delta zero in questa esecuzione nativa. I puntatori `src` realmente usati sono `0x7e36bf400000` per Ada e `0x7e36bf800000` per A2000. Le allocazioni sono2MiB, il payload verificato è4byte.

## Perché il decoder non esclude questo difetto

`gmmuFieldGetAddress()` ricompone il campo indirizzo della PTE con shift12: può quindi restituire esattamente un indirizzo multiplo di4KiB, anche se la PTE è inserita a un livello che descrive2MiB. L'entry16 qui è la large PTE del livello PDE0, non la leaf PTE8 di4KiB. Non è stato effettuato un readback hardware né è stato osservato il TLP sul filo. Non si afferma quale comportamento hardware specifico abbia una large PTE disallineata.

I sorgenti NVIDIA locali confermano il contratto di allineamento e l'origine della dimensione:

- `kernel-open/nvidia-uvm/uvm_turing_mmu.c:343`: il physical address di una PTE deve essere allineato a `page_size`; la HAL Ampere eredita il formato Turing e supporta4KiB,64KiB,2MiB,512MiB.
- `src/nvidia/src/kernel/rmapi/nv_gpu_ops.c`, funzione `nvGpuOpsFillGpuMemoryInfo`: esporta `pageSize` dalla memoria video originale.
- `kernel-open/nvidia-uvm/uvm_map_external.c`, scelta `mapping_page_size`: usa `mem_info.pageSize`, virtual address, lunghezza e offset; non conosce ancora la diversa granularità della futura finestra BAR1.
- La patch dynamic sostituisce l'indirizzo fisico con `dynBar1DmaBase + offset`, senza ridurre la pagina dichiarata in base all'allineamento della finestra.
- `kern_bus.c`, `kbusDetermineBar1Force64KBMapping`: default della policy `RM64KBBAR1Mappings` attivo quando BAR1 è al massimo256MiB; l'A2000 ha256MiB, la Ada16GiB. L'audit separato identifica `RM64KBBAR1Mappings=0` come parametro esistente da provare prima di modificare il codice.

Questo difetto è compatibile con la scrittura Ada→A2000 che termina senza errore PCI ma non consegna il valore atteso. Non spiega da solo la lettura A2000→Ada fallita, perché la finestra Ada usata in quel caso è già allineata2MiB. Il test del parametro deve quindi essere valutato per ognuno dei quattro confronti, senza considerare il problema complessivo risolto se ne passa soltanto uno in più.

Backup locale preparato: `../driver-uvm4k/uvm-peer-4k.patch`, parametro disattivato per default `uvm_cask_peer_small_pages`. Quando attivato limita a4KiB soltanto i mapping esterni fra GPU diverse su VRAM con proprietario noto e HAL che supporta4KiB. Il modulo RM e i suoi indirizzi restano identici; nessun build o caricamento è stato eseguito dall'agente locale.
