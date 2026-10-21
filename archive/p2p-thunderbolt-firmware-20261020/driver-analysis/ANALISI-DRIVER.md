> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Analisi statica del driver P2P Ada 2000 ↔ A2000

Data: 21 ottobre 2026. Ambito: sorgenti e log locali già raccolti. Nessun test, accesso SSH, modifica al server, caricamento di driver o scrittura firmware eseguiti per questa analisi.

Il controllo dell'inoltro PCIe sul root port Thunderbolt deve essere individuato nel firmware/piattaforma. Le modifiche NVIDIA esaminate consentono al software di dichiarare P2P e creare finestre BAR1; non programmano tale controllo. Una capability dichiarata dal driver, dalla libreria CUDA o dall'hypervisor non rende funzionante un percorso fisico che non inoltra le transazioni.

## Fonti e stato del codice

Radice dei reperti: `runtime/reports/gpu-followup-20261020/`.

Nel seguito `S/` indica `p2p-driver/source/NVIDIA-open-gpu-kernel-modules-19f3b34/` rispetto alla radice dei reperti.

- Base NVIDIA: versione 595.99.02, archivio ufficiale documentato in `p2p-driver/source-provenance.json`, SHA-256 `1174b28565fe8c0dff534a2588f4becd5e12c03465a70f347650a0d0fc9f23bc`.
- Port dinamico: fork `xiaoyanzi191/open-gpu-kernel-modules-p2p`, commit `025090f64d7f79b3b6de118c3e9c50bc32988235`, nato su 595.71.05 e portato a 595.99.02; fonte `p2p-driver/dynamic-port/provenance.json`.
- La directory `S/` contiene codice modificato, compresi esperimenti diagnostici. Non è una copia stock da ricompilare alla cieca. Le copie `.original` esistono per i cinque file principali del port; per altri file alterati occorre ripartire dall'archivio NVIDIA.
- Le note `driver-reference/method3-review-followups.md` descrivono limiti reali del prototipo. Alcune correzioni suggerite lì sono già nel sorgente attuale: in particolare `bDynBar1Mapped` è presente, quindi non va segnalato come difetto ancora aperto.

## Tre livelli software separati

| Livello | Stato stock o vincolo | Modifica esistente | Effetto reale |
|---|---|---|---|
| Libreria CUDA | Confronto architetture Ada/Ampere nei percorsi peer | Quattro salti condizionali in `libcuda.so.1` | Elimina il rifiuto software delle architetture differenti; non cambia BAR1, IOMMU o root port |
| RM/kernel NVIDIA | Metodi BAR1 non esposti per le GPU interessate; requisito static BAR1 | Collegamento degli HAL GH100, selezione BAR1 e finestre dinamiche per allocazione | Costruisce indirizzi peer per allocazioni esplicite |
| Piattaforma | Inoltro di richieste e completamenti tra i root port | Nessun controllo Thunderbolt individuato nei sorgenti NVIDIA esaminati | Deve essere configurato prima di poter dichiarare il percorso disponibile |

### Patch libcuda 595.99.02

`p2p-driver/patch_libcuda_595.py:5` verifica l'hash originale `192d4eedb1b39f0568f2b5423d35227d13b32b9025599e1968a9081982da207d`, verifica firme e destinazioni, poi sostituisce `74` (salto condizionale) con `eb` (salto incondizionato) agli offset `0x2a8566`, `0x2a8661`, `0x2cfed3`, `0x43ad7c`. La provenienza dichiara un port della patch mixed architecture di aikitoria effettuato tramite disassemblaggio. La libreria è una copia sperimentale isolata, non la libreria di sistema.

La sola patch libcuda aveva già portato le capability a true senza rendere corretti i dati: `p2p-driver/libcuda-only-result.json` e `p2p-driver/libcuda_peer_validation/direct_sm_peer_verify.log`. Non è quindi una soluzione del trasporto.

### Selezione BAR1 e blocchi della piattaforma nel driver

