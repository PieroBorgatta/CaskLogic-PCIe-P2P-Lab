> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

> **Stato corrente, 21 ottobre 2026, 02:08 CEST: indagine ancora in corso, P2P non risolto.** Il firmware sperimentale combinato D1/D7 è attualmente applicato per i collaudi; il ripristino descritto più sotto è un evento precedente, seguito da una nuova applicazione. Le registrazioni sotto questa nota conservano la cronologia e non descrivono tutte lo stato attuale.
>
> Le prove corrette con sincronizzazione dei proprietari confermano tre operazioni errate su quattro. La correzione dell'allineamento BAR1 rende coerenti le pagine da 2 MiB ma non cambia l'esito. Il controllo CPU legge correttamente due pattern nelle finestre di entrambe le GPU. Un nuovo programma di sole scritture, senza precedenti letture peer, completa 30 trasferimenti: tutti i 15 A2000→Ada sono corretti fino a 8 MiB; tutti i 15 Ada→A2000 falliscono. È in preparazione la prova temporanea con BAR1/BAR3 A2000 sotto 4 GiB. Nessuna modifica a corpus, checkpoint o codice della run di training.
>
> Evidenze aggiornate: [sincronizzazione](native-sync-gpu-results/ANALISI.md), [allineamento](native-regalign-gpu-results/ANALISI.md), [controllo CPU](native-cpubar-gpu-results/ANALISI.md), [sole scritture](native-push-gpu-results/ANALISI.md). Stato operativo: [WORKSTATE.md](WORKSTATE.md).

# CaskLogic — P2P Ada / A2000: prove firmware del 21 ottobre 2026

**Verifica riaperta dopo la revisione del protocollo CUDA.** È stata individuata l'assenza di una sincronizzazione esplicita sulla GPU proprietaria fra l'inizializzazione/azzeramento e l'accesso dall'altra GPU. La causalità dei fallimenti non è dimostrata, ma occorre correggere il test e ripeterlo con gli stessi bit. Gli esiti sotto restano registrazioni reali, con questo limite aggiuntivo. Il ripristino delle 01:00–01:01 è verificato; una nuova applicazione dello stesso candidato e una prova corretta sono in preparazione.

**P2P non risolto. Sono stati realmente scritti e verificati due firmware: prima le porte Thunderbolt D7, poi anche la porta interna D1. I bit cambiano come previsto, ma le prove dei dati continuano a fallire in tre operazioni su quattro, anche in Linux nativo senza Xen e con IOMMU disabilitata. Il codice BIOS precedente è stato ripristinato e riletto byte per byte; eliminati gli avvii temporanei. La VM è tornata attiva con entrambe le GPU e il driver di sistema.** Ultima lettura dei registri ripristinati: 01:00:50 CEST del 21 ottobre 2026 (`2026-10-20T23:00:50 UTC`).

Questa fase segue l'autorizzazione esplicita a modificare e collaudare i bit. Integra, senza riscriverne retroattivamente gli esiti, la [ricerca firmware precedente](../p2p-thunderbolt-firmware-20261020/ESITO.md) e le prove storiche nei report `gpu-followup-20261020` e `gpu-audit-20261020`. Topologia e posizione delle schede sono rimaste invariate.

**Prima prova firmware, soltanto D7, registri rilevati alle 00:34:12 CEST.** Intel FPT ha riportato la scrittura riuscita; il blocco riletto corrisponde allo SHA256 del candidato `8c9cd7ecaf9ea50689bd70891eab0e36d66b8b36bf45e55b42f7e1c032ce574e` ed è stato prodotto `VERIFIED.flag`. Il server ha poi completato l'avvio. Le letture successive riportano:

| Percorso | Valore dopo l'avvio |
| --- | --- |
| D7:F0, ID `8086:466e`, D0 | `0x00009077` |
| D7:F2, ID `8086:462f`, D0 | `0x00009077` |
| REGBAR C6:D0 | `0x00009077` |
| REGBAR CE:D0 | `0x00009077` |
| ECAM D7:F0:D0 | `0x00009077` |
| D7:F0:D8 | `0x09320048`, invariato |
| D0 della porta interna | `0x04008077`, invariato |

