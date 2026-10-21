> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Verifica P2P tra RTX 2000 Ada e RTX A2000 sul MS-01

CaskLogic Riscrivo, progetto di Piero Borgatta. Verifica dello storico del 20 ottobre 2026 e dello stato attuale del server.

Il P2P completo non funziona. Le prove individuano due problemi da distinguere: il driver originale non espone l'accesso CUDA fra queste GPU nella configurazione attuale; forzando il supporto, i dati risultano corretti soltanto nella scrittura dalla A2000 esterna verso l'Ada interna. Il percorso CPU/PCIe/Thunderbolt è il principale sospetto, ma il contributo dei driver sperimentali non è ancora escluso.

Vincolo confermato dall'utente: le GPU devono restare nelle posizioni attuali e non è possibile aggiungere uno switch PCIe, interno o esterno. La ricerca del P2P deve quindi restare su driver e firmware della configurazione esistente. Al momento non c'è una correzione dimostrata del P2P diretto; la comunicazione attraverso RAM è invece già verificata. Ulteriori forzature generiche del driver non risolvono ciò che le prove hanno già mostrato.

**Configurazione verificata**

Il computer è un Minisforum MS-01, scheda AHWSA, Intel Core i9-12900H e BIOS 1.26. L'Ada da 16 GB è sullo slot interno, all'indirizzo fisico 01:00.0, sotto la porta 00:01.0. La A2000 da 12 GB è esterna, all'indirizzo 06:00.0, dietro due bridge ASMedia 1b21:2461 e la porta Thunderbolt 00:07.0. Si tratta di PCIe trasportato attraverso USB4/Thunderbolt, non di un collegamento USB ordinario fra le GPU.

XCP-ng assegna entrambe a Ubuntu nella VM gpu-vm. Il driver originale è 595.99.02. Durante questa verifica il training risulta inattivo e disabilitato, le GPU non hanno processi di calcolo e il servizio ventole è attivo. Non sono stati modificati BIOS, driver, servizi o sorgenti e non sono stati avviati nuovi benchmark GPU.

La nuova interrogazione delle API CUDA, senza kernel né trasferimenti, restituisce `cuDeviceCanAccessPeer=false` in entrambe le direzioni. Contemporaneamente `nvidia-smi topo -p2p r/w` restituisce `OK`. La disponibilità dichiarata da quest'ultimo non certifica quindi l'accesso CUDA utilizzabile. Risultati registrati in [verifica attuale](verifica-attuale.json).

**Prove già eseguite**

I percorsi della tabella sono relativi a `runtime/reports/`.

| Prova | Esito effettivo | Evidenza |
| --- | --- | --- |
| Calcolo e memoria delle GPU singolarmente e insieme | Controlli corretti; non certificano la comunicazione diretta | `gpu-audit-20261020/summary.json` |
| Driver originale dentro e fuori Docker nella VM | CUDA peer access falso in entrambi i versi; casi P2P nvbandwidth saltati | `gpu-audit-20261020/route_confirmation.json`, `gpu-followup-20261020/host-p2p.json` |
| Parametri NVIDIA ForceP2P e RM | Nessuna abilitazione CUDA utile | `gpu-followup-20261020/p2p-driver/parameter-result.json` |
| Patch della sola libcuda | Il flag diventa positivo, ma la lettura diretta restituisce dati errati | `gpu-followup-20261020/p2p-driver/libcuda-only-result.json` |
| BAR1 statico e VRAM limitata | Alcuni tentativi falliscono durante l'inizializzazione; necessari recuperi della VM | `gpu-followup-20261020/p2p-driver/static-capped-events.json` |
| BAR1 dinamico e memoria virtuale CUDA | Scrittura A2000 verso Ada corretta fino a 64 MiB; scrittura inversa e letture errate | `gpu-followup-20261020/p2p-driver/dynamic-matrix-fenced-events.json` |
| Lettura CPU delle finestre BAR1 | Dati corretti su entrambe; conferma l'accesso CPU, non GPU verso GPU | `gpu-followup-20261020/p2p-driver/cpu-bar-observations.json` |
| Indirizzi fisici e virtuali Xen, alias | Nessun P2P completo; alcuni timeout | `gpu-followup-20261020/p2p-driver/trial-index.json` |
| ACS, coerenza, NoSnoop, Relaxed Ordering, pacchetti piccoli | Nessuna matrice numerica completa corretta | `gpu-followup-20261020/p2p-driver/trial-index.json` |
| Motori di copia e dispositivo che avvia il trasferimento | Passa solo A2000 verso Ada avviato dall'A2000 | `gpu-followup-20261020/p2p-driver/ce-small-events.json` |
| Scrittura UEFI diretta della voce P2P | Rifiutata con WRITE_PROTECTED; valore ancora zero | `gpu-followup-20261020/uefi-p2p/P2P-enable-result.txt` |
| Apertura diretta del menu BIOS nascosto | Pagina non pubblicata nell'interfaccia HII disponibile | `gpu-followup-20261020/uefi-p2p/native-form-log.txt` |
| Scrittura controllata di un byte nella configurazione flash | Riuscita: SaSetup 0x3E3 passa a 1 e persiste dopo riavvio | `gpu-followup-20261020/firmware-mod/SaSetup-persisted.verified.json` |
| Tre prove VM dopo modifica BIOS, anche con ACS e ordinamento modificati | Sempre tre operazioni errate su quattro | Tre file `bios-slot-enabled-…-events.json` recuperati in questa directory |
| Prima prova Linux in RAM | Invalida: tunnel USB4 non autorizzato, una sola GPU | `gpu-followup-20261020/baremetal-probe/result-before-USB4-authorization.log` |
| Prova Linux in RAM corretta, senza Xen e con IOMMU disabilitato | Due GPU presenti; due driver sperimentali riproducono tre errori su quattro anche con soli 4 byte | `gpu-followup-20261020/baremetal-probe/result.log` |

