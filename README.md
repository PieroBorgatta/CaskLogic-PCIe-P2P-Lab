<p align="center"><img src="docs/assets/casklogic-logo.png" width="230" alt="CaskLogic — logo originale"></p>
<h1 align="center">CaskLogic PCIe P2P Lab</h1>
<p align="center"><strong>Due GPU. Due rami PCIe. Un trasferimento che funziona in un solo verso.</strong><br>Indagine aperta su Minisforum MS-01, RTX 2000 Ada e RTX A2000 via USB4.</p>
<p align="center">
<img src="https://img.shields.io/badge/stato-NON_RISOLTO-d55b45?style=for-the-badge" alt="Non risolto">
<img src="https://img.shields.io/badge/NVIDIA-Ampere_%2B_Ada-76b900?style=for-the-badge&logo=nvidia&logoColor=white" alt="NVIDIA Ampere e Ada">
<img src="https://img.shields.io/badge/Intel-Alder_Lake_H-0071c5?style=for-the-badge&logo=intel&logoColor=white" alt="Intel Alder Lake H">
<img src="https://img.shields.io/badge/USB4-PCIe_tunneling-408d9d?style=for-the-badge&logo=usb&logoColor=white" alt="USB4 PCIe tunneling">
</p>
<p align="center"><a href="docs/technical-summary.en.md">English technical summary</a> · <a href="#risultati-che-contano">Risultati</a> · <a href="firmware/README.md">BIOS sperimentali</a> · <a href="docs/indice.md">Archivio</a></p>

![Topologia e risultato direzionale](docs/assets/topology.svg)

## Perché questo repository

Questo progetto raccoglie l'indagine di **Piero Borgatta / CaskLogic** del 20–21 ottobre 2026: prove CUDA, modifiche sperimentali NVIDIA RM/UVM, analisi BIOS/FSP, misure e risultati negativi. Lo scopo è permettere a chi conosce PCIe, Intel TCSS, USB4 o il driver NVIDIA di esaminare evidenze concrete e proporre il prossimo discriminante utile.

**Non è disponibile una correzione del P2P bidirezionale.** Una capability dichiarata, un registro modificato o un comando DMA completato non sono una prova di consegna corretta del payload. Le prove positive in un verso non qualificano la soluzione per produzione, atomiche, NCCL o training.

## Hardware e ambiente

| Elemento | Configurazione rilevata |
|---|---|
| Computer | Minisforum MS-01, Intel Core i9-12900H, CPUID `906A3` |
| BIOS | AHWSA 1.26; confronto statico con 1.27 |
| GPU interna | NVIDIA RTX 2000 Ada Generation, 16 GB, Ada, compute capability 8.9 |
| GPU esterna | NVIDIA RTX A2000, 12 GB, Ampere, compute capability 8.6 |
| Dock | AOOSTAR, alimentatore 800 W; AG02 plausibile, etichetta/revisione PCB non confermate |
| Bridge | Famiglia ASM2464, bridge PCI `1b21:2461` |
| Percorso | PEG interno ↔ fabric Intel ↔ TCSS/root USB4 ↔ bridge ↔ GPU esterna |
| Driver delle prove | NVIDIA 595.99.02, varianti sperimentali documentate separatamente |
| Ambienti | VM con passthrough su XCP-ng e Linux nativo temporaneo in RAM, senza Xen |

Il collegamento esterno usa **PCIe tunneling via USB4**, non normali trasferimenti USB. Nei test nativi Ada è `01:00.0`, A2000 `06:00.0`; non generalizzare gli indici CUDA ad altre macchine.

## Risultati che contano

Nella prova nativa qualificata PUSH/PULL si confrontano **tutte le parole** di payload da **4 B, 64 KiB e 1 MiB**, con inizializzazione e sincronizzazione dell'owner verificate.

| Dati trasferiti | Esecutore | SM: confronti corretti | CE: confronti corretti |
|---|---|---:|---:|
| PUSH Ada → A2000 | Ada | 0/3 | 0/3 |
| PUSH A2000 → Ada | A2000 | **3/3** | **3/3** |
| PULL Ada → A2000 | A2000 | 0/3 | 0/3 |
| PULL A2000 → Ada | Ada | 0/3 | 0/3 |

**18 errori su 24 confronti.** CUPTI osserva 12 operazioni CE e 12 SM, senza record persi; il primo PULL è CE e precede ogni lettura SM. CUPTI non è una cattura TLP e non prova da solo l'assenza di qualsiasi staging interno non esposto.

[Analisi completa PUSH/PULL](archive/p2p-next-investigation-20261021/native-pushpull-results/ANALISI.md) · [Log pubblico anonimizzato](archive/p2p-next-investigation-20261021/native-pushpull-results/result.log)

### Cosa è stato provato

| Famiglia di prove | Risultato e limite |
|---|---|
| Driver originale | CUDA peer non disponibile in entrambi i versi; alcuni report `nvidia-smi` indicano OK senza dimostrare trasferimenti |
| Patch libcuda e percorso BAR1 dinamico | Consentono esperimenti; non eliminano corruzione/assenza del dato |
| ACS, coerenza, NoSnoop, Relaxed Ordering, MPS, GPA/HPA | Nessuna matrice completa riuscita; alcuni tentativi incompleti sono etichettati come tali |
| Linux nativo senza Xen | L'asimmetria persiste; Xen non è una condizione necessaria |
| Sincronizzazione corretta | Rimedia a un limite dei primi test; l'asimmetria rimane dopo la correzione |
| BAR sotto 4 GiB, PTE/allineamento, UVM 4 KiB, SYS_COH | Nessuna risoluzione nelle varianti documentate |
| `SaSetup[0x3E3]`, FSP e CCFG PEG/TCSS | Bit effettivamente modificati e riletti; Ada→A2000 ancora errato; span FSP poi ripristinato |
| CE fisico, destinazione NONCOHERENT=2 / COHERENT=1 | Entrambi completano il comando, ma conservano lo stesso errore nel verso Ada→A2000 |
| NVML TX/RX con controlli positivi host↔GPU | Compatibile con mancata consegna lungo il percorso; contatori aggregati, nessuna localizzazione del singolo TLP |
| Firmware AOOSTAR e architetture GPU | Nessun aggiornamento ufficiale applicabile identificato; non dimostrata una regola «vecchia→nuova sì, nuova→vecchia no» |

