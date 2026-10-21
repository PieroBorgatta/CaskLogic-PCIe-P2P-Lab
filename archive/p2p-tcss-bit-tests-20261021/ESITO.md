> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# CaskLogic — esito dell’indagine P2P Ada / A2000

**21 ottobre 2026. Il P2P bidirezionale non è risolto.** Le modifiche firmware hanno cambiato realmente i bit previsti, ma nessuna variante collaudata ha reso corretta la direzione RTX 2000 Ada interna → RTX A2000 esterna. Il codice FSP modificato per questi esperimenti è stato infine ripristinato, riletto e confrontato byte per byte. Gli avvii sperimentali sono stati rimossi dopo il backup completo. L’ultimo controllo operativo disponibile è delle **03:21 CEST**.

Topologia conservata: MS-01, i9-12900H, BIOS AHWSA 1.26; Ada interna, A2000 tramite ASM2464 e tunnel PCIe Thunderbolt/USB4. Nessuno scambio delle schede e nessun trasferimento fra GPU attraverso RAM della CPU presentato come soluzione P2P. I controlli CPU descritti sotto servono a verificare le allocazioni e le finestre, non a trasportare il payload peer.

## Risultato numerico più significativo

| Prova | A2000 → Ada | Ada → A2000 |
| --- | --- | --- |
| Kernel che legge VRAM locale e scrive VRAM peer, 4 B / 4 KiB / 64 KiB / 1 MiB / 8 MiB, tre ripetizioni | **15/15 corrette** | **15/15 errate**, incluse tutte le parole di ogni confronto |
| Confronto sullo stesso insieme di allocazioni: kernel SM e motore di copia CE, 4 B / 64 KiB / 1 MiB | **6/6 corrette** | **6/6 errate** |
| Letture remote nelle matrici sincronizzate | Errate | Errate |

La prova di sole scritture esegue per prima Ada → A2000 e non è preceduta da letture peer: il fallimento non richiede una lettura remota precedente. I 60 controlli locali delle allocazioni passano. [Analisi delle 30 scritture](native-push-gpu-results/ANALISI.md).

Nell’ultima prova **CUPTI osserva effettivamente sei operazioni CE e sei SM**, con traccia completa, zero record persi e confronto integrale dei dati. I 24 controlli iniziali delle allocazioni passano. Nessuna copia host è osservata dentro i casi di trasferimento, ma CUPTI non certifica ogni eventuale passaggio interno: non si rivendica una prova del percorso fisico completo. Il risultato negativo Ada → A2000 basta comunque a escludere questa implementazione CE come soluzione. Non è un benchmark di prestazioni. [Analisi CE/SM](native-ce-gpu-results/ANALISI.md), [risultati verificati](native-ce-gpu-results/verified-result.json).

## Cosa è stato modificato davvero

**Firmware:** individuato il codice di inizializzazione delle porte Thunderbolt D7 nel modulo SiInitFsp installato. La prima patch modifica la maschera dell’istruzione a offset PE `0x20304` da `FE` a `F0`, azzerando CCFG bit 25–27 sulle porte D7. La seconda cambia anche il byte a `0xF634` da `04` a `00` per il bit 26 della porta interna D1. Non sono offset da applicare a un BIOS diverso.

| Registro | Prima | Durante il firmware combinato | Dopo il ripristino finale |
| --- | --- | --- | --- |
| D1:F0 CCFG | `04008077` | `00008077` | `04008077` |
| D7:F0 / D7:F2 CCFG | `0e009077` | `00009077` | `0e009077` |

Le scritture a sistema avviato non avevano cambiato questi bit; le modifiche nel codice di inizializzazione li hanno cambiati e le riletture lo provano. **Azzerarli non ha abilitato il trasferimento richiesto.** Gli esperimenti non attribuiscono automaticamente ai tre bit una semantica di “abilitazione P2P Thunderbolt” non documentata per questo stepping.