- `S/src/nvidia/interface/nvrm_registry.h:1073`: `ForceP2P` ha campi separati read, write e atomics. `0x11` forza read e write, lasciando atomics disabilitati. È un override delle decisioni chipset, non una programmazione del chipset.
- `.../nvrm_registry.h:1101`: `RMForceP2PType=1` seleziona PCIe; l'header specifica che il tipo deve essere supportato dall'hardware.
- `.../nvrm_registry.h:1118`: `RMPcieP2PType=1` seleziona BAR1; `0` seleziona mailbox; `2` consente auto.
- `S/src/nvidia/src/kernel/platform/p2p/p2p_caps.c:646`: `_p2pCapsGetHostSystemStatusOverPcieBar1` accetta read solo con switch PCIe comune, CPU Ryzen o Xeon Sapphire Rapids. Un Core con GPU su root distinti non rientra in queste condizioni.
- `.../p2p_caps.c:703`: `_kp2pCapsGetStatusOverPcieBar1` controlla prima che il mapping BAR1 sia supportato e solo dopo applica l'override. Quindi `ForceP2P` da solo non implementa il mapping mancante.
- `S/src/nvidia/src/kernel/gpu/bus/arch/hopper/kern_bus_gh100.c:1447`: la funzione di supporto BAR1 verifica selezione/proprietà, assenza di loopback e assenza di connessione mailbox preesistente. Il port dinamico rimuove il requisito che entrambe le schede abbiano static BAR1.
- La patch attuale rifiuta però coppie con una GPU static e una dynamic (`.../kern_bus_gh100.c:1497`). Nel percorso esistente le prove hanno impostato entrambe dynamic con `RMForceStaticBar1=0`. Rimuovere il rifiuto senza implementare mapping/unmapping per direzione produrrebbe indirizzi non coperti dalla IOMMU per il lato static.
- `p2p-driver/bar1-minimal.patch`: collega gli HAL BAR1 in `src/nvidia/generated/g_kern_bus_nvoc.c` e gestisce la connessione BAR1 in `kern_bus_gp100.c`. Non modifica i bridge Intel.

Se il controllo firmware corretto viene trovato e configurato, il punto per una capability circoscritta è il controllo piattaforma BAR1, subordinato alla piattaforma e al percorso realmente configurati. Non è corretto aggiungere tutti i Core alla lista o trasformare globalmente ogni rifiuto in successo. In una VM la lettura della configurazione fisica e la sua attestazione devono rimanere nel livello host competente.

## Vendor capability e clique: non sono controlli Thunderbolt

`S/src/nvidia/src/kernel/platform/chipset/chipset_pcie.c:4362`, `objClLoadPcieVirtualP2PApproval`, opera solo con `IS_PASSTHRU`. Cerca nella lista PCI una capability vendor-specific con firma `0x00503250`, versione 0, e registra un ID di clique a 4 bit. L'offset riservato è `0xc8`, ma il codice accetta altri offset se collegati nella lista. Definizioni: `S/src/nvidia/arch/nvalloc/common/inc/nvpcie.h:214`.

`S/src/nvidia/src/kernel/virtualization/hypervisor/hypervisor.c:276` accetta la clique solo se tutte le GPU hanno capability valida e lo stesso ID. Il commento stock è esplicito: l'hypervisor garantisce che P2P è stato verificato e funziona sulla piattaforma fisica. Inserire la capability per aggirare il rifiuto non adempie questa garanzia e non cambia il routing.

Il percorso alternativo `_hypervisorCheckVirtualPcieP2PGeneralApproval` interroga il Physical RM con `NV2080_CTRL_CMD_INTERNAL_GET_PCIE_P2P_CAPS`. Anche questo restituisce uno stato: non configura il root port Thunderbolt. Parte del comportamento Physical RM/GSP e libcuda non è ricostruibile dai soli sorgenti aperti presenti.

## Requisiti di mapping da preservare

Il percorso dinamico è in `S/src/nvidia/src/kernel/rmapi/nv_gpu_ops.c:3689` e seguenti:

1. La finestra deve mappare l'allocazione nella BAR1 della GPU proprietaria con `kbusMapFbAperture_HAL`, mantenendo stabile allocazione e finestra finché esistono PTE peer o operazioni pendenti.
2. Il port corrente esige un solo intervallo BAR1 contiguo: niente `ALLOW_DISCONTIG`, controllo esplicito `memArea.numRanges == 1`. La VRAM fisica può essere dispersa, perché la traduzione interna BAR1 la gestisce. Non si può invece linearizzare una BAR1 multi-intervallo con un unico indirizzo base.
3. La dimensione della finestra è `memdescGetSize`, non `ActualSize` arrotondata. `memdescCreateSubMem` impone `Offset + Size <= pMemDesc->Size` con somma sicura (`mem_desc.c:2523`).
4. Il descrittore `pWindowMemDesc` deve appartenere alla GPU remota/proprietaria. `osIovaMap` usa il proprietario root per riconoscere che l'indirizzo è nella BAR1 del peer (`S/src/nvidia/arch/nvalloc/unix/src/os.c:3645`). Usare come proprietario la GPU sorgente causa il riconoscimento errato come memoria di sistema senza dati privati.
5. L'indirizzo usato nelle PTE deve essere quello restituito dal mapping nella IOVAS della GPU che accede, non un indirizzo CPU, guest o host scelto manualmente. Il percorso ufficiale passa per `nv_dma_map_peer`, quindi DMA API oppure conversione bus address (`S/kernel-open/nvidia/nv-dma.c:759`).
6. Il flag esplicito `bDynBar1Mapped` va mantenuto: IOVA zero può essere un indirizzo valido e non deve significare automaticamente «static».
7. `SYS_NONCOH` è la scelta quando non sono disponibili atomiche PCIe. Non trasformare in `SYS_COH` tutte le PTE per superare un problema di routing: la scelta ha implicazioni sulle atomiche (`S/kernel-open/nvidia-uvm/uvm_gpu.c:893`).

Nel sorgente di lavoro `S/kernel-open/nvidia/nv-dma.c` è ancora presente una sostituzione diagnostica con BAR fisici Xen hardcoded `0x4000000000` e `0x4600000000`. Va esclusa dal driver finale. Anche `xen-low-gpa-alias.patch`, `bar1-coherent-diagnostic.patch`, `bar1-disable-nosnoop.patch` e `pcie-packet-128.patch` sono esperimenti separati; nessuno costituisce una configurazione Thunderbolt documentata.

## Difetti attuali da correggere prima di un driver utilizzabile

### 1. Teardown IOVAS incompleto: osservato

`baremetal-probe/kernel.log:1105` registra quattro mapping rimasti in IOVAS `0x100`, poi assert `pIOVAS != NULL` in `io_vaspace.c:598/607`; lo stesso accade a riga 1159 nel secondo caricamento. La funzione stock `iovaspaceFromMapping` spiega che questi assert significano mapping sopravvissuti alla loro IOVAS.

Punti concreti del port da correggere:

- `nvGpuOpsDeviceDestroy` chiama `_nvGpuOpsDynBar1DestroyAll` solo dopo aver liberato il subdevice RM (`nv_gpu_ops.c:2389` → `2400`). Il drain va completato quando i dispositivi, le IOVAS e le allocazioni referenziate sono ancora validi, prima del loro teardown. Non basta spostare una chiamata senza verificare il contratto dei lock e l'ordine tra i due device della sessione.
- `nvGpuOpsFreeDupedHandle` salta il destroy dinamico quando fallisce la ricerca del subdevice o della memoria, ma libera comunque l'handle nel ramo `out` (`nv_gpu_ops.c:9744–9772`). La rimozione per chiave deve coprire anche questi percorsi e tutte le liberazioni equivalenti, senza usare oggetti già distrutti.
- L'elenco conserva puntatori grezzi a GPU remota e memdesc. Il port non aggiunge una propria retention dell'allocazione. Il mapping BAR1 stock usa callback di distruzione sul memdesc, non una promessa che il puntatore rimarrà valido dopo la liberazione dell'handle. Va definita una proprietà esplicita per il tempo di vita del mapping; in alternativa va assicurato in ogni percorso che il mapping venga rimosso prima dell'handle e del relativo device.
- Non attribuisco con certezza tutti e quattro i mapping residui alla medesima lista dinamica: il log non stampa una correlazione sufficiente. È dimostrato il difetto di durata dei mapping; non è dimostrato che sia la causa delle prime letture errate.