Questo prova che la modifica all'inizializzazione ha cambiato i bit attesi e che il sistema ha avviato con quei valori. Le prove GPU successive, nella VM e in Linux nativo, mostrano che questa sola modifica **non corregge il P2P**. Esito della scrittura comunicato dal coordinatore dell'intervento; misure conservate nella [traccia dei registri dopo il riavvio](firmware-trial-registers.json).

**Prova GPU nella VM completata alle 00:35:47 CEST.** Il driver sperimentale dynamic e la libcuda patchata hanno consentito la prova reale; entrambi i gate hanno verificato D7:F0/F2 a `0x00009077` immediatamente prima delle operazioni. Su quattro confronti da quattro byte:

| Operazione fisica | Esito |
| --- | --- |
| A2000 legge memoria Ada | Errato: lettura tutta `FF` prima della trasformazione del test |
| A2000 scrive memoria Ada | Corretto |
| Ada legge memoria A2000 | Errato: lettura tutta `FF` prima della trasformazione del test |
| Ada scrive memoria A2000 | Errato: destinazione rimasta zero |

`TOTAL_FAILURES 3`, uscita 5. `cudaCanAccessPeer=true` ottenuto dal driver di prova non equivale a dati corretti. Il runner ha scaricato i moduli sperimentali, ricaricato quelli di sistema e ripristinato i servizi iniziali; `stock_restored=true`, nessun errore. Nessun Xid/assert/IOVAS nel log di questa prova. Evidenze: dati GPU *(artefatto locale non pubblicato)*, [risultato strutturato](driver/candidate/gpu-result.json), [letture durante i gate](driver/coordinator-events.json), [ripristino driver](driver/candidate/restore.json). La successiva ripetizione nativa è descritta qui sotto.

**Ripetizione nativa del primo firmware D7 completata: stesso risultato, tre errori su quattro.** Linux `7.0.0-38-generic` è stato avviato senza hypervisor, con `intel_iommu=off iommu=off`. Le quattro operazioni hanno riprodotto esattamente la tabella precedente: corretta soltanto la scrittura A2000 → Ada; entrambe le letture errate e scrittura Ada → A2000 errata. `TOTAL_FAILURES 3`, uscita 5. Le porte D7 sono rimaste a `0x00009077` prima del caricamento NVIDIA, dopo il caricamento e dopo la prova; D1 è rimasto a `0x04008077`. Questo esclude Xen come condizione necessaria per riprodurre il fallimento di questa configurazione. [Risultato nativo verificato](native-gpu-results/verified-result.json), [sequenza completa](native-gpu-results/result.log).

Nel log di questa prova nativa compaiono `iovaspaceDestruct_IMPL: 4 left-over mappings` e otto assert `pIOVAS != NULL` in `io_vaspace.c`, ai tempi monotoni 13,372954–13,399993 s. Non va estesa a questa prova l'assenza di anomalie registrata nella VM. Il log precedente non contiene marcatori sufficienti per ordinare ogni assert rispetto a ogni confronto e rilascio della memoria. Il nuovo programma rinvia tutti i rilasci fino al completamento dei quattro confronti e aggiunge marcatori di fase con orologio monotono, per distinguere i dati trasferiti dagli errori di pulizia del driver. Log kernel nativo *(artefatto locale non pubblicato)*.

**Secondo firmware combinato D7 + D1 scritto e verificato.** La lettura precedente alla scrittura coincide byte per byte con `CURRENT.bin`; quella successiva coincide con `CANDIDATE.bin`, SHA256 `c37f53eec3a5702d4a3e7b9d55bf382050100e324f2ec1210d9b98439cabedf4`. Il controllo successivo riporta zero byte differenti e ha prodotto `VERIFIED.flag`. Il server ha completato l'avvio. Controllo precedente *(artefatto locale non pubblicato)*, controllo successivo *(artefatto locale non pubblicato)*, conferma di rilettura *(artefatto locale non pubblicato)*.

| Registro dopo il secondo avvio, 00:51:43 CEST | Valore |
| --- | --- |
| D1:F0, ID `8086:460d`, D0 della porta interna | `0x00008077` |
| D7:F0, ID `8086:466e`, D0 | `0x00009077` |
| D7:F2, ID `8086:462f`, D0 | `0x00009077` |
| REGBAR C6:D0, CE:D0 e ECAM D7:F0:D0 | `0x00009077` |
| D7:F0/F2:D8 | `0x09320048`, invariato |