**Driver:** usate varianti sperimentali RM/UVM e libcuda per superare il rifiuto software iniziale, esporre le finestre BAR1 e osservare le traduzioni. Corretto un difetto concreto di allineamento: BAR1 A2000 usava offset da 64 KiB incompatibili con la granularità PTE da 2 MiB scelta nel percorso sperimentale. Disabilitare `RM64KBBAR1Mappings` rende gli indirizzi allineati, ma non elimina i tre fallimenti. Sono state poi compilate e collaudate separatamente una variante UVM con pagine da 4 KiB e una variante RM con aperture SYS_COH. Nessuna risolve Ada → A2000. Le tracce PTE descrivono il software e non sono una cattura delle transazioni sul collegamento.

## Ipotesi sottoposte a verifica

| Ipotesi / intervento | Osservazione e limite |
| --- | --- |
| Sincronizzazione incompleta dei primi test | Individuata e corretta; seed e destinazioni verificati sulla GPU proprietaria prima dell’accesso peer. Tre operazioni errate su quattro persistono. |
| Xen / virtualizzazione | Lo stesso comportamento si riproduce con Linux nativo temporaneo, senza Xen. Xen non è necessario per riprodurre il guasto. |
| VT-d | Nella prova dedicata, la traduzione risulta disabilitata nell’unità DRHD dichiarata; BAR VT-d TCSS letti a zero. Non equivale a una verifica di ogni filtro interno alla piattaforma. |
| Indirizzi oltre 4 GiB | BAR1 A2000 ricollocata realmente a `0x80000000`, BAR3 a `0x90000000`, con finestre dei tre bridge coerenti. Stesso esito negativo. |
| Allineamento / dimensione pagina | Corretto l’allineamento da 2 MiB e poi provate pagine UVM da 4 KiB; errori peer invariati. |
| Finestra A2000 inaccessibile | La CPU legge e scrive correttamente la stessa parola BAR1 destinazione della scrittura peer fallita. Due pattern per GPU e ripristino della parola verificati. La raggiungibilità dalla CPU non dimostra quella dal requester GPU. |
| Cache o verifica D2H ingannevole | Lettura CPU della finestra subito dopo il completamento della scrittura peer e prima del D2H: Ada contiene il valore atteso, A2000 resta a zero. |
| NoSnoop / Relaxed Ordering | Cinque fasi sulle stesse allocazioni, scritture DeviceControl rilette e ripristino verificato: tre fallimenti su quattro in ogni fase. Un errore nel verificatore shell finale è stato riprodotto e distinto dal programma GPU completo; non viene nascosto. |
| Apertura SYS_COH | Quattro mapping con enum software 4 / campo hardware codificato 2 osservati nei PTE prodotti; stesso risultato negativo. Non prova tutte le combinazioni possibili di attributi. |
| Motore di copia diverso dai kernel | CE realmente osservato con CUPTI; la direzione Ada → A2000 fallisce anche con CE a tutte le tre taglie. |
| Errori IOVAS in chiusura | Nelle prove con marcatori completi compaiono dopo tutti i confronti e durante la chiusura del contesto. Non spiegano temporalmente i confronti già falliti; non viene escluso ogni altro difetto del driver sperimentale. |

Lo [storico verificato](STORICO-PROVE.md) indicizza anche le 25 varianti precedenti, distinguendo matrici complete, prove interrotte e tentativi senza confronto dati. Le prime prove prive di sincronizzazione esplicita mantengono quel limite; le conclusioni attuali usano le ripetizioni corrette. I report precedenti sono conservati, inclusa la [versione precedente di questo documento](ESITO-fase-precedente.md).

## Diagnosi e ciò che manca per una correzione

I dati restringono il problema alla consegna della richiesta peer attraverso il percorso Ada/PEG → A2000/TCSS, o al modo in cui il driver/requester la genera. **L’ipotesi principale è una limitazione di instradamento o accettazione sul percorso fra le due porte della piattaforma Intel. Il punto esatto non è dimostrato.** Il fatto che la CPU raggiunga la stessa finestra e che la direzione opposta funzioni è un indizio; non identifica da solo un filtro Intel, il tunnel USB4 o il requester NVIDIA.

