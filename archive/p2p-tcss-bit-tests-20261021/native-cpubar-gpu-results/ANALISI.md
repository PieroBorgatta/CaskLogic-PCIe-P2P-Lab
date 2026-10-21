> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# CPU→BAR1 funziona su entrambe le GPU; P2P ancora tre fallimenti su quattro

La prova nativa completa conferma **due controlli CPU-BAR1 superati**, ciascuno con due valori diversi, e riproduce gli stessi tre fallimenti P2P. Il controllo usa le stesse allocazioni e finestre fisiche poi impiegate dalle letture e scritture peer. Non verifica però come l'hardware della GPU richiedente interpreta il PTE o instrada la transazione.

`analyze_cpubar.py` rigenera `verified-result.json` dai file locali, senza operazioni sul server. L'analisi ha verificato quattro catene di mapping, dieci controlli della memoria locale, quattro letture CPU, quattro confronti P2P e 102 acquisizioni PCIe. `TOTAL_FAILURES 3`, `NATIVE_TEST_RC=5`, `SCRIPT_RC=5` e `PROBE_COMPLETED` documentano un test concluso, non interrotto prima dei confronti.

## Identità e condizioni

Linux nativo 7.0.0-38-generic, NVIDIA Open Kernel Module 595.99.02, CPU signature 000906a3 e hypervisor=0; il kernel conferma `DMAR: IOMMU disabled`. L'ordine CUDA è verificato dal sorgente/init e dalle identità UUID/BDF:

| CUDA | GPU | Endpoint | Root port |
|---|---|---|---|
| 0 | RTX 2000 Ada Generation, 16GB | 01:00.0, 10de:28b0 | 00:01.0, 8086:460d |
| 1 | RTX A2000 12GB | 06:00.0, 10de:2571 | 00:07.0, 8086:466e |

UUID Ada `GPU-00000000-0000-0000-0000-000000000001`; A2000 `GPU-00000000-0000-0000-0000-000000000002`. I due bridge ASMedia sono 04:00.0 e 05:00.0, entrambi 1b21:2461.

Il registro CCFG è verificato prima del driver, dopo il driver e dopo il test: D1=00008077, D7F0/D7F2=00009077. È attivo `RM64KBBAR1Mappings=0`; tutte le quattro finestre risultano allineate a 2MiB. `printk_devkmsg=on` mantiene tutti gli otto marcatori di allocazione e i 37 marcatori temporali del programma anche nel kernel log.

Il preflight low-MMIO di questo avvio era `execute=0` e ha restituito `not_started`, rc=-19: non è stata provata una riallocazione. I riferimenti runtime-PM del preflight sono azioni di gestione dell'alimentazione, quindi non lo si descrive come una sequenza globalmente priva di effetti hardware. I BAR1 usati dal controllo sono rimasti quelli alti indicati sotto.

## Catene e controllo CPU

Per ciascuna allocazione un nonce nuovo delimita nel log kernel la creazione. Sono coerenti GPUVA/UUID richiedente, handle UVM/RM, descrittore RM, ID della finestra, BDF di origine/destinazione DMA, indirizzo fisico e PTE prodotto; invio e completamento UVM riportano status=0. Nessuna finestra viene distrutta prima dei quattro confronti. I valori grezzi del PTE RM e di quello inviato da UVM coincidono; l'indirizzo decodificato dal formato software coincide con la finestra fisica.

| Finestra | GPU proprietaria | GPUVA | BAR1 + offset | Fisico/DMA | Uso |
|---|---|---|---|---|---|
| 1 | Ada | 7a15dd400000 | 4000000000 + 400000 | 4000400000 | Controllo CPU, lettura e scrittura da A2000 |
| 2 | A2000 | 7a15dd600000 | 4600000000 + 400000 | 4600400000 | Output locale del primo kernel di lettura |
| 3 | A2000 | 7a15dd800000 | 4600000000 + 600000 | 4600600000 | Controllo CPU, lettura e scrittura da Ada |
| 4 | Ada | 7a15dda00000 | 4000000000 + 600000 | 4000600000 | Output locale del secondo kernel di lettura |

Gli indirizzi nella tabella sono esadecimali. Le allocazioni hanno granularità 2MiB; il dato del test è una sola parola di quattro byte. Il controllo CPU legge soltanto quella parola delle finestre 1 e 3, tramite `resource1` aperta O_RDONLY e mappata PROT_READ. Non scrive nella BAR. I due pattern sono invece inizializzati nella VRAM della GPU proprietaria mediante CUDA, sincronizzati e riletti localmente prima del controllo CPU.

