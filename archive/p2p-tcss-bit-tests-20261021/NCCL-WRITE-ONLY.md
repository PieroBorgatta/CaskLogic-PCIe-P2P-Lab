> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# NCCL a sole scritture: percorso verificabile, ancora da collaudare

Analisi locale dei sorgenti ufficiali **NCCL v2.27.5-1**, coerenti con la versione 22705 registrata nelle prove precedenti (`gpu-followup-20261020/communication/baseline.log`). Non è stata eseguita una nuova prova NCCL. Prima dell'uso occorre registrare versione e hash della libreria effettivamente caricata; i risultati storici non identificano automaticamente il binario della prossima prova.

**Conclusione:** Simple + Ring può usare carichi solo dalla VRAM locale e scritture verso la GPU remota, compresi crediti e notifiche. Per questo servono anche registrazione dei buffer disabilitata e trasporto P2P senza copy engine. `NCCL_P2P_READ_ENABLE=0` da solo non basta. Esiste inoltre un controllo preciso per impedire il fallback NET sullo stesso host: `NCCL_NET_DISABLE_INTRA=1`. La configurazione seguente costituisce un candidato motivato, subordinato al successo della scrittura P2P in entrambe le direzioni; non risolve una scrittura Ada→A2000 ancora guasta.

## Dati e sincronizzazione

