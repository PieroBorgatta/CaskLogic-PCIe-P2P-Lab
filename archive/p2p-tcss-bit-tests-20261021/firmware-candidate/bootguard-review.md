> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Boot Guard: evidenze e controllo nativo, 21 ottobre 2026

**La lettura UEFI nativa è completata: la macchina non riporta la capability Boot Guard secondo il criterio Intel usato da Slim Bootloader Alder Lake, e Verified Boot risulta zero. I due dump aggiornati identici confermano KM/BPM completamente vuoti.** La precedente lettura sotto Xen era indisponibile e non aveva valore conclusivo. Questi riscontri non certificano l'avviabilità del candidato SiInitFsp o l'assenza di ogni altro controllo del produttore.

## Evidenza statica direttamente verificata

Il file di partenza è `runtime/reports/gpu-followup-20261020/uefi-p2p/spi-backup-a.bin`, 33.554.432 byte, SHA256 `ad8ab9c0f7c2d09273bf4fe2f3b12be6cb203495f384f18a86e5d023ae5cfe9b`. Gli offset fisici corrispondono a `0xFE000000 + offset SPI`. Il puntatore FIT a `0xFFFFFFC0` seleziona `0xFFE90980`; le altre sequenze simili a FIT nel file non sono state considerate come tabella attiva.

La tabella selezionata contiene otto voci, tra cui Startup ACM, Key Manifest e Boot Policy Manifest. L'ACM a `0xFFF40000` ha header Intel, dimensione `0x26000`, data 28 ottobre 2022 e firma RSA presente. Questo descrive un modulo disponibile, non il suo impiego con enforcement verificato nell'avvio corrente.

| Oggetto puntato dalla FIT | Offset SPI del corpo | Lunghezza | Riscontro sui byte |
| --- | --- | --- | --- |
| BPM, FFS `C30FFF4A-10C6-4C0F-A454-FD319BAF6CE6` | `0x1F3F080` | `0xA00` | Tutti `FF` |
| KM, FFS `7C9A98F8-2B2B-4027-8F16-F7D277D58025` | `0x1F3FB00` | `0x400` | Tutti `FF` |

Quindi l'errore del parser su queste due voci non dipende semplicemente da una revisione del formato sconosciuta: i corpi raw sono interamente vuoti. Header FFS e padding circostanti non sono compresi nell'affermazione «tutti FF». Nel dump non compaiono le firme `__KEYM__`, `__ACBP__`, `__IBBS__` o `__PMSG__`. Offset, lunghezze, SHA256 dei corpi e del FFS SiInitFsp sono registrati in `bootguard-static-evidence.json`.

I due record AMI protected ranges v2 a `0x1F92C60` e `0x1FD2C60` contengono indirizzi, lunghezze e hash `FF`: non specificano intervalli validi in quei record. Non sono una misura dei fuse Intel e non dimostrano che qualsiasi controllo di integrità del produttore sia assente.

Il FFS SiInitFsp occupa `[0x1B02B60, 0x1B2883D)`, nel volume annidato `[0x1B00070, 0x1B5A070)`, dentro il volume esterno `[0x1B00000, 0x1BB0000)`. **Non esiste in questi slot una lista IBB valida con cui dimostrare che SiInitFsp sia escluso dalla verifica.** Il candidato modifica 72.228 byte compressi all'interno di questo solo FFS, pur modificando un solo byte nel PE decompresso.

Intel descrive una catena di verifica che coinvolge policy OEM fuse, KM, BPM e Initial Boot Block; l'IBB può verificare componenti successivi. Le policy fuse non sono leggibili direttamente dal BIOS: lo Startup ACM ne espone informazioni tramite BTG_SACM_INFO e ACM_POLICY_STATUS. La presenza dei file da sola non stabilisce la policy attiva. [Intel, Key Usage in Integrated Firmware Images, ID 790859](https://www.intel.com/content/www/us/en/developer/articles/technical/software-security-guidance/resources/key-usage-in-integrated-firmware-images.html).

## Perché il risultato Xen non basta

La lettura host di MSR `0x13A` ha restituito `EIO`, secondo il riscontro dell'operatore. Questo significa che non è stato ottenuto un valore utilizzabile; non significa «Boot Guard disabilitato».