L'indice dei tentativi driver contiene 25 varianti: 12 matrici complete, 7 prove parziali o timeout e 6 senza test dei dati. Non sono 25 collaudi completi. Nessuna matrice completa supera tutti i controlli. Le prove BIOS e native successive vanno considerate separatamente.

**Cosa dimostrano i risultati**

La prova nativa corretta elimina Xen come condizione necessaria al difetto. Non elimina il driver, perché usa due varianti modificate della stessa famiglia e una libcuda sperimentale. Il registro del kernel contiene inoltre anomalie di rilascio delle mappature. Gli hash dei log nativi coincidono con quelli del riepilogo verificato.

| Operazione nel test nativo | Esito |
| --- | --- |
| Scrittura A2000 esterna verso Ada interna | Corretta |
| Scrittura Ada interna verso A2000 esterna | Dato non arrivato, destinazione ancora zero |
| Lettura remota eseguita dall'Ada | Errata |
| Lettura remota eseguita dall'A2000 | Errata |

Il fallimento su 4 byte rende inadeguata una spiegazione basata soltanto sulla saturazione della banda. La causa esatta fra instradamento della piattaforma, controller USB4 e mappature del driver resta da isolare.

Il BIOS è stato effettivamente cambiato: il registro CCFG dello slot interno è passato da `0x0E008077` a `0x04008077`. Il registro della porta Thunderbolt è rimasto `0x0E009077`; la lettura attuale conferma entrambi. I successivi tentativi di cambiare altri bit CCFG non hanno modificato il valore letto. Non è quindi corretto affermare che tutti quei controlli siano stati disabilitati e poi collaudati.

La voce P2P modificata riguarda una porta PCIe CPU. Nei menu esaminati, le porte TCSS/Thunderbolt hanno impostazioni separate e nessun equivalente P2P esposto. Anche gli header [Intel FSP per Alder Lake-P](https://github.com/intel/FSP/blob/master/AlderLakeFspBinPkg/IoT/AlderLakeP/Include/FspsUpd.h) distinguono le relative policy. Non c'è evidenza che modificare gli offset P2P vicini abiliti Thunderbolt.

I vecchi file `uefi-p2p/SaSetup-enabled.verified.json` e `server-state-final.json` descrivono un tentativo precedente fallito. Lo stato persistente corretto è documentato nella directory `firmware-mod`.

**Percorso per risolvere**

1. **Stabilire il comportamento nativo con driver originale.** Nello stesso ambiente Linux, usare librerie e moduli originali coerenti, interrogare accesso peer e provarne l'abilitazione. Se supportata, verificare campioni CUDA ufficiali e dati ricevuti in entrambe le direzioni. Se rifiutata, registrare il rifiuto: forzare il flag non costituisce un successo. Questa combinazione nativa originale manca nelle prove esaminate.
2. **Confrontare driver originali coerenti sulla stessa topologia.** Se la prova nativa originale nega l'accesso, distinguere il supporto della coppia Ampere/Ada dalle mappature BAR1 sperimentali. Un eventuale confronto fra versioni deve cambiare un solo elemento per volta e mantenere risultati numerici verificabili. Non basta modificare il valore restituito da una funzione di capacità.
3. **Proseguire sul firmware solo identificando il percorso TCSS.** L'analisi successiva del modulo SiInitFsp ha ricondotto il callsite inizialmente sospetto a porte PCH con device 0x1b/0x1c/0x1d, non alla porta Thunderbolt 00:07.0. Questa pista non giustifica quindi una patch. Inoltre la definizione pubblica di CCFG a 0xD0 va verificata per il controller esatto: leggere lo stesso offset non prova che i bit abbiano lo stesso significato. Il BIOS 1.27 non è una soluzione documentata solo perché contiene la stessa voce P2P.
4. **Per utilizzare le GPU insieme, collaudare il percorso RAM già funzionante sul carico reale.** Tenere disabilitato il trasporto P2P nel solo ambiente di prova, lasciare disponibile la memoria condivisa NCCL e confrontare throughput, correttezza e memoria contro Ada sola. Promuovere il risultato soltanto se il confronto completo dimostra un vantaggio. Questo risolve l'utilizzo multi-GPU, non l'accesso diretto fra le VRAM.

La soluzione si considera raggiunta quando il percorso previsto passa ripetutamente controlli numerici di lettura, scrittura e copia in entrambi i versi, su dimensioni diverse e dopo riavvio. I dati vanno controllati sul destinatario, prima di misurare banda e collettive NCCL. La documentazione [NVIDIA sulla diagnosi GPU](https://docs.nvidia.com/deeplearning/nccl/user-guide/docs/troubleshooting/gpu_troubleshooting.html) distingue i controlli effettivi del percorso dalle sole indicazioni di supporto.

**Utilizzo delle due GPU durante la ricerca**

Le copie attraverso RAM con due buffer hanno già verificato circa 1,75 GB/s Ada verso A2000 e 3,80 GB/s A2000 verso Ada. Questo permette comunicazione corretta fra le schede, ma non ripara il P2P diretto. La configurazione NCCL con P2P disabilitato e trasporto tramite RAM ha superato anche un collaudo breve del modello a 32 blocchi: un aggiornamento misurato a circa 3.534 token/s. Il confronto completo con una sola GPU è incompleto e non dimostra un vantaggio di training.

Il codice di produzione resta configurato per una sola GPU: queste prove non hanno convertito la run corrente in training distribuito. Il passaggio a due GPU richiederebbe una configurazione separata, verifiche di ripresa e confronto di prestazioni; non va applicato silenziosamente al checkpoint esistente.