La seconda modifica ha quindi effettivamente azzerato anche il bit26 della porta interna. **Anche il risultato GPU combinato è ora disponibile: tre operazioni errate su quattro.** [Snapshot dopo il secondo avvio](firmware-d1-trial-registers.json).

Il pacchetto nativo aggiornato è costruito e i suoi hash locali sono verificati: kernel SHA256 `9f55ef7253055a9cf68f8a04323c93dead2fca617386d842fbde9ca7b178b27e`, initrd SHA256 `22a6535bb5bbb081bcedf7219f117d7c7177f75086393c842ad7432036f684a5`. Predispone un solo passaggio di quattro operazioni da quattro byte, rilascio differito di tutte le allocazioni e marcatori `CLOCK_MONOTONIC`/kernel. Controlla D1=`0x00008077`, D7:F0/F2=`0x00009077`; non scrive la configurazione PCI. Il manifest di costruzione conserva `hardware_boot_started=false`: descrive lo stato al momento della preparazione. L'esecuzione successiva è provata separatamente dallo stato di avvio e dai log freschi. Manifest del nuovo collaudo *(artefatto locale non pubblicato)*.


**Prova nativa del firmware combinato completata.** Avvio predisposto alle 00:55:58 CEST; log acquisiti al ritorno del server alle 00:58:35. Il kernel conferma IOMMU disabilitata e assenza di Xen. UUID, bus fisici e contenuti del pacchetto sono stati verificati. D1=`0x00008077`, D7:F0/F2=`0x00009077` prima del driver, dopo il caricamento e dopo i confronti. Le quattro operazioni da quattro byte riproducono esattamente la tabella precedente: corretta soltanto A2000 che scrive in Ada; entrambe le letture e la scrittura Ada → A2000 errate. `TOTAL_FAILURES 3`, `NATIVE_TEST_RC=5`, `PROBE_COMPLETED`, `SCRIPT_RC=5`. [Dati e controlli verificati](native-d1-gpu-results/verified-result.json), [log completo](native-d1-gpu-results/result.log).

Tutti i confronti sono terminati prima di qualsiasi rilascio esplicito della memoria. Allineando i marcatori comuni dei due orologi, i quattro mapping IOVAS residui compaiono circa 266 ms dopo l'inizio della chiusura finale; il primo assert circa 290 ms dopo. Il log kernel ha soppresso 15 marcatori per rate limit, mentre stdout conserva tutti i tempi: il confronto tiene conto di questo limite. Questi errori di chiusura non spiegano i tre fallimenti già completati. Non viene escluso un diverso difetto precedente nel mapping del driver. [Analisi temporale](native-d1-gpu-results/ANALISI.md).

La topologia rimane quella richiesta: RTX 2000 Ada interna, RTX A2000 esterna attraverso ASM2464 e Thunderbolt/USB4, su MS-01 con i9-12900H. La porta esterna è `0000:00:07.0`, ID `8086:466e`, PortID TCSS `C6`. Le prove precedenti avevano mostrato la stessa asimmetria anche senza Xen: passa la scrittura A2000 → Ada; falliscono la scrittura Ada → A2000 e le letture nelle due direzioni. Questo è il punto di partenza, non una nuova misura di questa sessione.

**Quattro tentativi runtime: nessun bit modificato.** Sul registro `C6:D0`, indirizzo fisico `0xFBC600D0`, sono state eseguite scritture MMIO allineate a 32 bit. Ogni tentativo è stato riletto attraverso REGBAR, ECAM e configurazione PCI esposta dal sistema; ripristino finale confermato. Nessun carico GPU è stato eseguito da questa sonda.

| Tentativo | Valore richiesto | Lettura immediata | Lettura dopo circa 50 ms |
| --- | --- | --- | --- |
| Azzeramento bit 25 | `0x0C009077` | `0x0E009077` | `0x0E009077` |
| Azzeramento bit 26 | `0x0A009077` | `0x0E009077` | `0x0E009077` |
| Azzeramento bit 27 | `0x06009077` | `0x0E009077` | `0x0E009077` |
| Azzeramento bit 25–27 | `0x00009077` | `0x0E009077` | `0x0E009077` |

