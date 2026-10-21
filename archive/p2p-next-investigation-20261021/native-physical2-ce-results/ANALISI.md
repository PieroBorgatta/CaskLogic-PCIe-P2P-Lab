> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# PHYS2: CE fisico completato, asimmetria invariata

Il protocollo è completo: quattro confronti P2P, due comandi CE fisici completati e quattro calibrazioni CPU/GPU valide. Il trasferimento Ada → A2000 fallisce sia con SM sia con CE fisico. A2000 → Ada riesce con entrambi. Il problema P2P bidirezionale non è risolto.

| Direzione | Motore | Confronto di 4 byte |
|---|---|---|
| Ada → A2000 | SM | FAIL: rimane il valore iniziale `0877b6da`, atteso `f7884925` |
| Ada → A2000 | CE fisico | FAIL: rimane lo stesso valore iniziale `0877b6da` |
| A2000 → Ada | SM | PASS, atteso `0c69f37a` |
| A2000 → Ada | CE fisico | PASS, atteso `0c69f37a` |

Il programma termina con `protocol_complete=1`, `physical_completed=2`, `qualified_windows=4`, RC5 per i due confronti falliti. È un risultato hardware effettivo, diverso dal precedente PHYS1 che si era fermato durante VALIDATE senza eseguire copie.

## Comandi e indirizzi verificati

La revisione correla UUID/BDF, VA, handle duplicati RM, oggetti dell'allocazione, PTE, finestre BAR1, query fisiche e metodi registrati dal kernel. Le query sono richieste esplicitamente ReadWrite e riescono prima dei metodi CE. Tutte le guardie registrano `ffff`; i metadati effettivi sono KIND6, formatoDefault, mapping_type1, pagina2MiB e offset0.

| Direzione | VA sorgente → destinazione | Fisico sorgente → BAR1 destinazione | Finestra |
|---|---|---|---|
| Ada → A2000 | `772022e00000` → `402800000` | `0a000000` → `4600400000` | 2 |
| A2000 → Ada | `402000000` → `772023600000` | `09c00000` → `4000400000` | 1 |

Entrambe le operazioni usano C7B5, canale GPU-to-GPU privilegiato, `LAUNCH_DMA=04003186`, sorgente fisica LOCAL_FB0 e destinazione fisica NONCOHERENT_SYSMEM2. Il kernel registra `no_virtual_fallback=1`, `status=0`, `flags=77`. Gli indirizzi fisici locali coincidono con quelli ricostruiti dalle PTE sorgente; le destinazioni coincidono con le finestre BAR1 già esistenti e riutilizzate. Gli stessi buffer sono usati nel confronto SM/CE, con inizializzazione e verifica owner separate prima di ogni caso.

Il completamento del comando CE non significa che il valore atteso sia arrivato: è il confronto owner a mostrarne la mancata consegna nel verso Ada → A2000. Questa prova evita l'indirizzamento virtuale del comando CE attraverso le PTE sorgente/destinazione; conserva l'apertura BAR1 del target. Non certifica ogni aspetto del mapping hardware, né identifica il componente che non consegna il dato.

## Calibrazione positiva dei contatori

Le quattro finestre CPU/GPU sono successive a tutti i confronti P2P e separate da essi. Usano memoria host pinned e buffer GPU accessibili soltanto all'owner. Nessun campionatore NVML opera durante gli ioctl fisici. I dati host e owner sono corretti in tutti e quattro i controlli; tutte le finestre rispettano durata, sincronizzazioni e numero minimo di campioni. Sono state ricontrollate 640 letture NVML e le relative statistiche, con finestre iniziali escluse dal periodo quieto e da quello attivo.

| Controllo | Contatore pertinente | Media quieta kB/s | Media attiva kB/s |
|---|---|---:|---:|
| Host → Ada | RX Ada | 300,52 | 11.976.610,77 |
| Ada → Host | TX Ada | 396,39 | 12.652.304,93 |
| Host → A2000 | RX A2000 | 296,26 | 3.118.010,14 |
| A2000 → Host | TX A2000 | 383,88 | 4.085.389,29 |

