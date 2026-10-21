> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# CaskLogic — campionamento TX/RX durante PUSH

Candidato diagnostico locale. Non costituisce una soluzione P2P né una misura delle prestazioni utilizzabili: il dato trasferito viene verificato indipendentemente. Nessuna esecuzione GPU è compresa nella preparazione di questo candidato.

Quattro fasi: Ada→A2000 con SM, Ada→A2000 con `CUDA_COPY_REQUEST`, A2000→Ada con SM, A2000→Ada con `CUDA_COPY_REQUEST`. Il secondo nome indica una richiesta CUDA DtoD: questo programma non usa CUPTI e non dichiara il motore CE osservato. La precedente traccia CUPTI non sostituisce una traccia della nuova esecuzione.

Quattro allocazioni VMM da 8 MiB restano vive fino a tutti i confronti. Ogni sorgente è accessibile soltanto al proprietario; ogni destinazione a entrambe le GPU. Solo la sorgente può quindi eseguire ordinariamente entrambe le operazioni sugli operandi. UUID, BDF, proprietà degli handle, diritti ai due estremi, contesto e stream sono verificati.

Prima di ogni finestra si inizializza 1 MiB sul proprietario e si confrontano integralmente sorgente e poison dopo sincronizzazione. Durante la finestra non sono effettuate inizializzazioni H2D, verifiche D2H, letture della configurazione PCI o stampe del thread principale. Un thread separato chiama esclusivamente quattro getter NVML: TX e RX per entrambe le GPU. Ogni invocazione ha timestamp monotonic iniziale/finale e codice di ritorno.

- Baseline: circa 200 ms.
- Finestra attiva: obiettivo almeno 1,2 s, limite 5 s. Una sola batch da 64 copie × 1 MiB è in volo. SM usa un kernel con 64 passaggi limitati e store volatile; CUDA richiede 64 copie sullo stesso stream. Una fence di sistema conclude il lavoro dei thread SM attivi. L'evento dello stream è interrogato circa ogni 1 ms.
- Limite aggiuntivo: 4096 batch. Raggiungerlo prima di 1,2 s rende la durata non qualificata, non un PASS della finestra.
- Coda osservata: circa 100 ms dopo l'ultimo evento completato.
- Arresto e join del sampler prima di qualunque D2H di verifica o nuovo snapshot PCI.

Le statistiche primarie attive includono soltanto le chiamate completamente contenute in `[active_start+40 ms, active_end]`. La baseline quieta usa `[sampler_start+40 ms, active_start]`. Le due guardie tengono conto dei 20 ms della misura NVML ed escludono la prima finestra influenzabile dal traffico precedente. Per entrambi gli intervalli servono almeno cinque campioni validi per endpoint/contatore. La coda `TAIL` stampata include invece tutto lo stadio: i suoi primi campioni possono riflettere gli ultimi trasferimenti, e non vengono chiamati baseline quieta.

Le chiamate ai quattro contatori sono seriali, non simultanee. I valori sono KB/s aggregati di tutto il traffico PCIe di ciascun endpoint, non una cattura di TLP e non contatori del solo payload. Anche la finestra attiva comprende invii di comandi e interrogazioni di eventi. `submitted_payload_bytes` conta le richieste del programma, non i byte arrivati a destinazione. Nessuna sottrazione o integrazione permette da sola di certificare instradamento, no-staging, indirizzo o punto di scarto. Il verso A2000→Ada è il controllo positivo da ricontrollare nella stessa esecuzione.

Il caricamento è dinamico da `libnvidia-ml.so.1`; sono risolti soltanto init/shutdown e getter. Le identità NVML sono confrontate con UUID e BDF attesi; tutti e quattro i getter devono essere disponibili al preflight. Un errore conserva `rc`, `valid=0` e sentinella UINT_MAX; non viene sostituito da zero né incluso nelle medie. Errori successivi, overflow, eccezioni o meno di cinque campioni interni per ciascun endpoint/contatore invalidano la qualificazione della fase.

`TRAFFIC_PROGRAM_END protocol_complete=1` indica quattro confronti completati; `qualified_windows=4` è un requisito separato. RC 0: protocollo e finestre qualificati, tutti i dati corretti. RC 5: protocollo e finestre qualificati, almeno un payload errato. RC 6: almeno una finestra non qualificata. RC 27: aborto. Un limite di processo/boot esterno resta necessario: il deadline nel programma non può interrompere una chiamata driver bloccata.

I controlli offline usano il vero `nvml_sampler.h` contro una libreria NVML simulata, senza CUDA o GPU: successo, identità errata, indisponibilità al preflight, errore durante il campionamento. Quattro scenari più sedici assert sui confini temporali e le statistiche passano con ASan/UBSan. `source-provenance.json` identifica sorgenti e header; i file delle fixture simulate non fanno parte del payload nativo.

Fonte NVML: [documentazione ufficiale](https://docs.nvidia.com/deploy/nvml-api/latest/api/group__nvmlDeviceQueries.html). L'header finale è il C originale del pacchetto NVIDIA [cuda-nvml-dev-12-6 12.6.37-1](https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2004/x86_64/cuda-nvml-dev-12-6_12.6.37-1_amd64.deb), SHA `2ec2431ac69cf205ecf6cd2bf24d0402997975505d574cee5aec6a85a4c520c9`, estratto dal coordinatore. Tutte le fixture sono state ricompilate e ripassate con questo header. La copia preliminare NVIDIA/go-nvml, che avvolge l'handle per Go, è mantenuta soltanto come riferimento di provenienza; non è inclusa nel candidato finale.
