> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Prova nativa sincronizzata: tre fallimenti confermati, nuovo RMA nelle letture

Esito: quattro verifiche locali dei proprietari passano; tre delle quattro operazioni peer falliscono. La correzione della sincronizzazione non risolve il problema. Il test termina con TOTAL_FAILURES 3, NATIVE_TEST_RC=5 e PROBE_COMPLETED; non è un arresto del test prima dei confronti.

La novità diagnostica è precisa: ciascuna lettura fallita imposta PCI_STATUS bit13 sul richiedente e sul suo root port. AER non cambia. Non è quindi corretto descrivere il percorso PCIe come privo di errori.

## Identità e condizioni verificate

Kernel nativo Linux 7.0.0-38-generic, NVIDIA Open Kernel Module 595.99.02, CPU i9-12900H family6/model9A/stepping3; il kernel conferma DMAR: IOMMU disabled. La macchina è identificata come Venus Series/AHWSA BIOS1.26. La prova non gira dentro Xen.

L'init imposta CUDA_DEVICE_ORDER=PCI_BUS_ID. I dispositivi e i root port rilevati sono:

| CUDA | GPU | Endpoint | Root port |
| --- | --- | --- | --- |
| 0 | RTX 2000 Ada Generation, 16GB | 01:00.0, 10de:28b0 | 00:01.0, 8086:460d |
| 1 | RTX A2000 12GB | 06:00.0, 10de:2571 | 00:07.0, 8086:466e |

I bridge intermedi 04:00.0 e 05:00.0 sono entrambi 1b21:2461. I BAR1 nativi sono Ada 0x4000000000–0x43FFFFFFFF, A2000 0x4600000000–0x460FFFFFFF.

Il log verifica tre volte, prima del modulo, dopo il modulo e dopo il test: D1 CCFG=00008077, D7F0=00009077, D7F2=00009077. Le modifiche firmware combinate erano effettive durante questa prova.

## Dati osservati

Prima di usare ogni GPU come proprietaria, la copia H2D è sincronizzata e riletta localmente; prima della scrittura peer il contenuto azzerato viene ugualmente sincronizzato e verificato. Tutti i quattro OWNER_CHECK hanno valid=1: due valori iniziali 00003039 e due valori azzerati 00000000.

| Operazione reale | Risultato numerico | Esito |
| --- | --- | --- |
| A2000 legge memoria Ada | edcba987 invece di 12346641 | Fallisce |
| A2000 scrive memoria Ada | confronto con a5a42468 superato | Passa |
| Ada legge memoria A2000 | edcba987 invece di 12346641 | Fallisce |
| Ada scrive memoria A2000 | 00000000 invece di a5a42468 | Fallisce |

Il kernel di lettura applica XOR12345678 al dato remoto: edcba987 implica un valore letto FFFFFFFF. Il risultato non è semplicemente la copia del valore locale iniziale sbagliato, che è stato verificato prima della lettura.

Il log indica PEER can=1 in entrambi i versi, ma ciò resta una capacità dichiarata dal driver modificato, non una garanzia di trasporto.

Un confronto restringe ulteriormente l'ipotesi di mapping sbagliato: nella prima coppia A2000 legge e poi scrive lo stesso puntatore src appartenente ad Ada, senza rimappatura intermedia. La lettura riceve il rifiuto, la scrittura sul medesimo mapping funziona dopo azzeramento e controllo locale. Un semplice indirizzo BAR errato non spiega bene questa differenza tra tipi di transazione. Questa è un'inferenza dal sorgente e dai risultati, non la lettura dei PTE runtime; il mapping opposto verso A2000 resta da verificare perché falliscono entrambe le operazioni.

## Differenze PCIe, operazione per operazione

Acquisite 54 righe: sei dispositivi per nove fasi, con baseline e prima/dopo ciascuna delle quattro operazioni. Tutte le letture config restituiscono 4096byte senza errore; tutti gli orologi risultano validi.

| Fase dopo l'operazione | Uniche differenze rispetto alla fase prima |
| --- | --- |
| read_0_to_1: A2000 legge Ada | PCI_STATUS 0010→2010 su D7 00:07.0 e A2000 06:00.0 |
| write_1_to_0: A2000 scrive Ada | Nessuna |
| read_1_to_0: Ada legge A2000 | PCI_STATUS 0010→2010 su D1 00:01.0 e Ada 01:00.0 |
| write_0_to_1: Ada scrive A2000 | Nessuna nuova differenza |

