> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Traccia PTE, BAR1 e indirizzi DMA — 21 ottobre 2026

Il pacchetto locale `../driver-instrumented/` ricostruisce una base pulita NVIDIA 595.99.02, applica le sole patch BAR1 minimal e dynamic storiche, quindi aggiunge registrazioni in `nvidia.ko` e `nvidia-uvm.ko`. Non cambia indirizzi, aperture, sincronizzazioni CUDA, permessi, mapping o cleanup. Non contiene indirizzi GPA/HPA fissi. Nessun modulo è stato compilato o caricato durante questa preparazione locale.

## Provenienza verificata

Archivio originale: `nvidia-595.99.02-original.tar.gz`, SHA256 `1174b28565fe8c0dff534a2588f4becd5e12c03465a70f347650a0d0fc9f23bc`. Tutti i sette file interessati corrispondono all'archivio completo autentico. `source-manifest.json` registra preimmagini, risultati e tre patch. `validated-complete-tree/build-manifest.json` documenta l'applicazione esatta su estrazione completa: nessun fuzz o adattamento automatico.

Non usare il vecchio albero `gpu-followup-20261020/p2p-driver/source/NVIDIA-open-gpu-kernel-modules-19f3b34`: contiene esperimenti successivi. La ricostruzione minimal+dynamic corrisponde ai sorgenti documentati e ai tre file del port dinamico. Il vecchio modulo con SHA `41a3025b63192242bda4f9eb692d8a000fc85850d009c45f679f9ef46f9bef80` non possiede un manifest completo sorgenti/toolchain: non è rivendicata una ricostruzione binaria identica.

## Compilazione CPU nella VM, a cura dell'operatore

Trasferire tutta la piccola cartella `driver-instrumented` esclusi `clean-tree`, `validated-complete-tree` e gli alberi `*-subset`. Il builder richiede soltanto i tre file patch, `strict_patch.py`, `source-manifest.json` e `prepare_and_build.py`.

```sh
python3 /mnt/llm/riscrivo/runtime/reports/p2p-tcss-bit-tests-20261021/driver-instrumented/prepare_and_build.py \
  --archive /mnt/llm/riscrivo/runtime/reports/gpu-followup-20261020/p2p-driver/nvidia-595.99.02-original.tar.gz \
  --output /mnt/llm/riscrivo/runtime/reports/p2p-tcss-bit-tests-20261021/driver-instrumented-build-01 \
  --kernel 7.0.0-38-generic --jobs 4 --build
```

Servono Python con `tarfile` data filter, compilatore, make e header del kernel indicato. Il comando non installa pacchetti, non esegue `modules_install`, non carica moduli e non interroga GPU. Rifiuta qualsiasi directory output esistente. Produce `build.log`, `build-manifest.json` e `modules/{nvidia.ko,nvidia-uvm.ko}`, verificando versione 595.99.02 e vermagic. In caso di errore conserva l'albero e il log; scegliere un nuovo output per una ripetizione completa. Senza `--build` prepara e verifica solamente i sorgenti.

Il test successivo deve caricare entrambi i moduli della stessa compilazione; il solo `nvidia.ko` non fornisce le righe UVM. Occorre registrare gli hash effettivamente inclusi nell'initrd e mantenere lo stesso probe sincronizzato con quattro byte, quattro confronti e deallocazioni differite. Il builder non prepara né arma tale avvio.

## Registrazioni e correlazione

| Evento `P2PTRC` | Informazione |
| --- | --- |
| `DMA_MAP` | BDF sorgente/destinazione, indirizzo CPU fisico in ingresso, indirizzo DMA in uscita, resource BAR, indirizzo bus BAR, scelta DMA API e stato. |
| `WINDOW_CREATE/REUSE` | Identificatore progressivo del mapping, handle memoria duplicata, istanze e ID GPU, descriptor, IOVA space, lunghezza, BAR1 fisica, offset finestra, indirizzo fisico e DMA. |
| `RM_REQUEST/RETURN` | Sessione e handle memoria, descriptor, GPU sorgente/owner, offset/dimensione e risultato del costruttore PTE. |
| `RM_PTE` | Prima PTE del mapping, versione/formato, aperture effettiva, validità, permessi, pagina, indirizzo inserito e indirizzo decodificato dalle funzioni NVIDIA, word grezze. |
| `UVM_ALLOCATION` | Handle utente e handle RM duplicato, UUID/nome GPU, GPU VA, dimensione e offset dell'allocazione. |
| `UVM_PTE` | GPU VA effettiva, handle RM, pagina, PTE grezza ricevuta da RM e indirizzo della pagina tabella destinataria. |
| `UVM_SUBMIT/MAP_COMPLETE` | Esito della submission e del wait già esistente; nessuna attesa aggiunta. |
| `WINDOW_DESTROY_BEGIN/DONE` | Stesso ID della creazione, per collocare il cleanup rispetto ai confronti e agli assert. |

Catena da confrontare: GPU VA (`UVM_PTE`) → handle RM (`UVM_ALLOCATION`) → descriptor (`RM_REQUEST`) → mapping ID/DMA (`WINDOW_CREATE`) → PTE RM e UVM. Identificare le GPU mediante UUID, BDF e GPU ID; non assumere che l'indice CUDA coincida sempre con `gpuGetInstance()`.

