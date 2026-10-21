> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Candidato locale SiInitFsp — 21 ottobre 2026

**Preparato e verificato a livello binario; non scritto sul server e non qualificato come avviabile.** La preparazione non contiene SSH, accessi hardware o operazioni di programmazione. Il risultato è un esperimento sulla configurazione iniziale del controller, non una soluzione P2P già dimostrata.

## Modifica precisa

Nel PE SiInitFsp, GUID FFS `80a845ac-210f-43b0-995b-477be41ab4e8`, l'istruzione a RVA/offset file `0x20300` passa da `B9 88 CF FF FE` a `B9 88 CF FF F0`: cambia esclusivamente il byte `0x20304`, da `FE` a `F0`. La maschera AND passa da `0xFEFFCF88` a `0xF0FFCF88`; la differenza è esattamente `0x0E000000` (bit 25, 26, 27). La maschera OR `0x1077` resta identica. Non vengono modificati gli altri bit del registro da questa variazione.

Il chiamante costruisce il BDF D7 dai dati di presenza e dalla mappa delle funzioni e applica l'inizializzazione a **tutte le porte D7 presenti**, non soltanto a F0. Questa scrittura CCFG precede le operazioni su D8 e REGBAR `3E24`. La loro relazione con un lock attivo sul processore ADL-P specifico non è provata: nella lettura runtime D8 bit 23 era zero, mentre `3E24` restituiva `FFFFFFFF`. Non si può quindi attribuire il mancato effetto delle scritture runtime con certezza a quel lock. Anche la semantica P2P dei bit 25–27 su D7 ADL-P rimane un'ipotesi da verificare.

## Provenienza della baseline

Base integrale: `uefi-p2p/spi-backup-a.bin`, dump reale da 32 MiB, SHA256 `ad8ab9c0f7c2d09273bf4fe2f3b12be6cb203495f384f18a86e5d023ae5cfe9b`.

Per mantenere nel candidato di analisi l'abilitazione PEG P2P già applicata, la baseline locale include il successivo `NV-before.bin` a SPI `0x01000000` per `0x60000` byte, e il settore già letto dopo la scrittura `P2P-sector-after.bin` a `0x01024000`. Il dump NV successivo differisce in 73 byte dalla SPI più vecchia; il settore verificato aggiunge un solo cambiamento, SPI `0x010243F9`, `0 → 1`. I byte esterni a NV restano identici alla SPI originale. Questa è una **ricostruzione storica esplicita**, non un dump del contenuto attuale. Non usare l'immagine integrale per sovrascrivere le variabili correnti.

La patch firmware interessa un intervallo distante da NV. Prima di qualunque applicazione, i dump SPI aggiornati devono dimostrare che FFS e intervallo originale corrispondono ancora ai riferimenti qui verificati. L'operatore sta acquisendo quei dump separatamente.

## Ricomposizione e verifica

È stato usato UEFIPatch 0.28.0 disponibile in `driver-reference/UEFIPatch-0.28.0`; il file di patch limita la ricerca al GUID SiInitFsp e alla sezione PE32 (`10`). La sequenza cercata compare una sola volta nel PE originale.

Il confronto indipendente delle estrazioni con `uefi_firmware` comprende 2.969 oggetti per immagine: nessun oggetto aggiunto o mancante. Cambiano soltanto il PE (un byte) e gli otto contenitori che lo racchiudono. Tutti gli altri oggetti sono identici. UEFIExtract A75 rilegge il candidato senza nuovi errori attribuibili al modulo.

Le 72.228 differenze nella SPI sono tutte interne al medesimo FFS, conservato alla posizione `0x01B02B60`, con lunghezza invariata `154845` byte e header identico. Nessun byte esterno a questo FFS cambia rispetto alla baseline: quindi nessun altro modulo, ME, descriptor, payload TCSS/TBT, NV o dato identificativo viene modificato dalla patch. L'header PE ha checksum originale zero e directory dei certificati zero; questi campi restano identici. L'assenza di certificato PE non dimostra l'assenza di una protezione esterna al PE.