Il bit aggiunto è 13, Received Master Abort. Il [datasheet Intel710723-003](https://cdrdv2-public.intel.com/710723/710723-003.pdf) lo definisce esattamente, sia per D1 (§5.4, pagina439) sia per D7 (§12.5.4, pagina964), come indicazione che il root port ha ricevuto dal backbone una completion Unsupported Request.

Questa evidenza sostiene il rifiuto delle richieste di lettura sul percorso verso il sistema. Non localizza da sola il componente che produce il rifiuto e non distingue definitivamente un limite di routing peer da un indirizzo errato nel PTE. Serve ancora verificare l'indirizzo runtime effettivo prima di escludere quest'ultimo caso.

UES, CES, HeaderLog, RootStatus, DeviceStatus e SecondaryStatus non mostrano nuove variazioni nei nove gruppi acquisiti. Gli errori correggibili dei bridge esistono già nella baseline: CES=00002000 su04 e CES=00003040 su05; DEVSTA=0009 e0001 rispettivamente. Non sono effetti attribuibili a questa singola operazione.

La scrittura fallita Ada→A2000 avviene dopo la lettura fallita Ada←A2000: RMA è già sticky. L'assenza di una nuova differenza nella scrittura non dimostra consegna corretta né esclude un evento che usi un bit già impostato. HeaderLog resta tutto zero; non è disponibile una cattura dei TLP o dei loro indirizzi.

La risposta NVIDIA sui processori client Intel con sole scritture P2P è coerente con queste letture rifiutate, ma non prova da sola il comportamento della topologia esatta. Il problema ancora necessario per un trasporto P2P a scritture è Ada→A2000.

## Gli assert IOVAS seguono i confronti

Marcatori monotonic del programma:
- data_done: 13.183113350;
- prima liberazione: 13.183114668;
- cleanup_done: 13.183494064;
- context_exit_begin: 13.183494617.

Tutte le quattro liberazioni avvengono dopo i quattro confronti. Il kernel registra quattro mapping residui a13.471760 e otto assert pIOVAS!=NULL tra13.497710 e13.499833.

I dieci marcatori comuni permettono di allineare i due orologi: kernel meno monotonic ha mediana0.0063630905s, con intervallo0.006362678–0.006374957s. Dopo questa correzione, il primo messaggio IOVAS è circa281.902ms dopo context_exit_begin e il primo assert307.852ms dopo. Il kernel segnala19marcatori successivi soppressi per rate limiting; i marcatori stdout sono presenti. L'allineamento non richiede di fingere che tutti i marcatori compaiano anche nel kernel.

Gli errori di teardown rimangono reali e il driver non è ancora idoneo a un uso stabile. La loro tempistica non spiega i valori già confrontati. Questa analisi non certifica l'assenza di altri difetti di mapping.

## Integrità e riproducibilità locale

analyze_native_sync.py rigenera verified-result.json senza accesso hardware. Sono stati ricalcolati localmente13SHA256 e verificata la corrispondenza con build-manifest e stato di armamento per kernel/initrd, sorgente, eseguibile, header, init e modulo. Tutti i digest completi, le54righe strutturate, i delta e i riferimenti alle righe originali sono nel JSON.

| Artefatto | SHA256 completo |
| --- | --- |
| result.log | d28a4b81d5fe5fda9f8e4954c78ef8ad0b6b8d5d8f1c9468be214a5a94a07a53 |
| kernel.log | 63d91cd4bd351ef4955faf246581216a4a9ca95c6052216acea97ecf2bf2dc70 |
| probe-initrd.img | 3d67a0e0d014e44597d764f0fbb6a65878b7a1d3116bbee8617f6410f84d90e4 |
| peer_vmm_word_sync_native | 226ac737d3c55fdfd24790b17ad46a98c2d46752cc08f2b2541a0dac17f9b0ee |
| peer_vmm_word_sync.cu | 0b8dfdbfa3a1235a563f987d8c64093cff92e506e72ec1e5738e064629462972 |
| pcie_diag.h | 4820c6c0f296c9af7bb75403885f860a3f8d1837d0aed1e625143258001358ae |
| nvidia-dynamic.ko | 41a3025b63192242bda4f9eb692d8a000fc85850d009c45f679f9ef46f9bef80 |

La libreria CUDA ha SHA03271500dbda9456e3ba765270bd2609bef2631672809da50b19c67fb1f609a7 nel manifest di costruzione; non è stata estratta e ricalcolata separatamente in questa revisione. Non è stato modificato alcun sorgente del test o del driver durante l'analisi.

La lacuna di sincronizzazione dei proprietari è esclusa come spiegazione unica dei tre fallimenti. Il P2P bidirezionale resta non risolto; non è stata dimostrata un'impossibilità definitiva.

