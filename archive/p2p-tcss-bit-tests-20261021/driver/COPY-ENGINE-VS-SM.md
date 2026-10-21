> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Motore di copia e scritture P2P: proposta discriminante

Stato: ricerca di fonti e proposta; nessuna implementazione, installazione o
esecuzione. La prova attuale usa store da kernel SM. Una copia CUDA può essere
un confronto utile, ma il nome dell'API non certifica né l'impiego del motore
di copia, né la GPU esecutrice, né l'assenza di un passaggio interno in RAM.

La funzione Driver API si chiama `cuMemcpyDtoDAsync`; l'equivalente Runtime
usa `cudaMemcpyAsync(..., cudaMemcpyDeviceToDevice, stream)`. La documentazione
Driver 12.9.1 descrive operandi, byte e stream, senza esporre un selettore
obbligatorio CE/SM o una modalità che fallisca se viene usato un buffer host.
Questo è un limite del contratto pubblico esaminato, non una prova che il
driver stia effettivamente usando un buffer host.
[CUDA Driver API: memory management](https://docs.nvidia.com/cuda/archive/12.9.1/cuda-driver-api/group__CUDA__MEM.html).

## Evidenza primaria specifica per VMM

Cory Perry, coautore del blog NVIDIA sulle API VMM, descrive la selezione dei
dispositivi capaci di accedere a tutto il range coinvolto. Contesto corrente,
stream e operandi concorrono alla selezione; l'implementazione può scegliere
CE oppure kernel SM. Con più alternative la scelta del dispositivo è interna
al driver. Il commento è del 2021: chiarisce il modello, ma non è una promessa
sulla precisa implementazione 595.99.02 modificata.
[Risposta di Cory Perry, messaggio 20](https://forums.developer.nvidia.com/t/introducing-low-level-gpu-virtual-memory-management/148875/20).

Il blog spiega che `cuMemSetAccess` abilita l'accesso peer per singola
allocazione VMM: non richiede `cudaDeviceEnablePeerAccess` per quelle
allocazioni. Va quindi verificato il diritto sull'intero range di ciascun
operando, senza interpretare una capability globale forzata come verifica
del percorso fisico.
[Blog NVIDIA VMM](https://developer.nvidia.com/blog/introducing-low-level-gpu-virtual-memory-management/).

Il progetto NVIDIA `nvbandwidth` separa esplicitamente gli iniziatori CE e SM.
Nel commit esaminato, `MemcpyInitiatorCE::memcpyFunc` usa `cuMemcpyAsync`, mentre
la selezione del contesto può preferire sorgente o destinazione. Questo è un
precedente concreto di test, non una garanzia universale per ogni dimensione
e allocazione VMM.
[Sorgente NVIDIA, righe 372 e 859](https://github.com/NVIDIA/nvbandwidth/blob/82fc4e8c6afa0babb8687793678f615b3b8d793e/memcpy.cpp).
Copia locale in `reference/nvbandwidth-memcpy-82fc4e8.cpp`, Git blob
`021c2f951234efa3c06b9d604c976b7678788f6e`.

## Candidato che isola la direzione di accesso

Inferenza progettuale basata sulle fonti, ancora da misurare:

1. Per la direzione S→T creare una sorgente fisica su S accessibile soltanto
   a S e una destinazione fisica su T accessibile a T e S. Nessuna memoria
   managed e nessun buffer host come operando della copia.
2. Verificare proprietà dei due handle con
   `cuMemGetAllocationPropertiesFromHandle` e diritti per entrambe le GPU con
   `cuMemGetAccess`: sorgente S=RW/T=NONE, destinazione S=RW/T=RW. Queste query
   sono documentate nella
   [Driver API VMM](https://docs.nvidia.com/cuda/archive/12.9.1/cuda-driver-api/group__CUDA__VA.html).
3. Rendere corrente il contesto S e creare lo stream in S, verificandone il
   contesto. Inizializzare e verificare sorgente e destinazione sui rispettivi
   proprietari, con sincronizzazione esplicita, prima del trasferimento.
4. Richiedere la sola copia locale-S→peer-T sullo stream S. La GPU S è l'unica
   con accesso a entrambi gli operandi; questo elimina l'alternativa ordinaria
   di esecuzione su T con lettura peer di S. È un vincolo del mapping, non
   prova dei comandi effettivamente emessi dal driver.
5. Sincronizzare lo stream e verificare l'intero intervallo dal proprietario T;
   confrontare con il kernel SM usando le stesse condizioni. Ripetere l'altra
   direzione con sorgente separata e non peer-mappata. Rilasciare soltanto dopo
   tutti i confronti, mantenendo i marker e le fotografie PCIe già disponibili.

Un risultato della sola copia da quattro byte non prova l'uso CE. Per una
dimensione successiva già entro i buffer di collaudo occorre osservare il
motore, senza assumere una soglia fissa CE/SM e senza usare la velocità come
criterio di correttezza.

## Evidenza necessaria sul percorso

CUPTI 12.9.1 espone per la copia peer device esecutore, device sorgente e
destinazione, contesti, stream, byte, correlation ID, channel ID e channel
type. Registrare attività API, copie ordinarie, copie peer e kernel concorrenti;
correlare l'operazione e richiedere assenza di record persi. Per dichiarare che
il confronto ha usato CE serve `channelType=ASYNC_MEMCPY` e GPU esecutrice S.
[Record peer CUPTI](https://docs.nvidia.com/cupti/12.9.1/api/structCUpti__ActivityMemcpyPtoP4.html),
[tipi di canale CUPTI](https://docs.nvidia.com/cupti/12.9.1/api/group__CUPTI__ACTIVITY__API.html).

Il conteggio `asyncEngineCount` descrive una capacità, non prova il motore
della singola operazione. Analogamente, endpoint DEVICE→DEVICE e assenza di
copie host visibili nel trace sono evidenze utili, ma il solo contratto CUPTI
non certifica l'assenza di ogni buffer interno del driver. Con il vincolo
rigoroso «nessun payload attraverso RAM», un eventuale PASS richiede anche
evidenza del trasferimento diretto nei comandi/mapping del percorso esecutore;
altrimenti va riportato come PASS della copia CUDA con percorso incompletamente
verificato, senza dichiarare risolto il P2P.

La guida CUDA descrive l'eliminazione dello staging host quando l'accesso peer
è disponibile. Qui il driver modifica capability e mapping: non trasferiamo
automaticamente quella promessa a questa configurazione sperimentale.
[Guida CUDA: peer memory copy](https://docs.nvidia.com/cuda/archive/12.9.1/cuda-c-programming-guide/index.html#peer-to-peer-memory-copy).

Se CE su S passa dove il kernel SM fallisce, si restringe l'indagine al percorso
di emissione o ai suoi attributi. Se viene scelto un kernel, non è stato
provato un percorso CE distinto. Un fallimento CE ripetuto non localizza da
solo il guasto nel controller Thunderbolt.

## Approfondimento operativo: driver 595 e CUPTI 12.6

È stato preparato un candidato separato in `../native-ce-probe/`, ancora da
compilare, revisionare ed eseguire al momento della sua prima stesura. Usa gli
header e la libreria CUPTI **12.6.80**, estratti dal container CUDA12.6 dal
coordinatore, e gli ABI realmente presenti: `CUpti_ActivityMemcpy5`,
`CUpti_ActivityMemcpyPtoP4`, `CUpti_ActivityKernel9`, API version24. Il toolkit
usato per compilare è nvcc12.6.85. Non sostituisce libcuda595.99.02 né modifica
il driver per il primo confronto.

Le attività copia non contengono gli indirizzi GPU. Gli indirizzi provengono
quindi da una callback Driver API `cuMemcpyDtoDAsync_v2`/`_ptsz`: src, dst,
ByteCount, stream, contextUid e correlationId vengono copiati durante la
callback, quando sono validi. La stessa correlationId deve comparire nel
record Driver API e nel record di copia. L'external correlation collega
inoltre il record al singolo caso numerato; non si deduce l'appartenenza dal
solo ordine di consegna del buffer, che CUPTI non garantisce.
[Contratto callback NVIDIA](https://docs.nvidia.com/cupti/12.9.1/api/structCUpti__CallbackData.html),
[ordine, flush e compatibilità](https://docs.nvidia.com/cupti/12.9.1/main/main.html).
L'ABI effettivo viene verificato sugli header12.6 locali, non assunto dagli
esempi di una release successiva.

Il candidato ha quattro buffer da8MiB mantenuti vivi. Per ciascuna direzione
esegue SM e copia CUDA sulle stesse allocazioni per4B,64KiB,1MiB: dodici
confronti totali. Prima di ogni confronto ricrea sorgente e poison con H2D sul
rispettivo owner, sincronizza e confronta l'intero intervallo localmente. La
sorgente è VMM accessibile soltanto alla GPU che esegue; la destinazione è RW
su owner ed executor. `cuMemGetAllocationPropertiesFromHandle` e
`cuMemGetAccess` all'inizio e alla fine del mapping controllano proprietà e
permessi; contesto corrente e contesto dello stream devono essere quelli del
source. Il solo trasferimento SM è local-source→peer-target; nessuna lettura
peer precede le prove.

Sono distinti: completamento dei dodici confronti, correttezza dei dati,
completezza del trace, osservazione di CE e prova del percorso diretto. Un
caso CE è osservato soltanto con callback esatta, attività coerente per
executor/context/stream/range-byte, canale ASYNC_MEMCPY, nessun kernel nella
copia, nessuna copia con endpoint host e zero record persi/errori. I dati
possono essere corretti senza che il percorso sia certificato: il candidato
stampa sempre `direct_route_proven=0`. Un FAIL con CE osservato aggiunge
l'evidenza di un secondo motore; un PASS richiederebbe il passo successivo sui
comandi/mapping interni per dichiarare il requisito «nessuna RAM payload».

## Via UVM realmente esplicita, distinta dall'API CUDA

La sorgente NVIDIA inclusa nella build595 contiene già un generatore di
comandi CE. Non basta chiamare un test dal nome CE per riutilizzarlo sui
nostri buffer, ma il percorso è concreto:

- `uvm_channel.c:2917` esclude GRCE quando seleziona un motore; UVM richiede
  capability sysmem e p2p. `uvm_hal_turing_ce_init()` emette SET_OBJECT con
  classe CE sul subchannel0: il commento NVIDIA spiega che questo fallirebbe
  su GRCE. La classe effettiva va letta da `rm_info.ceClass`, senza dedurla dal
  solo nome Ampere/Ada.
- `uvm_hal.c:87–106` fa ereditare a classi AMPERE_DMA_COPY_A/B il generatore
  `uvm_hal_turing_ce_memcopy`; per la classeB imposta inoltre DISABLE_PLC.
- Il generatore emette `OFFSET_IN_UPPER/LOWER` **0x400/0x404**,
  `OFFSET_OUT_UPPER/LOWER` **0x408/0x40c**, `LINE_LENGTH_IN` **0x418** e
  `LAUNCH_DMA` **0x300**. Le classiC6B5/C7B5 espongono SRC/DST_TYPE ai bit12/13.
- `SET_SRC_PHYS_MODE` **0x260** e `SET_DST_PHYS_MODE` **0x264** hanno TARGET
  [1:0]: localFB0, coherentSYS1, noncoherentSYS2, peer3. Sono valori del metodo
  CE, differenti dai valori aperture dei PTE. L'HAL ordinario mappa
  UVM_APERTURE_SYS su coherentSYS; non permette di fingere che cambiare
  l'enum PTE controlli direttamente questo metodo.

Fonti primarie:
[uvm_turing_ce.c](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/19f3b34/kernel-open/nvidia-uvm/uvm_turing_ce.c),
[uvm_hal.c](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/19f3b34/kernel-open/nvidia-uvm/uvm_hal.c),
[uvm_channel.c](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/19f3b34/kernel-open/nvidia-uvm/uvm_channel.c),
[classC7B5](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/19f3b34/src/common/sdk/nvidia/inc/class/clc7b5.h).
I file sono presenti nell'archivio locale verificato della build. Il connector
GitHub ha restituito i tre file richiesti con Git blob
`b3ae6c9465d3bf14378fe510659e8bdfceb53673`,
`fac3b5f2ce0e292fb395c0af759a830bbb098dc3`,
`df331e8ad5104e229829aa770487d383fe1f0632`; una richiesta separata dell'oggetto
commit abbreviato19f3b34 ha restituito422. Non presento quindi questo suffisso
come commit remoto completo risolto: per riproducibilità valgono archivio e
hash locali, e la verifica del contenuto dei file.

**Limite pratico:** gli ioctl di test esistenti non eseguono il nostro caso
senza adattamenti. `UVM_TEST_CE_SANITY` non riceve le due VA utente e crea altre
allocazioni. `UVM_TEST_PEER_IDENTITY_MAPPINGS` usa sysmem come sorgente e richiede
peer-copy modeVIRTUAL: non certifica la copia VRAM→VRAM richiesta.
`nvUvmInterfaceDupAllocation` dichiara esplicitamente non supportata la
 duplicazione di vidmem fraGPU; non è una scorciatoia per far entrare due
allocazioni CUDA nel VA space interno UVM.

Un ioctl nuovo potrebbe allocare una piccola sorgente VRAM UVM, inizializzarla
con il CE, e scrivere quattrobyte nella finestra BAR1 della destinazione viva.
Per essere proponibile deve però ottenere la finestra dal mapping RM corrente
tramite handle e refcount, bloccarne la distruzione durante il push e validare
owner/BDF/range. Non deve accettare un indirizzo fisico arbitrario o una riga
storica di log come autorizzazione. Deve loggare i metodi effettivi, classe,
engine, aperture, indirizzi, byte, release/membar e completamento; nessuna
operazione payload deve usare sysmem come sorgente/intermedio. Il target
fisico bypasserebbe il PTE attuale e quindi cambierebbe anche il percorso di
traduzione: sarebbe un discriminante, non un confronto CE-vs-SM puro. Questo
ioctl non è implementato né verificato; la via immediata rimane il candidato
CUDA osservato con CUPTI, con i limiti sopra espliciti.