| Artefatto | SHA256 |
| --- | --- |
| PE originale | `de17fb9ae71e0cb04fa39102ed1895284640befb719b44ea45b498e29b0c928f` |
| PE modificato | `a5f000b4cda7cfa11167545a33c18783754623012170bab73a419f4128fa05a4` |
| Baseline ricostruita | `e2caf625b967aa0115c3e4704db4f65640c1a3eaa52098f1a86f13f9f45db5a5` |
| Candidato integrale di analisi | `0216b836faf40b4a4336b5ee9ef6b7eca285b81114ab6b5408eaf5a037534d51` |

Il minimo intervallo che comprende tutte le differenze con allineamento a 4 KiB è **`[0x01B16000, 0x01B29000)`**, lunghezza `0x13000` = 77.824 byte = 19 settori. I due blocchi estratti preservano anche i byte non modificati ai margini:

| Blocco | SHA256 |
| --- | --- |
| `SPI-01B16000-00013000.ORIGINAL.bin` | `b60186e3126a68a06d2fa18cf6b1ac0bb357cab48c7ee06f48ce54a8d77f31e5` |
| `SPI-01B16000-00013000.CANDIDATE-NOT-FLASH-READY.bin` | `8c9cd7ecaf9ea50689bd70891eab0e36d66b8b36bf45e55b42f7e1c032ce574e` |

Questi blocchi non costituiscono una procedura di flash. Il file originale è una copia per confronto e ripristino, non prova da solo che il recupero sia possibile dopo un mancato avvio.

## BootGuard, protezioni e recupero

Nell'analisi della SPI originale sono presenti un Startup ACM e riferimenti FIT a Key Manifest/Boot Policy; il parser non riesce a interpretare questi ultimi. I due file AMI v2 protected ranges riportano intervalli e hash interamente `FF`. Questo contenuto **non dimostra né l'abilitazione né la disabilitazione** di BootGuard; occorrono i riscontri nativi del processore/piattaforma acquisiti dall'operatore. Non sono stati modificati ACM, manifest, protezioni SPI o hash per aggirarli.

Una modifica al codice eseguito prima dell'avvio potrebbe impedire anche l'accesso alla shell UEFI. Una modalità di recupero indipendente dall'avvio dello stesso firmware non è stata confermata: resta un rischio tecnico da registrare. La disponibilità di un backup su disco o il successo della precedente scrittura NV non equivalgono a quella capacità di recupero. L'utente ha autorizzato esplicitamente il lavoro in autonomia; questo rischio non introduce una nuova richiesta di approvazione.

Rimangono da stabilire: stato di enforcement BootGuard; corrispondenza dei dump SPI aggiornati; possibilità di recupero; effetto reale della maschera sul registro dopo il boot; integrità P2P nelle due direzioni. Nessuna di queste condizioni viene dichiarata soddisfatta da questo repack.

## File di evidenza

- `patch-manifest.json`: provenienza, target, singolo byte e limiti.
- `repack-verification.json`: confronto completo degli oggetti e conteggio differenze per settore.
- `prepare_candidate.py`: ricostruzione locale e patch PE con controlli di hash.
- `verify_candidate.py`: confronto estrazioni e produzione dei blocchi locali.
- `SiInitFsp-CCFG-mask.patch.txt`: patch UEFIPatch limitata a GUID/sezione/sequenza.
- `uefiextract-candidate-analysis.log`: analisi strutturale con gli avvisi BootGuard già presenti nella sorgente.

Le prove statiche della call chain sono nel rapporto precedente `p2p-thunderbolt-firmware-20261020/firmware-analysis/TCSS-D7-analysis.md` e nel relativo JSON/disassembly. Il fallimento dei quattro tentativi runtime è registrato separatamente in `runtime-c6/result.json`.
