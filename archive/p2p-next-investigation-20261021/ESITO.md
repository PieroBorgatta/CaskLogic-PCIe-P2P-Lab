> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# CaskLogic — indagine P2P RTX 2000 Ada / RTX A2000

**21 ottobre 2026: il P2P bidirezionale non è risolto.** Ho completato anche le nuove prove con un driver che emette copie fisiche privilegiate: Ada interna → A2000 esterna continua a restituire dati errati. Non esiste, fra le modifiche sviluppate e verificate, una correzione da installare permanentemente. Questa conclusione riguarda le prove svolte; non dimostra l’impossibilità assoluta di una correzione del produttore.

Sistema: Minisforum MS-01, i9-12900H, CPUID 906A3, BIOS AHWSA 1.26, RTX 2000 Ada interna su PEG e RTX A2000 12 GB tramite ASM2464 e tunnel PCIe USB4. Schede e collegamenti conservati. I controlli CPU delle allocazioni non costituiscono un trasferimento fra GPU attraverso RAM CPU.

## Controllo firmware individuato e prove precedenti

La [verifica firmware](firmware-review.md) ricostruisce la catena concreta `SaSetup[0x3E3] → EnablePeerMemoryWrite → SiInitFsp → D1:F0 CCFG`. Conduce al controllo già provato. Nel precedente lavoro sono state modificate davvero le istruzioni FSP che impostano CCFG D7 bit 25–27 e D1 bit 26, con rilettura dei registri:

| Registro | Originale ripristinato | Variante provata |
|---|---|---|
| D1:F0 CCFG | `04008077` | `00008077` |
| D7:F0 / D7:F2 CCFG | `0e009077` | `00009077` |

**La modifica effettiva dei bit non ha sbloccato Ada → A2000.** Lo span FSP modificato è stato successivamente ripristinato e confrontato byte per byte, con zero differenze. Non si afferma che tutto il BIOS e tutte le variabili NVRAM siano identici allo stato di fabbrica. I nuovi esperimenti qui descritti usano il FSP ripristinato e non hanno scritto la memoria SPI.

Il [rapporto precedente](../p2p-tcss-bit-tests-20261021/ESITO.md) e lo [storico delle prove](../p2p-tcss-bit-tests-20261021/STORICO-PROVE.md) conservano inoltre i confronti con sincronizzazione corretta, Linux nativo senza Xen, allineamento BAR1/PTE da 2 MiB, pagine UVM da 4 KiB, aperture SYS_COH, BAR sotto 4 GiB, NoSnoop/Relaxed Ordering e accesso CPU alla stessa finestra BAR1. Nessuna variante ha eliminato l’asimmetria. Le prime prove prive dei controlli successivi restano distinte da quelle qualificate.

Il confronto BIOS 1.26/1.27 trova SiInitFsp, SiInitPreMemFsp, ITbtDxe e Usb4CmDxe identici. Tre wrapper differiscono soltanto nella dimensione del buffer Setup. Alcune differenze dei moduli SiliconPolicy non sono state ricostruite semanticamente per intero: non si pretende di avere escluso ogni possibile controllo OEM. Non è emersa una nuova catena documentata policy → registro PEG/TCSS → effetto sul peer → fase di inizializzazione.

## Nuovi esperimenti conclusi

| Prova | Esito verificato |
|---|---|
| PUSH/PULL nativo, firmware ripristinato, 24 confronti | PUSH Ada→A2000: 6/6 errati. PUSH A2000→Ada: 6/6 corretti. PULL: 12/12 errati. |
| Qualificazione CUPTI dello stesso confronto | 12 CE e 12 SM realmente osservati, traccia completa, zero record persi; 48 controlli iniziali delle allocazioni corretti. Il primo PULL è CE prima di qualsiasi PULL SM. |
| Traffic1, quattro PUSH da 1 MiB | Due forward errati e due reverse corretti; baseline troppo breve, quindi contatori non usati come misura qualificata. |
| Traffic2, baseline di 2 secondi | Stessi risultati dati, quattro finestre qualificate, 624 campioni e 48 statistiche ricalcolate. |
| PHYS1, prima versione del driver fisico | Arresto nella validazione della memoria prima delle copie. Non è un esito negativo del trasferimento fisico. |
| PHYS2, destinazione fisica NONCOHERENT_SYSMEM=2 | SM e CE fisico Ada→A2000 errati; SM e CE fisico A2000→Ada corretti. Entrambi i CE completati. |
| PHYS3, destinazione fisica COHERENT_SYSMEM=1 | Identico esito: forward errato e reverse corretto con entrambi i motori; entrambi i CE completati. |
| Controlli separati host↔GPU in PHYS2 e PHYS3 | Otto controlli da 1 MiB corretti, otto finestre qualificate; tutti i contatori interessati rispondono al traffico positivo noto. |

Risultati: [PUSH/PULL](native-pushpull-results/ANALISI.md), [Traffic2](native-traffic2-results/ANALISI.md), [PHYS2](native-physical2-ce-results/ANALISI.md), [PHYS3](native-physical3-ce-results/ANALISI.md). I log grezzi sono conservati con manifest SHA-256; i controlli del protocollo sono distinti dal successo dei dati.

## Cosa fa il driver sviluppato