Nel [trasporto P2P, righe 484–558](https://github.com/NVIDIA/nccl/blob/v2.27.5-1/src/transport/p2p.cc#L484), con `read=0` e `useMemcpy=0`:

| Operazione GPU | Indirizzo usato | Tipo di accesso |
|---|---|---|
| Invio dei dati | buffer `recvDevMem` del destinatario | scrittura remota |
| Attesa di spazio del mittente | `sendDevMem.head` del mittente | lettura locale |
| Notifica del mittente | `recvDevMem.tail` del destinatario | scrittura remota |
| Attesa dei dati del destinatario | `recvDevMem.tail` del destinatario | lettura locale |
| Consumo/riduzione dei dati ricevuti | buffer `recvDevMem` del destinatario | lettura locale |
| Restituzione dei crediti | `sendDevMem.head` del mittente | scrittura remota |

Le corrispondenti operazioni sono in [`loadRecvConn` e `loadSendConn`](https://github.com/NVIDIA/nccl/blob/v2.27.5-1/src/device/prims_simple.h#L486). [`postPeer`](https://github.com/NVIDIA/nccl/blob/v2.27.5-1/src/device/prims_simple.h#L171) esegue la fence di sistema prima della notifica quando ha scritto dati. Le primitive Ring denominate `directSend`/`directRecv` usano comunque il FIFO ordinario quando i flag DirectRead/DirectWrite non sono attivati: il nome del metodo non prova un accesso diretto al buffer utente.

Il rischio nascosto è [`setDataPtrs`](https://github.com/NVIDIA/nccl/blob/v2.27.5-1/src/device/prims_simple.h#L744): con `Direct && ipcReg`, il destinatario in modalità DirectWrite può leggere `ptrExchange` situato nella memoria del mittente. Disabilitare entrambe le registrazioni elimina questo ramo: [`coll_reg.cc`](https://github.com/NVIDIA/nccl/blob/v2.27.5-1/src/register/coll_reg.cc#L39) conserva `NCCL_REGULAR_BUFFER` e ritorna quando LOCAL_REGISTER e GRAPH_REGISTER sono entrambi zero; [`enqueue.cc`](https://github.com/NVIDIA/nccl/blob/v2.27.5-1/src/enqueue.cc#L298) lascia `regUsed=0`. Anche [Send/Recv](https://github.com/NVIDIA/nccl/blob/v2.27.5-1/src/register/sendrecv_reg.cc#L20) mantiene il relativo flag a zero.

`NCCL_P2P_DIRECT_DISABLE=1` evita la scelta iniziale del trasporto chiamato `P2P/direct pointer`; **non sostituisce** le due variabili di registrazione. LL e LL128 non sono inclusi nella presente dimostrazione: si seleziona soltanto Simple. Questa è una verifica degli accessi espliciti del codice, non una cattura dei pacchetti PCIe generati dall'hardware per fence, ordinamento o coerenza.

## Escludere il transito del payload attraverso RAM/rete

[`ncclTopoCheckNet`](https://github.com/NVIDIA/nccl/blob/v2.27.5-1/src/graph/paths.cc#L510) restituisce `net=0` con **NCCL_NET_DISABLE_INTRA=1**. [`net.cc::canConnect`](https://github.com/NVIDIA/nccl/blob/v2.27.5-1/src/transport/net.cc#L153) lo consulta quando i due rank hanno lo stesso `hostHash`. Con **NCCL_SHM_DISABLE=1**, Ring e due GPU dello stesso host, [`selectTransport`](https://github.com/NVIDIA/nccl/blob/v2.27.5-1/src/transport.cc#L23) deve scegliere P2P oppure fallire: [SHM restituisce subito zero](https://github.com/NVIDIA/nccl/blob/v2.27.5-1/src/transport/shm.cc#L75) e anche [CollNet rifiuta questo tipo di connessione](https://github.com/NVIDIA/nccl/blob/v2.27.5-1/src/transport/coll_net.cc#L141). Non occorrono variabili inventate come `NCCL_NET_DISABLE`; disabilitare soltanto IB o il plugin NET non esclude Socket.

`NCCL_RUNTIME_CONNECT=0` fa eseguire [RingConnect durante l'inizializzazione](https://github.com/NVIDIA/nccl/blob/v2.27.5-1/src/init.cc#L1148), prima del primo AllReduce. L'inizializzazione può comunque creare socket di bootstrap, proxy locali, strutture CPU e memoria di controllo. Questo non è trasferimento del payload GPU attraverso la RAM. La garanzia è circoscritta ai due rank locali e al trasporto verificato; non va estesa a più host.

## Configurazione candidata per una sola prova

```text
NCCL_P2P_DISABLE=0
NCCL_P2P_LEVEL=SYS
NCCL_P2P_READ_ENABLE=0
NCCL_P2P_DIRECT_DISABLE=1
NCCL_P2P_USE_CUDA_MEMCPY=0
NCCL_LOCAL_REGISTER=0
NCCL_GRAPH_REGISTER=0
NCCL_PROTO=Simple
NCCL_ALGO=Ring
NCCL_CUMEM_ENABLE=1
NCCL_SHM_DISABLE=1
NCCL_NET_DISABLE_INTRA=1
NCCL_RUNTIME_CONNECT=0
NCCL_NVLS_ENABLE=0
NCCL_COLLNET_ENABLE=0
NCCL_MIN_NCHANNELS=1
NCCL_MAX_NCHANNELS=1
NCCL_DEBUG=INFO
NCCL_DEBUG_SUBSYS=ALL
```

`CUMEM_ENABLE=1` rende esplicita la scelta del percorso VMM invece del vecchio IPC; deve risultare supportato dalla libreria/driver presenti. `P2P_LEVEL=SYS` ammette la distanza misurata nella topologia, senza dimostrare la funzionalità dei trasferimenti. Tutte queste variabili appartengono al processo della prova: non sono una proposta di configurazione permanente. La [documentazione NVIDIA 2.27.5](https://docs.nvidia.com/deeplearning/nccl/archives/nccl_2275/user-guide/docs/env.html) distingue i parametri di configurazione da quelli diagnostici.

## Prova minima e criteri

Usare un singolo processo, due GPU e nessun MPI; eseguire AllReduce di interi `sum`, fuori da CUDA Graph, senza chiamare `ncclCommRegister`. Nel `nccl-tests` 2.21.1 locale i parametri della prova breve sono `-g 2 -b 4 -e 8M -f 2 -n 3 -w 1 -c 3 -d int -o sum -G 0 -R 0 -T 30`; verificare prima che `--help` del binario corrisponda al [sorgente ufficiale delle opzioni](https://github.com/NVIDIA/nccl-tests/blob/v2.21.1/src/common.cu#L1420). Questi sono argomenti proposti, non un'esecuzione effettuata. Conservare un watchdog esterno già usato nelle prove native: il timeout software non garantisce di interrompere un GPU hang.

Accettare il risultato soltanto se:

1. Il log identifica due rank locali sulle GPU attese e versione 2.27.5; si conservano hash di libreria, binario, ambiente e log.
2. Tutti i canali di dati risultano `via P2P/CUMEM` in entrambe le direzioni. Rifiutare canali `via SHM`, `via NET`, `P2P/indirect`, suffissi `/read` o `/CE`. Le sole righe di inizializzazione `NET/...` non indicano payload su NET: confrontare le righe **Channel ... via ...**.
3. Le variabili selezionano esclusivamente Ring/Simple. Il [tuning ufficiale](https://github.com/NVIDIA/nccl/blob/v2.27.5-1/src/graph/tuning.cc#L396) applica gli insiemi consentiti; non basta osservare una banda plausibile per dedurre il protocollo.
4. Ogni misura controllata, sia fuori posto sia sul posto, riporta zero elementi errati; nessun timeout, errore CUDA o comunicatore incompleto. Un successo numerico senza trasporto attestato non conta come P2P.
5. Si conservano registri PCIe ed errori prima/dopo. AER invariato non equivale a PCIe privo di errori: nelle prove precedenti era significativo anche PCI_STATUS.RMA.

Un successivo test applicativo può usare `ncclCommInitAll` e verificare i log dopo InitAll, prima di inviare dati, grazie a RUNTIME_CONNECT=0. Il semplice `nccl-tests` non introduce quel controllo intermedio, ma la coppia SHM_DISABLE/NET_DISABLE_INTRA esclude già i due fallback nel codice della versione verificata.

I 16 file NCCL esaminati sono conservati in `reference/nccl-2.27.5/`; `source-manifest.json` registra URL, Git blob SHA-1 verificato sui byte effettivi e SHA-256 locale. Non sono una libreria compilata o installata.

**Stato:** percorso software motivato e riferimenti raccolti; nessuna nuova misurazione NCCL, nessuna conclusione di risoluzione. Il fallimento persistente della scrittura Ada→A2000 rimane da spiegare prima di impiegare questa configurazione.