Per l'indirizzo dei quattro byte all'inizio dell'allocazione ci si aspetta:

```
window_phys = BAR1 fisica del peer + bar1_off
DMA_MAP.input = window_phys
WINDOW_CREATE.dma = DMA_MAP.output
RM_PTE.decoded = WINDOW_CREATE.dma + offset dell'allocazione
RM_PTE.raw0/raw1 = UVM_PTE.raw0/raw1 per lo stesso mapping
```

La prima pagina basta per il carico dei quattro byte, pur essendo l'allocazione VMM arrotondata alla granularità CUDA. La variante strumentata registra anche i mapping locali UVM: usare gli handle e le GPU, non la semplice vicinanza delle righe. `UVM_PTE.table_pa` è l'indirizzo della tabella PTE, non l'indirizzo target del trasferimento.

## Decodifica PTE da sorgenti NVIDIA

La decodifica nel log usa il formato runtime effettivo: `gmmuFmtPtePhysAddrFld()` seleziona il campo coerente con l'aperture e `gmmuFieldGetAddress()` estrae il campo e applica lo shift. Definizioni nell'archivio autenticato: `src/nvidia/inc/libraries/mmu/gmmu_fmt.h`, `src/nvidia/src/kernel/gpu/mmu/arch/pascal/kern_gmmu_fmt_gp10x.c` e `.../arch/turing/kern_gmmu_fmt_tu10x.c`. Non si assume che il nome dell'architettura nel percorso sia la GPU fisica.

Per il formato VER2 a otto byte, l'header ufficiale `src/common/inc/swref/published/pascal/gp100/dev_mmu.h` definisce valid bit0, aperture bits2:1, volatile bit3, readonly bit6, atomic-disable bit7, indirizzo SYS bits53:8 e shift12. Il controllo manuale dell'indirizzo SYS è quindi `((raw0 >> 8) & ((1 << 46) - 1)) << 12`, soltanto quando il formato/aperture del log lo confermano. RM può selezionare una larghezza diversa in funzione delle caratteristiche GPU: il `decoded` ottenuto dal descrittore runtime prevale sulla formula manuale. La HAL UVM Ampere eredita il formato Turing e modifica i livelli; non usare la vecchia PTE legacy definita in altri header Ampere.

## Limite probatorio

Questi dati verificano il valore costruito da RM, ricevuto da UVM e sottoposto al motore che aggiorna le pagine GPU. Non sono una cattura del TLP emesso sul collegamento né un readback hardware delle page table. Un PTE corretto più l'errore PCI osservato orienta verso il percorso PCIe, senza dimostrare da solo che l'indirizzo sul filo sia identico. Per le scritture, l'assenza di AER non prova la consegna. Gli header AER utili, se validi e non preesistenti, vanno correlati ai marcatori temporali del probe.

Il logging usa livelli visibili e modifica tempi/volume dei messaggi; è una prova diagnostica breve, non un benchmark. Registra una PTE per chiamata RM e per intervallo UVM, non ogni pagina. I difetti di cleanup noti sono intenzionalmente preservati per non cambiare due variabili contemporaneamente.

## Compilazione completata e analisi offline

Il manifest successivamente ricevuto conferma compilazione riuscita con GCC 15.2.0, kernel 7.0.0-38-generic e versione moduli 595.99.02. Hash prodotto `nvidia.ko`: `ab41b0a38e7ab92c0d1468b33c456c5c5c57501c67dfe5a666f49aed9fb6b1b5`; `nvidia-uvm.ko`: `9b993671ef066c9d3e58fd52b0d70228861769a2e3dcf304bc3d80bca089c4d0`. La verifica locale di manifest, sorgenti e log è in `../driver-instrumented/build-verification.json`. Nessun errore compilatore o avviso di formato nei tre file strumentati; sono presenti avvisi objtool su return/frame-pointer nel blocco OS-agnostic, avvisi di sorgenti stock e differenza pahole. Il build omette BTF perché manca vmlinux. Non è stato eseguito un confronto con una compilazione stock per attribuire ogni avviso.

Il parser locale legge soltanto due file esistenti:

```sh
python3 runtime/reports/p2p-tcss-bit-tests-20261021/driver-instrumented/analyze_p2ptrc.py \
  runtime/reports/p2p-tcss-bit-tests-20261021/native-instrumented-gpu-results
```

Produce `pte-chain-validation.json`, mantenendo righe sorgente, eventi completi, check superati/falliti/mancanti, confronti dati, variazioni PCI e correlazione temporale. Riconosce `PROBE_PTR` con indirizzi `%p` (`0x...`) e collega i puntatori alle GPU VA UVM. Senza questa riga usa esplicitamente un'inferenza temporale dalle fasi. La coerenza della catena osservata è distinta dalla correttezza dei quattro trasferimenti e dalla copertura completa del probe. Sei fixture sintetiche offline verificano che indirizzi troncati, PTE mutate, wait mancanti e log assenti non siano dichiarati successi.