Il controllo Host → A2000 colma il limite delle prove Traffic: il contatore RX A2000 risponde nettamente a traffico in ingresso correttamente ricevuto. Per quella finestra ci sono 23 campioni quieti e 14 attivi; anche il minimo attivo, 3.066.357 kB/s, è molto superiore al massimo quieto, 341 kB/s. Il successivo D2H verifica l'intero MiB dell'owner.

Questo rafforza l'interpretazione del RX A2000 rimasto al livello quieto durante i PUSH P2P precedenti. I contatori sono però aggregati, non una cattura TLP: la calibrazione H2D non dimostra che ogni classe di richiesta P2P venga contabilizzata nello stesso modo, né localizza il punto preciso in cui il trasferimento fallisce. Le copie host di calibrazione non sono una soluzione P2P e non fanno da relay tra le GPU.

## Stato PCI e durata delle allocazioni

I 102 snapshot completi dei sei dispositivi non mostrano variazioni di PCI_STATUS, Device Status, AER o degli altri campi registrati rispetto alla baseline. Non compare quindi un nuovo Received Master Abort in questa prova di sole scritture. I bridge ASM hanno già bit CES presenti nella baseline: non si descrive il sistema come privo di qualsiasi errore PCI storico.

I registri firmware restano quelli originali, D1=`04008077` e D7=`0e009077`, prima del driver, dopo il caricamento e dopo la prova. Tutti i buffer rimangono vivi fino al termine dei confronti e delle calibrazioni. Entrambe le finestre BAR1 hanno un `WINDOW_DESTROY_DONE` successivo a `data_done`.

Restano gli errori di cleanup già osservati: quattro mapping IOVAS residui 346,285 ms dopo `context_exit_begin`, poi otto assert a partire da361,291 ms dopo quel marcatore. Zero Xid. Questa sequenza non precede né interrompe i confronti acquisiti; rimane un difetto distinto del cleanup del driver sperimentale.

## Unico ulteriore confronto per questa pista

La variante fisica corrente forza destinazione NONCOHERENT_SYSMEM2. Il normale helper CE Ampere per UVM_APERTURE_SYS sceglie invece COHERENT_SYSMEM1. Una variante che cambi soltanto quel metodo, mantenendo indirizzi, canale, buffer, durata e controlli, è un confronto ancora distinto dalla precedente prova PTE SYS_COH: qui cambia direttamente `SET_DST_PHYS_MODE` in un comando fisico, senza usare la PTE target per la traduzione del comando. [Helper primario NVIDIA](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/19f3b34/kernel-open/nvidia-uvm/uvm_ampere_ce.c).

È un'ipotesi discriminabile, non una correzione dimostrata. Non si deducono da questi due nomi l'effettivo bit NoSnoop del TLP, un nuovo Requester ID o un percorso CPU. Nessuna variante è stata implementata o eseguita dall'autore di questa analisi al momento della chiusura di PHYS2.

## Evidenza e riproduzione locale

Verificati tutti i 17 hash del manifest di raccolta, senza modificare i file acquisiti. `verified-protocol-nvidia.json` contiene il ricalcolo del protocollo e delle statistiche; `verified-kernel-nvidia.json` documenta le correlazioni dei comandi e la durata delle risorse; `verified-result.json` li raccoglie. `analyze_kernel_nvidia.py` ripete soltanto letture locali dei log.

- result.log SHA256: `f4cc1ff47595015ef1aba7fa7f27a5039fa88eb8b5f433a663de4253c25cb374`
- kernel.log SHA256: `6b50eafdf23091be87b9c3f96dfe5ecfa6dce652542890dc4610c07067672e44`

La revisione non ha eseguito accessi remoti, prove GPU, modifiche firmware o operazioni hardware.