Le prime riletture sono avvenute dopo 19,7–21,7 µs; quelle successive dopo 50,1–50,2 ms. Tutti e tre i percorsi hanno riportato lo stesso valore iniziale e finale. Sessioni: preflight alle `22:14:34 UTC`, lettura aggiuntiva alle `22:14:42 UTC`, esecuzione alle `22:15:08 UTC`. Evidenze: snapshot runtime *(artefatto locale non pubblicato)*, [risultati completi](runtime-c6/result.json), eventi *(artefatto locale non pubblicato)*.

Questo dimostra che il tentativo runtime non è efficace. **Non dimostra quale meccanismo impedisca la modifica.** `D8=0x09320048` ha il bit 23 a zero; `REGBAR+0x3E24` restituisce `0xFFFFFFFF`, valore non interpretabile come conferma di un lock attivo. Possibili campi non scrivibili, valori fissati all'avvio o altri vincoli restano da distinguere. [Letture dei registri](lock-observation-before.json).

**Prima modifica firmware D7: un solo byte del codice SiInitFsp.** Il disassemblato identifica il ciclo di inizializzazione D7 a `0x20692` e la scrittura D0 nella funzione chiamata a `0x207E8`. L'istruzione interessata, unica nel PE, è a RVA/offset file `0x20300`:

```text
Originale: B9 88 CF FF FE    AND mask = 0xFEFFCF88
Candidato: B9 88 CF FF F0    AND mask = 0xF0FFCF88
Byte modificato: 0x20304, FE → F0
Differenza della maschera: 0x0E000000, esattamente bit 25, 26, 27
OR invariato: 0x00001077
```

La variazione fa tentare l'azzeramento durante l'inizializzazione firmware, prima delle scritture D8 e `3E24` individuate nello stesso ciclo. Non cambia quelle scritture e non risulta una policy che consenta di saltare soltanto esse. La modifica interessa **tutte le porte D7 presenti**, non soltanto C6/F0. Non è dimostrato che preceda ogni eventuale vincolo del silicio.

La motivazione era discriminare una configurazione modificabile durante l'avvio da un campo non modificabile nemmeno allora. Il risultato ora acquisito dimostra che questa inizializzazione può azzerare i bit e conservarli fino alla lettura dopo l'avvio; i tentativi runtime precedenti non erano riusciti. **La funzione P2P dei bit 25–27 su D7 Alder Lake non è documentata con certezza dalle fonti pubbliche trovate:** l'ipotesi nasce dai campi analoghi PEG/D6 e dall'asimmetria misurata. Il candidato non è quindi una correzione P2P già provata. Specifica indipendente *(artefatto locale non pubblicato)*, [manifest della patch](firmware-candidate/patch-manifest.json).

**Seconda modifica firmware: un ulteriore byte nel ramo P2P della porta interna.** L'audit della catena di policy ha dimostrato che `SaSetup[0x3E2 + indice]` alimenta il flag P2P e che l'indice 1 identifica D1:F0. Con il flag attivo, il firmware originale conserva deliberatamente il bit26 nella maschera per le porte il cui helper restituisce un valore nonzero. Il candidato combinato conserva la prima modifica D7 e aggiunge:

```text
Offset PE 0xF62F, istruzione AND ECX, immediato:
Originale/corrente D7: 81 E1 00 00 00 04    AND ECX, 0x04000000
Combinato:           81 E1 00 00 00 00    AND ECX, 0x00000000
Byte modificato: 0xF634, 04 → 00
ADD successivo invariato: 0xF07FEF88
Maschera risultante per helper nonzero: 0xF47FEF88 → 0xF07FEF88
```

La variazione interessa soltanto il bit26 della maschera nel ramo P2P attivo; il ramo disattivo e il caso helper zero non cambiano. L'ambito è quello delle porte con helper nonzero e P2P attivo, **non una selezione rigida della sola funzione D1:F0**. La semantica esatta del bit26 su D1 Alder Lake-P non è confermata da una definizione pubblica primaria trovata; il campo di disabilitazione delle letture peer documentato su D6 non basta a provarla su D1. L'azzeramento è misurato; il collaudo nativo successivo non mostra miglioramento nei quattro trasferimenti. [Catena firmware D1](firmware-analysis-d1/D1-P2P-analysis.md).