Lo [storico completo](archive/p2p-tcss-bit-tests-20261021/STORICO-PROVE.md) distingue esecuzioni, timeout, tentativi senza dati e sole preparazioni. Il [rapporto conclusivo](archive/p2p-next-investigation-20261021/ESITO.md) e la [verifica AOOSTAR/architetture](archive/p2p-aoostar-architecture-20261021/ESITO.md) hanno precedenza sulle ipotesi dei documenti più vecchi.

## BIOS e driver inclusi

Sono disponibili **due immagini BIOS complete sperimentali** e **due regioni FSP candidate**, con hash, provenienza e stato delle prove. Il BIOS con menu modificato non è stato flashato. L'immagine completa PEG/TCSS è ricostruita offline dal BIOS OEM; la sua regione FSP è stata provata sull'esemplare originale, non l'intera immagine qui distribuita.

**Nessuno di questi BIOS risolve il difetto.** Le immagini non sono universali: un flash non compatibile può impedire l'avvio. Prima di qualsiasi uso occorrono identificazione esatta della scheda, backup proprio e recupero hardware disponibile. Il repository non esegue flash né modifica il server.

- [BIOS: contenuto, limiti e ricostruzione](firmware/README.md)
- [Driver RM/BAR1 strumentato](archive/p2p-tcss-bit-tests-20261021/driver-instrumented/)
- [Driver UVM CE fisico e contratto](archive/p2p-next-investigation-20261021/driver-physical-ce/README.md)
- [Riproduttori CUDA, analizzatori e prove offline](docs/riproducibilita.md)

I sorgenti storici sono un **archivio di ricerca**, non un installer portabile. Gli identificativi della macchina sono sostituiti coerentemente da valori fittizi: i controlli di identità restano presenti. La ricompilazione su un altro sistema richiede revisione esplicita di quei controlli e delle dipendenze, non la loro rimozione indiscriminata.

## Che aiuto cerchiamo

1. Documentazione Intel/OEM sul forwarding di Memory Write e Memory Read **PEG↔TCSS** su Alder Lake-H, inclusi controlli e fase di inizializzazione.
2. Conferma NVIDIA del supporto della coppia A2000 Ampere / RTX 2000 Ada e revisione dei metodi effettivamente emessi.
3. Informazioni AOOSTAR/ASMedia su revisione hardware, firmware e accettazione di traffico peer originato da un altro ramo PCIe.
4. Una proposta che distingua **GPU requester, fabric Intel e bridge USB4**, usando una traccia o un esperimento realmente discriminante.

Non è possibile scambiare le due schede o collegarle allo stesso switch PCIe. Un relay del payload attraverso RAM CPU non soddisfa l'obiettivo. Questi vincoli limitano anche ciò che possiamo concludere: architettura GPU e posizione nella topologia restano correlate.

[Apri una discussione tecnica tramite issue](https://github.com/PieroBorgatta/CaskLogic-PCIe-P2P-Lab/issues/new) allegando hardware, topologia, versioni e confronto dati, distinguendo chiaramente ipotesi e risultati.

## Navigazione e integrità

| Percorso | Contenuto |
|---|---|
| `archive/` | Rapporti, sorgenti, patch, risultati e verifiche storiche anonimizzati |
| `firmware/` | Immagini OEM modificate, regioni FSP e manifest delle varianti |
| `docs/` | Sintesi italiana/inglese, indice e riproducibilità |
| `provenance/` | Hash degli originali e delle copie pubblicate, esclusioni e controlli |
| `tools/` | Controlli locali di integrità e ricostruzione offline del BIOS |

```bash
python3 tools/verify_publication.py
python3 tools/replay_evidence.py
```

Questi comandi leggono file locali: non avviano GPU, non accedono via SSH e non scrivono firmware. Verificare che un analizzatore ricostruisca 18 errori **non** significa che il P2P funzioni.

Non sono pubblicati dump SPI/NVRAM personali, chiavi, credenziali, dischi delle VM, corpus o checkpoint. I log anonimizzati hanno hash differenti dagli originali; entrambi sono distinti nel manifest. I vecchi manifest interni rimangono documenti storici, non checksum delle copie modificate.

## Fonti e attribuzioni

- [Linux PCI P2PDMA](https://www.kernel.org/doc/html/latest/driver-api/pci/p2pdma.html)
- [Linux Thunderbolt/USB4](https://www.kernel.org/doc/html/latest/admin-guide/thunderbolt.html)
- [NVIDIA open GPU kernel modules 595.99.02](https://github.com/NVIDIA/open-gpu-kernel-modules/tree/595.99.02)
- [CUDA Peer Device Memory Access](https://docs.nvidia.com/cuda/cuda-runtime-api/cuda_runtime_api/group__CUDART__PEER.html)
- [Intel datasheet 710723-003](https://cdrdv2-public.intel.com/710723/710723-003.pdf)

Nessuna affiliazione o approvazione da NVIDIA, Intel, Minisforum o AOOSTAR. Marchio e logo CaskLogic appartengono al progetto dell'autore. Vedere [LICENSE.md](LICENSE.md) per distinguere materiali originali e componenti di terzi.