### 2. Lock e gestione degli errori

`_nvGpuOpsDynBar1Destroy` e il ramo `fail` di `_nvGpuOpsDynBar1Create` ignorano il risultato di `rmDeviceGpuLocksAcquire` e proseguono con unmap/release (`nv_gpu_ops.c:3861`, `3934`). Una correzione deve distinguere lock già posseduto, acquisizione riuscita e fallimento; non eseguire unmap senza lock e non dichiarare completato il cleanup quando non è riuscito. Il destroy attuale restituisce `void`, quindi il chiamante non può gestire il fallimento.

Il drain deve essere idempotente e coordinato con le operazioni di mapping: impedire nuovi mapping durante il teardown, mantenere il riferimento necessario sino a unmap completato, rimuovere la mappatura IOVA e solo dopo la finestra BAR1 e i riferimenti. I lock RM/GPU/mutex devono seguire un ordine unico.

### 3. Limiti e overflow

I due builder (`nv_gpu_ops.c:4597`, `4955`) verificano `offset + size`, mentre la dimensione effettiva è `mappingSize = size ? size : allocSize` (`4395`, `4853`). Con `size == 0`, oppure overflow della somma, il controllo non copre l'intervallo effettivamente codificato. Usare sottrazione sicura (`offset <= windowSize` e `mappingSize <= windowSize - offset`) e verificare anche pagine finali/arrotondamenti; oppure rifiutare esplicitamente `size == 0` su questo percorso. La formula `dmaBase + offset + i * pageSize` richiede controlli di range e overflow coerenti.

Il budget BAR1 è per subdevice sorgente, ma le finestre consumano BAR1 remota (`nv_gpu_ops.c:3728`). È solo una stima, non una quota globale; anche l'addizione di tre quantità può traboccare. Il budget corretto va applicato al proprietario remoto e coordinato con gli altri utilizzatori della BAR1. La prenotazione effettiva resta responsabilità dell'allocatore BAR1.

### 4. Percorsi UVM non implementati

Il port segnala link `PCIE_BAR1` ma restituisce DMA base/size `0/0` in modalità dynamic (`nv_gpu_ops.c:3290`). `uvm_gpu_peer_phys_address` richiede invece size nonzero e aggiunge la base per i peer-copy fisici (`S/kernel-open/nvidia-uvm/uvm_gpu.c:3226`). Documentare il limite non basta: occorre un gate esplicito che impedisca a queste capability di essere utilizzate per migrazione managed/peer-copy senza finestra globale, oppure implementare quel percorso con mapping dinamici propri. Il prototipo copre essenzialmente allocazioni esplicite e PTE esterne; non equivale al supporto di ogni API CUDA P2P.

## Adattamento mirato subordinato al firmware

Una volta individuato un controllo firmware effettivo per il root Thunderbolt, la sequenza di implementazione deve conservare la separazione tra le responsabilità:

1. Il firmware/host configura il controllo documentato sul percorso fisico e ne conserva una descrizione riproducibile. Il driver GPU non deve inventare registri Intel né usarne un offset appartenente a un diverso tipo di root port.
2. Il driver accetta solo la combinazione di GPU/topologia/policy coperta dal controllo. Il gate in `p2p_caps.c` è il punto utile; una clique virtuale può comunicare una garanzia host già valida, non crearla.
3. Le GPU usano BAR1 dynamic su entrambi i lati con il port attuale, oppure si implementano correttamente mapping per direzione per supportare static/dynamic misto. Si escludono gli indirizzi diagnostici hardcoded e si usa la DMA API corretta anche in VM.
4. Si correggono cleanup, durata dell'allocazione, lock, controlli dei limiti e capacità UVM. Solo la modifica dei bit che pubblicizzano P2P lascerebbe gli stessi difetti già osservati.
5. Il vincolo mixed architecture di libcuda rimane un intervento separato e legato esattamente al binario 595.99.02; il port non va applicato a offset fissi su versioni diverse.

Questo documento definisce dove intervenire e quali invarianti preservare. Non afferma che il controllo Thunderbolt sia stato trovato o abilitato, né che la correzione completa sia già dimostrata. Non sono stati eseguiti nuovi collaudi, come richiesto.