Entrambe le GPU restituiscono alla CPU prima **00003039**, poi **6b2d91e7**. Il valore iniziale 00003039 viene ripristinato e verificato prima dei test peer. Questi risultati con due pattern sullo stesso indirizzo rafforzano la corrispondenza tra finestra BAR1 fisica e parola della corretta allocazione; non sono soltanto letture casuali di una BAR aperta.

## Risultati P2P e PCIe

| Operazione reale | Dato osservato | Esito |
|---|---|---|
| A2000 legge Ada | edcba987 invece di 12346641 | Fallisce |
| A2000 scrive Ada | confronto con a5a42468 superato | Passa |
| Ada legge A2000 | edcba987 invece di 12346641 | Fallisce |
| Ada scrive A2000 | 00000000 invece di a5a42468 | Fallisce |

Il kernel di lettura applica XOR 12345678 al valore peer: edcba987 implica un carico di FFFFFFFF. Il dato locale iniziale e l'azzeramento prima della scrittura sono verificati; nella stessa direzione il controllo CPU, la lettura peer e la scrittura peer usano la medesima finestra senza rimappatura intermedia.

Le 102 acquisizioni coprono sei dispositivi in 17 gruppi: baseline, prima/dopo quattro letture CPU e prima/dopo quattro operazioni peer. Tutte leggono 4096 byte di configurazione, senza errore e con orologio valido. Le uniche variazioni sono:

| Momento | Dispositivi | Variazione |
|---|---|---|
| Dopo A2000 legge Ada | A2000 06:00.0 e D7 00:07.0 | PCI_STATUS 0010→2010 |
| Dopo Ada legge A2000 | Ada 01:00.0 e D1 00:01.0 | PCI_STATUS 0010→2010 |

Nessun nuovo cambiamento durante le letture CPU o le scritture peer. AER UES/CES, HeaderLog, RootStatus, DeviceStatus e SecondaryStatus restano invariati. I CES preesistenti ASMedia sono 00002000 su04 e 00002040 su05; DEVSTA iniziali 0009 e0000. **Non è corretto concludere che PCIe sia privo di errori:** il bit13 aggiunto è Received Master Abort. Per D1 e D7 il [datasheet Intel710723-003](https://cdrdv2-public.intel.com/710723/710723-003.pdf), rispettivamente §5.4/p439 e §12.5.4/p964, associa questo stato a una completion Unsupported Request ricevuta dal backbone.

Il bit è sticky: durante la scrittura successiva era già impostato, quindi l'assenza di un nuovo delta non prova la consegna della scrittura. Queste osservazioni non localizzano il componente che rifiuta la lettura e non distinguono definitivamente routing e interpretazione hardware del mapping.

## Tempi e integrità

`data_done` monotonic=13.702967246 precede tutte le liberazioni. Il kernel registra `context_exit_begin` a13.709723, mapping residui IOVAS a13.980038, quindi **270,315ms dopo**, e otto assert pIOVAS!=NULL a partire da14.004828. I 37 marcatori comuni hanno differenza mediana kernel−monotonic di0,006360104s. I diagnostici di teardown sono reali ma successivi ai confronti già stampati; non dimostrano che ogni operazione precedente del driver fosse corretta.

Sono stati ricalcolati tutti i digest dell'inventario acquisito, quelli del pacchetto di avvio e dei sorgenti. Sono inoltre stati verificati **direttamente nei contenuti dell'initramfs** gli hash di eseguibile, moduli RM/UVM, libcuda, init e helper preflight, confrontandoli con il manifest. Non si presume che un file attuale sul server coincida con quello avviato.

| Artefatto | SHA-256 |
|---|---|
| result.log | bd7eedead61200b08edebfafe7e3073cf0ae6988702b2a926e72cd5345b5871a |
| kernel.log | dbccf312d37906f5f71ba63be30aafbcc3a37ee4ff79b40b817e142fc5a6a63b |
| initramfs avviato | 55bb8c8b66e9c14ba78aff112a67002b8b17c1494c1f99b5738025833ad2e15f |
| eseguibile nel pacchetto | 096a7ffab425fdff4782af0908f599d611ba04842ecd290e50143b5106c35273 |

Il JSON contiene tutti i digest completi, le righe di evidenza e i delta. `hardware_boot_started=false` nel manifest è un campo prodotto durante la costruzione: il completamento effettivo è documentato dai log, non da quel campo precedente all'avvio.

**Limite decisivo:** il controllo CPU riuscito esclude un'apertura BAR1 completamente inattiva o estranea alla parola verificata in quelle finestre. Non certifica PTE hardware, cache/TLB, attributi del mapping, percorso del richiedente GPU o routing peer. Il problema Ada→A2000 rimane aperto; questa prova restringe le ipotesi senza dichiararlo risolto.