Il candidato combinato contiene esattamente due byte di codice differenti dall'originale (`0xF634` e `0x20304`) e uno dal primo candidato D7. La verifica indipendente ha confrontato 2.999 oggetti per immagine: cambiano il PE e i suoi contenitori, nessun altro modulo. Header, posizione e dimensione del FFS restano identici; tutti i byte esterni al FFS sono identici. L'intervallo della seconda scrittura è `[0x01B0B000, 0x01B29000)`, 122.880 byte, 30 settori. Gli hash dei tre blocchi coincidono con le rispettive porzioni delle immagini complete; i controlli locali PRE/POST/RESTORE hanno superato 15/14/14 scenari. `ORIGINAL.bin` contiene il vero codice SiInitFsp precedente a entrambe le modifiche; il ripristino di questo intervallo non cambia la precedente impostazione SaSetup contenuta altrove. [Revisione indipendente](firmware-candidate-d1/independent-pe-review.json), [profilo dei blocchi](firmware-candidate-d1/flash-profile.json), [collaudi dei controlli](firmware-candidate-d1/TcssRegionGate.validation.json).

**Lettura nativa Boot Guard completata.** `BootGuardRead.efi` ha rilevato CPU Intel `0x906A3`, modello `0x9A`, bit hypervisor zero e supporto MSR. Risultati: `MSR 0x13A=0x0000001000000000`; `TXT DIDVID=0x00000001B00C8086`; `ACM_POLICY_STATUS`, `BOOTSTATUS` e `ACM_STATUS` tutti zero. Sono zero anche Measured Boot, Verified Boot e capability bit 32.

La libreria Intel collegata alla build Alder Lake-P interpreta capability zero come `BootGuardSupported=FALSE`, non come lettura invalida. Il solo bit 36 rimane senza una definizione primaria trovata; lo stesso valore compare nel manuale ufficiale Shuttle per un altro sistema Alder Lake. L'insieme delle evidenze **non mostra Boot Guard Verified Boot attivo su questo avvio**. Nel dump corrente i riferimenti FIT KM/BPM puntano a corpi interamente `FF`; anche i dati AMI protected ranges sono `FF`. Questi riscontri non garantiscono che il candidato avvii correttamente. Report nativo originale *(artefatto locale non pubblicato)*, interpretazione con fonti Intel *(artefatto locale non pubblicato)*, [audit SPI indipendente](firmware-candidate/fresh-independent-audit.json).

**Baseline precedente alle due scritture: due dump SPI coincidenti byte per byte.** Intel FPT `16.50.0.1120`, eseguito in UEFI, ha completato entrambe le letture da 32 MiB con esito positivo. SHA256 comune: `cfe6c07a4f2113928e13198ab2b8adc52924893aa0c239982c2213feb53c5124`. Il FFS SiInitFsp corrisponde all'originale già analizzato. Il primo candidato D7 mantiene esattamente i byte della baseline fuori dai 19 settori interessati, inclusi NV, ME e descriptor. Il precedente candidato basato su una ricostruzione storica è soltanto un artefatto di analisi; per il confronto corrente valgono i nuovi dump. [Verifica dump correnti](fresh-spi-verification.json).

| Riferimento del primo candidato D7 | Valore |
| --- | --- |
| FFS SiInitFsp | `80a845ac-210f-43b0-995b-477be41ab4e8` |
| Intervallo SPI interessato | `[0x01B16000, 0x01B29000)`, 77.824 byte, 19 settori |
| SHA256 blocco originale | `b60186e3126a68a06d2fa18cf6b1ac0bb357cab48c7ee06f48ce54a8d77f31e5` |
| SHA256 blocco candidato | `8c9cd7ecaf9ea50689bd70891eab0e36d66b8b36bf45e55b42f7e1c032ce574e` |
| SHA256 candidato integrale su dump corrente | `1ddc33f1e8164e1e0ee888886ebc6b709ba2c266daf69685d27b3e5a3219bdf2` |

**Verifiche degli strumenti e del primo pacchetto D7.** UEFIPatch `0.28.0` ha ricomposto il modulo; UEFIExtract A75 e il confronto indipendente con `uefi_firmware` hanno verificato la struttura. Sui dump correnti sono stati confrontati 2.999 oggetti per immagine, senza aggiunte o rimozioni: cambia soltanto un byte nel PE, oltre ai contenitori che lo racchiudono. La ricompressione produce 72.228 byte fisicamente differenti, tutti nel FFS originale, con posizione, dimensione e header invariati. Non sono 72.228 modifiche al codice.