Il nuovo percorso UVM esegue una copia di **4 byte** fra allocazioni VMM già vive. Ricava gli indirizzi dal gestore NVIDIA, verifica proprietà, permessi, intervalli e finestra BAR1, mantiene i riferimenti necessari e usa un canale CE privilegiato. Non accetta indirizzi fisici arbitrari dall’utente e non converte silenziosamente il comando in una copia virtuale. Il dato finale è verificato dalla GPU proprietaria. Se il completamento diventa incerto, le risorse restano referenziate fino al riavvio dell’ambiente temporaneo.

La prima versione rifiutava il formato memoria KIND6; la correzione è stata verificata rispetto ai sorgenti NVIDIA, mantenendo il controllo esplicito dei permessi. PHYS2 e PHYS3 attraversano tutti i controlli e registrano la submission effettiva. In entrambe, classe `C7B5`, comando `04003186`, sorgente fisica LOCAL_FB=0 e indirizzi BAR1 coincidono fra log client, query del driver, mapping e metodi emessi. PHYS3 cambia soltanto il modo fisico destinazione da 2 a 1, oltre ai relativi controlli e nomi degli artefatti. [Motivazione e fonti NVIDIA](physical-aperture-followup.md).

**Il comando completato non equivale a un dato consegnato:** in entrambe le modalità la parola ricevuta dall’A2000 è errata. Quindi la nuova implementazione fisica non è una soluzione. Non è stata promossa a driver di sistema né qualificata per carichi applicativi, atomiche o produzione.

Per ciascuna delle due prove fisiche, 102 snapshot PCI non mostrano variazioni dei campi monitorati. Gli otto assert noti IOVAS compaiono dopo l’uscita dal contesto, oltre 350 ms dopo, non durante i confronti. Questo ne esclude quella particolare relazione temporale con i dati già falliti; non certifica l’assenza di ogni difetto del driver sperimentale.

## Diagnosi sostenibile e informazione mancante

Nel Traffic2 fallito TX Ada aumenta, mentre RX A2000 resta prossimo al baseline. PHYS2 e PHYS3 aggiungono il controllo positivo che mancava: RX A2000 sale da circa 290–296 a circa 3,12 milioni di kB/s dichiarati dall’API durante H2D corretto. Il contatore reagisce quindi al traffico host noto. Sono contatori aggregati: non identificano singoli pacchetti, indirizzi o payload e non localizzano il punto di perdita. [Semantica NVML](https://docs.nvidia.com/deploy/nvml-api/latest/api/group__nvmlDeviceQueries.html).

L’ipotesi principale resta una limitazione nell’instradamento o accettazione delle richieste fra Ada/PEG e A2000/TCSS, oppure un attributo con cui il requester le emette. Il punto preciso fra GPU, fabric Intel e tunnel/bridge non è dimostrato. Il fallimento anche con operandi fisici riduce il peso dell’ipotesi di sola traduzione virtuale, senza provare quale componente sia responsabile.

La documentazione Linux spiega che il P2P fra domini di gerarchia PCIe non è garantito dalla specifica generale. Non è una prova di impossibilità specifica su questo MS-01. [P2PDMA Linux](https://www.kernel.org/doc/html/latest/driver-api/pci/p2pdma.html). Analogamente, il limite PEG→DMI nel datasheet Intel non permette di equiparare automaticamente D7/TCSS a DMI. [Intel 710723-003, §2.15](https://cdrdv2-public.intel.com/710723/710723-003.pdf).

**Non ho un ulteriore candidato fondato da applicare autonomamente.** Per avanzare serve almeno una nuova informazione verificabile: una policy o sequenza di registri Intel/OEM specifica per PEG→TCSS sul 12900H, una traccia delle transazioni che localizzi il rifiuto, oppure un difetto NVIDIA individuato nei metodi effettivamente emessi. La domanda tecnica per Minisforum/Intel è se questo preciso percorso possa inoltrare Memory Write e Memory Read peer e quale controllo lo governi; a NVIDIA servono invece indirizzi, metodi e risultati del riproduttore. Questo è il punto di arresto tecnico dell’indagine disponibile, non una richiesta di ulteriore autorizzazione.

## Stato finale e conservazione

Tutti gli avvii temporanei di questa fase sono stati raccolti integralmente. PHYS3 conserva 19 file del backup ESP e 17 file di risultati grezzi, verificati sull’host e sul Mac prima della pulizia. Le sole voci EFI originali sono state ricontrollate, senza BootNext, e la directory di avvio temporaneo è stata rimossa. [Verbale di pulizia](native-physical3-ce-collection.json).

Al controllo delle **05:23 CEST**, la VM Docker è attiva; entrambe le GPU sono riconosciute, servizi Docker, ventole e persistenza attivi, nessun processo compute né Xid dall’avvio. Training inattivo e disabilitato. Il modulo NVIDIA di sistema conserva l’hash osservato prima di questa fase; ciò non ne certifica la provenienza stock. Windows rimane sospesa con il suo stato conservato: le assegnazioni attuali non permettono di riavviarla insieme a Docker nella RAM disponibile. Controllo operativo finale *(artefatto locale non pubblicato)*.

Durante le prove native i dischi delle VM non sono stati montati. Corpus, checkpoint e codice del training non sono stati modificati; non è stata eseguita una verifica integrale per hash di tutti i dati del server. Sorgenti e risultati restano nell’area `runtime/` esclusa da Git, con backup separati.

Repository GitHub, post Reddit ed email di presentazione erano subordinati a una soluzione verificata. Tale condizione non è soddisfatta: non sono stati pubblicati né inviati. Il risultato documentato è una diagnosi più circoscritta e un riproduttore aggiuntivo, non una correzione riuscita.