Nel riferimento upstream Xen 4.17.5, una lettura MSR del dominio PV passa dall'emulazione: registri non riconosciuti possono produrre un'eccezione, oppure uno zero sintetico nei percorsi permissivi. `0x13A` non ha un caso di inoltro esplicito nei file esaminati. Pertanto anche uno zero da dom0 sarebbe insufficiente senza verificare il percorso concreto del fork XCP-ng installato. Questo confronto non certifica che il codice upstream coincida con tutti i patch del server. [Xen PV emul-priv-op.c](https://raw.githubusercontent.com/xen-project/xen/RELEASE-4.17.5/xen/arch/x86/pv/emul-priv-op.c), [Xen guest_rdmsr](https://raw.githubusercontent.com/xen-project/xen/RELEASE-4.17.5/xen/arch/x86/msr.c).

## Lettura UEFI nativa

`BootGuardRead.c` scrive esclusivamente `\EFI\CaskLogicTcssTest\native-security.txt`, sul filesystem dal quale è avviata l'applicazione. Il file è UTF-16LE con BOM. Ogni riga viene scaricata con `Flush`; `phase=start` e `phase=before_rdmsr_13a` precedono la lettura privilegiata. Controlla CPUID GenuineIntel, famiglia 6, modello `0x9A`, supporto MSR e bit hypervisor non impostato. Conserva la firma CPUID completa, quindi anche lo stepping osservato.

Legge MSR `0x13A` e registra sia il valore completo sia i campi seguenti. Queste definizioni corrispondono al codice di logging CBnT di coreboot; CHIPSEC non è stato usato come fonte dei bit MSR. [Coreboot, logging.c](https://raw.githubusercontent.com/coreboot/coreboot/main/src/security/intel/cbnt/logging.c).

| Campo MSR | Significato utilizzato |
| --- | --- |
| 0 | NEM |
| 2:1 | Tipo TPM |
| 3 | Esito TPM |
| 5 | Measured Boot |
| 6 | Verified Boot |
| 32 | Capacità Boot Guard, distinta dall'attivazione di Verified Boot |

I bit 5 e 6 non sono equivalenti: misurare il boot non implica necessariamente bloccare una modifica tramite verifica delle firme. Anche un riscontro nativo del bit 6 descrive lo stato osservato, non fornisce l'elenco degli intervalli IBB coperti.

L'app legge anche la finestra TXT pubblica. Convalida prima DIDVID a `0xFED30110`, richiedendo vendor `0x8086` e valore diverso da zero e da tutti uno. Solo allora legge ACM_POLICY_STATUS `0xFED30378` (64 bit), BOOTSTATUS `0xFED300A0` (64 bit) e ACM_STATUS `0xFED30328` (32 bit). Gli ultimi due restano grezzi per evitare decodifiche specifiche di altre generazioni. Base e offset sono confermati dalla configurazione TXT di [CHIPSEC, commit 0b0ab1228a56f687d947341cb35e731d00f9a8f4](https://raw.githubusercontent.com/chipsec/chipsec/0b0ab1228a56f687d947341cb35e731d00f9a8f4/chipsec/cfg/8086/TPM/txt.xml).

Intel specifica che ACM_POLICY_STATUS è leggibile dallo spazio pubblico e che la definizione completa dei bit varia per generazione. Dei campi pubblicati l'app interpreta soltanto TPM type `14:13` e S-CRTM status `34:32`, lasciando disponibile il valore grezzo. Non attribuisce ai bit bassi non documentati una presunta policy Verified/Measured. [Intel TXT Software Development Guide, ottobre 2025, appendice B.1.16, pagina 110](https://cdrdv2-public.intel.com/315168/315168_TXT_MLE_DG_rev_017_7.pdf).

Non vi sono WRMSR, scritture PCI/SPI, SetVariable, caricamenti driver, reset o cambiamenti del watchdog. La guardia CPUID limita l'impiego alla piattaforma prevista; non è presente un handler delle eccezioni CPU. Il marker precedente la lettura aiuta a distinguere un'interruzione prima del ritorno da un risultato completo. Una lettura MMIO non valida viene registrata e non trasformata in un «off».

| Riscontro | Conclusione sostenibile |
| --- | --- |
| MSR nativo valido, bit 6 = 1 | Verified Boot risulta attivo; nessuna esclusione del candidato dall'IBB è dimostrata da questi file. |
| MSR nativo valido, bit 6 = 0, bit 32 = 1 | Verified Boot non risulta attivo nell'osservazione; non garantisce da solo avviabilità o assenza di altri controlli. |
| EIO, valore nullo/tutti uno, file fermo prima della lettura | Stato non determinato. |
| Bit 5 = 1 o ACM presente nel dump | Non basta a concludere che Verified Boot sia attivo. |

La compilazione locale freestanding x86_64 con header GNU-EFI è riuscita con `-Wall -Wextra -Werror`. Non è stata eseguita alcuna lettura hardware dal computer di analisi. La lettura nativa e i due dump SPI aggiornati sono stati acquisiti separatamente dall'operatore.

## Risultato nativo acquisito e correzione del criterio

Il file `../native-read-results/native-security.txt` raggiunge `phase=complete`. Riporta CPUID `0x906A3`, vendor GenuineIntel e bit hypervisor zero; MSR `0x13A = 0x0000001000000000`; DIDVID `0x00000001B00C8086`; ACM_POLICY_STATUS, BOOTSTATUS e ACM_STATUS tutti zero. Nel MSR è impostato **il bit 36**, mentre capability bit 32 e Verified Boot bit 6 sono entrambi zero. Non è stata trovata una definizione pubblica primaria del bit 36 e non gli viene attribuito un significato inventato.

Il codice Intel di Slim Bootloader definisce capability come `BIT32`; `IsBootGuardSupported()` restituisce `FALSE` quando quel bit è assente. Quindi assenza della capability non equivale a errore della lettura. Questa non è solo una definizione tratta da una piattaforma precedente: `BoardConfigAdlP.py` eredita il Board Alder Lake, il cui `GetPlatformDsc()` seleziona proprio `CommonSocPkg/Library/BootGuardLibCBnT`. Le copie locali sono fissate al commit `fbcec1f60dfc887ea9da7fe50d7289d67e7c217c`, con hash in `bootguard-primary-source-manifest.json`. [Intel SBL BootGuardRegister.h](https://raw.githubusercontent.com/slimbootloader/slimbootloader/fbcec1f60dfc887ea9da7fe50d7289d67e7c217c/Silicon/CommonSocPkg/Library/BootGuardLibCBnT/BootGuardRegister.h), [IsBootGuardSupported](https://raw.githubusercontent.com/slimbootloader/slimbootloader/fbcec1f60dfc887ea9da7fe50d7289d67e7c217c/Silicon/CommonSocPkg/Library/BootGuardLibCBnT/BootGuardLibrary.c), [BoardConfig Alder Lake](https://raw.githubusercontent.com/slimbootloader/slimbootloader/fbcec1f60dfc887ea9da7fe50d7289d67e7c217c/Platform/AlderlakeBoardPkg/BoardConfig.py), [BoardConfig ADL-P](https://raw.githubusercontent.com/slimbootloader/slimbootloader/fbcec1f60dfc887ea9da7fe50d7289d67e7c217c/Platform/AlderlakeBoardPkg/BoardConfigAdlP.py).

Il manuale OEM Shuttle DH670, pagina numerata 10, mostra su un'altra macchina Alder Lake lo stesso valore SACM con gli stati TXT zero. È soltanto un riscontro aggiuntivo di plausibilità del valore, non una specifica del bit 36 e non una prova trasferibile della sicurezza del MS-01. [Manuale ufficiale Shuttle DH670](https://download.shuttle.eu/Mirror/MiniPC%26AIO/slim/DH670_DH670_V2/Manual/USER_MANUAL.PDF).

I dump `spi-current-a.bin` e `spi-current-b.bin`, entrambi 32 MiB, sono identici e hanno SHA256 `cfe6c07a4f2113928e13198ab2b8adc52924893aa0c239982c2213feb53c5124`. La verifica indipendente sui nuovi dump conferma i medesimi corpi BPM `0xA00` e KM `0x400` interamente `FF` alle posizioni indicate sopra. Il blocco originale di 19 settori coincide con il riferimento preparato. L'ACM presente senza manifest popolati, insieme allo stato nativo osservato e al criterio Intel, non evidenzia enforcement Boot Guard per questo avvio.

Il PRE v1 richiedeva capability bit 32 = 1 per ritenere valida la lettura: era un criterio eccessivo, perché confondeva supporto assente con lettura indisponibile. **Il PRE v2 corregge questo criterio usando soltanto il profilo nativo completo appena osservato su questa macchina**, senza un ramo generico permissivo. Richiede firma CPUID esatta `906A3`, assenza hypervisor, MSR esatto `1000000000`, DIDVID esatto `1B00C8086` e tre stati TXT zero; conserva inoltre un rifiuto esplicito per Verified Boot bit 6 attivo. Non modifica alcuna policy di sicurezza e non interpreta bit 36. Qualsiasi differenza da questo profilo interrompe il gate.

## Gate per i blocchi del candidato

`TcssRegionGate.c` è un'applicazione separata che verifica file e produce un marker; non programma firmware. I due riferimenti sono i blocchi di 77.824 byte già verificati:

| Nome da distribuire | Origine locale | CRC32 IEEE | SHA256 |
| --- | --- | --- | --- |
| `ORIGINAL.bin` | `SPI-01B16000-00013000.ORIGINAL.bin` | `2D0A1617` | `b60186e3126a68a06d2fa18cf6b1ac0bb357cab48c7ee06f48ce54a8d77f31e5` |
| `CANDIDATE.bin` | `SPI-01B16000-00013000.CANDIDATE-NOT-FLASH-READY.bin` | `AE93B05B` | `8c9cd7ecaf9ea50689bd70891eab0e36d66b8b36bf45e55b42f7e1c032ce574e` |

Le costanti sono compilate nel programma. Il CRC serve a riconoscere accidentalmente un file errato o corrotto, non costituisce una firma crittografica. Tutti i file devono misurare esattamente `0x13000` byte; è verificato anche EOF dopo l'ultimo byte atteso. Il confronto del readback è integrale byte per byte.

| Build | Input readback | Confronto | Marker dopo successo |
| --- | --- | --- | --- |
| Default PRE v2 | `region-before.bin` | Uguale a `ORIGINAL.bin`; entrambi riferimenti con CRC previsto; nuova lettura nativa CPUID/MSR/TXT uguale al profilo esatto sopra | `READY.flag` |
| `-DPOST_CHECK` | `region-after.bin` | Uguale a `CANDIDATE.bin`, con riferimenti validi | `VERIFIED.flag` |
| `-DRESTORE_CHECK` | `region-restored.bin` | Uguale a `ORIGINAL.bin`, con riferimenti validi | `RESTORED.flag` |

Tutti i percorsi sono fissi sotto `\EFI\CaskLogicTcssTest\`. La build PRE rilegge direttamente i registri, senza fidarsi di un vecchio file di stato. Ogni modalità elimina il proprio marker precedente prima di iniziare; PRE elimina anche gli altri due marker. Un errore di cancellazione interrompe il gate. La scrittura del nuovo marker deve completarsi, essere scaricata e chiusa correttamente; altrimenti si tenta la sua rimozione e viene restituito un errore. L'operatore deve considerare insieme il codice di uscita e il marker, usando una directory preparata per questa singola esecuzione. Prima di ciascun dump FPT deve rimuovere il precedente file di readback e verificare il codice di uscita del dump: il gate da solo non può distinguere un file corrente da un file vecchio identico.

I log sono `region-pre-gate.txt`, `region-post-gate.txt` e `region-restore-gate.txt`. Il marker PRE non prova possibilità di recupero o avviabilità: attesta soltanto i controlli elencati. Tutte le tre build compilano localmente con warning trattati come errori. SHA256 del sorgente v2: `16a095c6dc06ac2de484a40e9b32f76aed87302d27ae766d578ecc52256645d4`.

Il collaudo host `TcssRegionGate.host-test.c` include il sorgente reale e sostituisce soltanto i servizi UEFI con un filesystem in memoria. Sono passati 11 casi POST e gli stessi 11 RESTORE: lettura corretta in blocchi da 257 byte, CRC original/candidate errato, ultimo byte differente, file corto/lungo, file mancante, errore durante la lettura, errore di flush del flag, errore scrittura log e cancellazione del vecchio flag negata. Quest'ultimo restituisce errore anche quando il vecchio file resta presente, confermando la necessità di controllare il codice di uscita. Sono verificati anche il vettore standard CRC32 `123456789 → CBF43926` e i due blocchi reali. Risultati e hash sono in `TcssRegionGate.validation.json` e nei due log `TcssRegionGate.host-test-*.txt`. Il percorso PRE con MSR/MMIO è stato compilato, non eseguito dal collaudo host. Nessun test firmware o operazione remota è stato eseguito da questo sottocompito.