Le verifiche locali dei controlli dopo scrittura e dopo ripristino hanno superato 11 scenari ciascuno. Il percorso nativo precedente alla scrittura è stato compilato e revisionato; queste prove locali non sostituiscono l'esecuzione sulla macchina. La revisione dello script UEFI ha controllato la cancellazione dei risultati precedenti, i codici d'uscita, le riletture nuove e il confronto esatto prima di dichiarare scrittura o ripristino riusciti. Il pacchetto registrato in stato di preparazione della prova firmware *(artefatto locale non pubblicato)* usa l'intervallo dei 19 settori. Il recupero fisico indipendente non risulta confermato nei metadati. [Verifiche dei controlli](firmware-candidate/TcssRegionGate.validation.json), [revisione script UEFI](firmware-candidate/shell-independent-review.json).

Per i collaudi GPU descritti è stata identificata e verificata staticamente la build NVIDIA dinamica `595.99.02`, kernel `7.0.0-38-generic`, senza le successive patch di indirizzi Xen fissi. Il test predisposto verifica letture e scritture di quattro byte nelle due direzioni; non misura banda e non equivale a una qualifica completa del driver. La compilazione o l'audit del modulo non costituiscono una nuova prova GPU riuscita. [Audit build](driver/build-audit.json), [procedura del collaudo mirato](driver/PERCORSO-MINIMO.md).

**Revisione finale del mapping.** Il binario dinamico usato non contiene gli indirizzi Xen fissi delle varianti successive. L'analisi del port e del disassemblato non individua un calcolo di indirizzo concretamente errato prima dei confronti per cui esista già una patch puntuale motivata. Il problema di cleanup è reale e va corretto prima di qualunque driver utilizzabile stabilmente; non spiega retroattivamente questi trasferimenti. Non sono state certificate le PTE effettive della prova nativa: rimane quindi aperta anche questa parte della diagnosi. [Revisione finale con riferimenti al codice](driver/final-mapping-review.md).

**Ripristino concluso e verificato.** Alle 01:00:50 CEST il server è tornato ai valori D1=`0x04008077`, D7:F0/F2=`0x0E009077`, confermati anche attraverso REGBAR ed ECAM. Il blocco di 122.880 byte riletto dalla SPI coincide integralmente con quello precedente a entrambe le modifiche, SHA256 `b81e705a87c89a668c4bbddd3538a82ccd5ebea4b156ce2d79762147310deba9`. Il controllo UEFI riporta zero byte differenti e `ORIGINAL_RESTORED_AND_READBACK_VERIFIED`. Conservata la precedente impostazione SaSetup P2P, esterna al blocco ripristinato. [Rilettura dei registri](final-registers.json), controllo della SPI *(artefatto locale non pubblicato)*.

Rimossi soltanto i tre avvii temporanei e le relative directory EFI dopo averne conservato le evidenze. Ordine di avvio originale `0000,0001`, nessun BootNext; file di avvio originali invariati. La VM è attiva, entrambe le GPU sono visibili con NVIDIA `595.99.02` dal percorso di sistema; ventole e persistenza attive, training inattivo e disabilitato come prima delle prove, nessun processo CUDA in esecuzione. Non sono stati modificati modello, tokenizer, codice di training o file tracciati Git. [Verifica della pulizia](cleanup-verified.json), stato finale osservato *(artefatto locale non pubblicato)*.

**Conclusione tecnica.** I bit 25–27 di D7 e il bit26 di D1 sono modificabili durante l'inizializzazione BIOS; i tentativi a sistema avviato non li cambiavano. Il loro azzeramento non rende corretto il P2P con la configurazione e il driver collaudati. Sono quindi insufficienti come soluzione. Non è dimostrata l'impossibilità assoluta del percorso hardware, né l'assenza di altri controlli firmware o difetti di mapping. La parte ancora da risolvere è individuare quale passaggio rifiuti o indirizzi male le transazioni peer fra i due root. Le fonti pubbliche e le prove disponibili non identificano ancora una correzione verificata per quel passaggio. Nessun risultato di capability software viene presentato come trasferimento funzionante.