La documentazione Intel 710723-003, §2.15, limita le scritture peer PEG alle porte PEG ed esclude PEG → DMI. D7/TCSS non va però equiparato a DMI senza una prova specifica: quella restrizione non dimostra da sola l’impossibilità assoluta su questa topologia. [Datasheet Intel](https://cdrdv2-public.intel.com/710723/710723-003.pdf). Anche Linux documenta che l’inoltro P2P fra root port non è garantito in generale. [Documentazione kernel P2PDMA](https://www.kernel.org/doc/html/latest/driver-api/pci/p2pdma.html).

La ricerca nei sorgenti pubblici Intel FSP e nel codice USB4 Linux non ha identificato un ulteriore controllo applicabile con catena verificata **policy → registro D1/D7 → effetto sul peer → fase di scrittura**. Le policy `CpuPcieEnablePeerMemoryWrite` e `CpuPcieRpPeerToPeerMode` esistono, ma non forniscono una nuova mappatura dimostrata per D7 nel BIOS OEM installato. I campi LTR, FPB e UFDM esaminati non sono una nuova abilitazione P2P verificata. Revisione dei controlli firmware *(artefatto locale non pubblicato)*, [analisi USB4](driver/USB4-ROUTING-ATTRIBUTES.md).

**Non dispongo quindi di una patch risolutiva verificata da lasciare installata.** Per proseguire oltre le ipotesi già provate serve nuova evidenza sul routing interno del 12900H/TCSS o una traccia delle transazioni che localizzi dove Ada → A2000 viene fermato. È un limite tecnico dell’indagine disponibile, non una mancanza di autorizzazione. Non è corretto inventare un altro bit riservato e descriverlo come una funzione individuata. Non sono state qualificate atomiche, carichi applicativi completi o stabilità in produzione del percorso sperimentale.

## Stato finale del server e conservazione

Ripristino finale completato e raccolto alle **03:19:24 CEST**, pulizia conclusa alle **03:19:41**. Span FSP `0x01b0b000`, lunghezza `0x1e000`: SHA256 originale `b81e705a87c89a668c4bbddd3538a82ccd5ebea4b156ce2d79762147310deba9`, **zero byte differenti** nella rilettura. Questa è la verifica dello span modificato, non l’affermazione che ogni byte di tutto il BIOS o ogni variabile NVRAM coincida con il firmware di fabbrica. Le impostazioni SaSetup precedenti non sono state riscritte da questo ripristino e non sono state rilette indipendentemente dal collettore finale.

Verificati 28 file della raccolta di ripristino e tutti i 47 file del backup completo degli strumenti EFI prima della rimozione. Rimangono le sole voci di avvio originali `0000,0001`, nessun BootNext, file originali di avvio invariati. [Rilettura firmware](native-sync-restore-results/restore-verification.json), [revisione indipendente](final-sync-independent-review-storico.json).

Al controllo delle **03:21 CEST**, la VM `01-Docker_A` è attiva, entrambe le GPU sono riconosciute dal driver di sistema 595.99.02, servizi Docker, ventole e persistenza attivi, nessun processo compute e nessun Xid registrato dall’avvio. Training inattivo e disabilitato. Non sono stati installati permanentemente i moduli sperimentali di questa continuazione. La sola coincidenza di `srcversion` non certifica la provenienza stock del modulo: il report conserva il percorso e l’hash osservati senza trasformarli in tale certificazione.

**La VM `03-Windows_11` è sospesa, con stato conservato.** Il tentativo di riprenderla mentre Docker è attivo è stato respinto per RAM insufficiente: assegnazioni attuali Docker 26 GiB, Windows 8 GiB, dom0 4 GiB su circa 32 GiB fisici. Non sono state ridotte le assegnazioni né eliminato lo stato sospeso. Non va descritta come operativa insieme a Docker.

Durante i boot di prova i dischi delle VM non sono stati montati; i risultati sono stati scritti nell’area di test. Corpus, checkpoint e codice del training non sono stati modificati dalle operazioni svolte. Questo descrive la portata degli interventi, **non una verifica integrale per hash di tutti i dati del server**. Report e backup restano disponibili sul Mac e sull’host. Controllo operativo finale *(artefatto locale non pubblicato)*.
