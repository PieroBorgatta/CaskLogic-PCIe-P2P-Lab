> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# CaskLogic — storico verificato delle prove P2P

Aggiornamento: 21 ottobre 2026, fino ai controlli CPU in lettura/scrittura, alla ricollocazione BAR sotto 4 GiB, alla prova UVM da 4 KiB, alle cinque fasi NoSnoop/ordering, alla variante SYS_COH, al confronto nativo SM/CE osservato con CUPTI e al ripristino finale verificato delle 03:19 CEST. Ricostruzione da file locali; nessuna nuova prova GPU, operazione remota o modifica del server eseguita per redigere questo documento. I ripristini descritti nella prima parte sono eventi storici: il candidato FSP combinato è stato poi riapplicato per le prove corrette e infine rimosso con il ripristino verificato delle 03:19, documentato nell’ultima appendice.

**Esito complessivo: il P2P completo non è risolto.** Le matrici numeriche complete disponibili mantengono lo stesso comportamento: scrittura A2000 esterna → Ada interna riuscita, scrittura inversa e letture remote errate. Le due modifiche FSP recenti hanno cambiato davvero i registri, ma non i risultati del programma allora usato; la revisione successiva ha individuato il limite di sincronizzazione descritto sotto. Stato finale e conclusioni operative sono in [ESITO.md](ESITO.md); questo indice non lo modifica.

Esisteva già [diagnosi-e-soluzione.md](../p2p-review-20261020/diagnosi-e-soluzione.md), che copre la prima parte dello storico. Le proposte e le conclusioni temporanee di quel documento precedono le due prove FSP qui integrate. Le tabelle seguenti distinguono test eseguiti, test senza risultato numerico e sole preparazioni; un file di piano non conta come esecuzione.

## Limite emerso nella revisione della sincronizzazione

**I risultati precedenti del test a 4 byte vanno letti con un limite aggiuntivo.** Il sorgente usato nei nativi non sincronizzava esplicitamente il device proprietario dopo la copia host→device e dopo l'azzeramento della sorgente, prima di accedere a quella memoria da un'altra GPU. Non basta l'ordinamento del default stream del device che esegue il kernel per ordinare operazioni ancora pendenti sull'altro device. Le osservazioni di corruzione e i registri letti restano fatti registrati; attribuirne la causa al solo percorso hardware richiede la ripetizione corretta.

La prova separata `native-sync-probe` è stata successivamente eseguita: sincronizzazione dell'owner nei due punti, verifica CPU locale del seed e dello zero prima dell'accesso peer, stessi quattro byte e stessi kernel, tutti i free ancora ritardati. I quattro readback locali passano, i tre errori peer persistono. Gli snapshot PCIe/AER correlano errori PCI alle letture. Il readback locale verifica l'allocazione proprietaria e non trasferisce dati fra GPU. L'aggiornamento finale riporta queste evidenze e le prove ulteriori.

## Configurazione e convenzioni

Minisforum MS-01 AHWSA, Core i9-12900H, BIOS 1.26, NVIDIA 595.99.02. RTX 2000 Ada 16 GB interna a 01:00.0, UUID `00000000-0000-0000-0000-000000000001`; RTX A2000 12GB esterna a 06:00.0, UUID `00000000-0000-0000-0000-000000000002`, dietro bridge ASMedia e root Thunderbolt 00:07.0. Il collegamento esterno trasporta PCIe tramite USB4/Thunderbolt. I BDF della VM differiscono da quelli fisici; non vanno scambiati con gli indici CUDA. Nelle prove native verificate, indice 0=Ada e indice 1=A2000. [Identità, BAR e log nativo finale](native-d1-gpu-results/result.log).

Le date delle directory sono etichette di raccolta, non l'istante di ogni prova. Gli orari nella tabella delle 25 varianti provengono dal primo evento registrato di ogni tentativo e sono espressi in Europe/Rome, CEST (UTC+2), il 20 ottobre. Le prove FSP con directory 20261021 sono avvenute dopo mezzanotte locale.

## Baseline e accesso CUDA

| Gruppo | Stato ed esito osservato | Evidenza |
| --- | --- | --- |
| Calcolo, VRAM e stress delle due GPU | Eseguiti: controlli locali corretti,5 minuti per GPU e15 minuti insieme. I 7 casi P2P nvbandwidth risultano *Waived* perché non esistono coppie peer accessibili: non sono successi numerici. | [Riepilogo e casi saltati](../gpu-audit-20261020/summary.json) |
| Driver originale in container nella VM | Eseguito: accesso CUDA peer falso in entrambi i versi; identità GPU registrate. | route_confirmation.json *(artefatto locale non pubblicato)* |
| Driver originale fuori Docker, nel sistema operativo della VM | Eseguito: `cuInit=0`, `cuDeviceCanAccessPeer=0` nei due versi. Il nome host-p2p non identifica un boot Linux fisico. | [host-p2p.json](../gpu-followup-20261020/host-p2p.json) |
| Nuova lettura con driver originale nella VM | Eseguita senza kernel o copie: CUDA falso, contemporaneamente nvidia-smi P2P read/write=OK. La seconda indicazione non certifica trasferimenti utilizzabili. | [verifica-attuale.json](../p2p-review-20261020/verifica-attuale.json) |
| ForceP2P/RM su driver originale | Eseguito: parametri runtime, capability CUDA ancora falsa. | [parameter-result.json](../gpu-followup-20261020/p2p-driver/parameter-result.json) |
| Sola patch libcuda mixed-architecture | Eseguita su copia sperimentale 595.99.02: capability vera, prima lettura 64 KiB corrotta (`edcba987`, atteso `12346641`), RC 5. | [patch e hash](../gpu-followup-20261020/p2p-driver/libcuda-experiment/patch.json), [capability](../gpu-followup-20261020/p2p-driver/libcuda-only-result.json), log numerico *(artefatto locale non pubblicato)*, [stato esecuzione](../gpu-followup-20261020/libcuda_peer_validation/stages.json) |
| Capability vendor GPUDirect/clique in VM | Ispezione eseguita: nessuna firma GPUDirect nelle capability lette. Nessuna prova di una clique valida e funzionante; aggiungerla è solo un'ipotesi, non un risultato. | [capability PCI](../gpu-followup-20261020/pci-gpudirect-capabilities.json) |

La patch libcuda elimina un rifiuto software fra architetture diverse; il port kernel BAR1 e l'inoltro della piattaforma sono livelli distinti. L'analisi del codice e dei limiti è in [ANALISI-DRIVER.md](../p2p-thunderbolt-firmware-20261020/driver-analysis/ANALISI-DRIVER.md).

## Varianti driver, mapping e controlli PCIe: tutti i 25 tentativi indicizzati

Ricontrollati gli output effettivi dei 25 file `*-events.json` contro l'indice: **12 matrici complete,7 prove ridotte/interrotte o timeout,6 tentativi senza confronto dati**. Nessuna delle12 matrici complete passa tutte le operazioni. La proprietà storica `completed_data_probe=true` dell'indice non significa automaticamente quattro confronti conclusi: per esempio comprende anche `GATE_TIMEOUT`. La classificazione qui usa il contenuto dei log.

| Inizio CEST 20/10 | Tentativo e log primario | Portata reale | Risultato |
| --- | --- | --- | --- |
| 21:51:16 | [parameter](../gpu-followup-20261020/p2p-driver/parameter-events.json) | Senza confronto dati | Interrogazione capability: resta falsa in entrambi i versi; nessuna matrice dati. |
| 21:59:54 | [static-capped](../gpu-followup-20261020/p2p-driver/static-capped-events.json) | Senza confronto dati | Tentativo BAR 1 statico con VRAM limitata: problemi di inizializzazione/rilascio; nessun confronto dati. |
| 22:01:56 | [dynamic-full-vram](../gpu-followup-20261020/p2p-driver/dynamic-full-vram-events.json) | Ridotta/interrotta/timeout | Prima lettura da 64 KiB corrotta; arresto prima della matrice completa. |
| 22:03:26 | [dynamic-vmm](../gpu-followup-20261020/p2p-driver/dynamic-vmm-events.json) | Ridotta/interrotta/timeout | VMM esplicita: prima lettura da 64 KiB corrotta. |
| 22:04:25 | [dynamic-diagnostic](../gpu-followup-20261020/p2p-driver/dynamic-diagnostic-events.json) | Ridotta/interrotta/timeout | Variante diagnostica: prima lettura da 64 KiB corrotta. |
| 22:05:13 | [xen-bar-translation](../gpu-followup-20261020/p2p-driver/xen-bar-translation-events.json) | Ridotta/interrotta/timeout | Conversione indirizzi Xen: prima lettura da 64 KiB corrotta. |
| 22:05:57 | [dynamic-writes](../gpu-followup-20261020/p2p-driver/dynamic-writes-events.json) | Ridotta/interrotta/timeout | Solo scritture: passa 1 → 0, fallisce 0 → 1; RC 6. |
| 22:06:56 | [dynamic-matrix-fenced](../gpu-followup-20261020/p2p-driver/dynamic-matrix-fenced-events.json) | Matrice completa | 4 dimensioni,64 KiB/1 MiB/16 MiB/64 MiB:12 errori su 16 confronti. |
| 22:07:43 | [dynamic-cpu-probe](../gpu-followup-20261020/p2p-driver/dynamic-cpu-probe-events.json) | Ridotta/interrotta/timeout | Prima coppia read/write osservata, poi CPU_PROBE_TIMEOUT; RC 9. |
| 22:08:26 | [dynamic-cpu-probe-v2](../gpu-followup-20261020/p2p-driver/dynamic-cpu-probe-v2-events.json) | Matrice completa | Sonda CPU sincronizzata; matrice GPU 3 errori su 4. |
| 22:09:13 | [acs-gpa-matrix](../gpu-followup-20261020/p2p-driver/acs-gpa-matrix-events.json) | Matrice completa | ACS e indirizzi guest:12 errori su 16 confronti, fino a 64 MiB. |
| 22:09:40 | [acs-hpa-matrix](../gpu-followup-20261020/p2p-driver/acs-hpa-matrix-events.json) | Senza confronto dati | Tentativo indirizzi fisici host: nessun risultato numerico acquisito; container/driver non si chiudono regolarmente. |
| 22:14:29 | [coherent-small](../gpu-followup-20261020/p2p-driver/coherent-small-events.json) | Matrice completa | Variante PTE coerenti:3 errori su 4 da 64 KiB. |
| 22:15:08 | [nosnoop-off-small](../gpu-followup-20261020/p2p-driver/nosnoop-off-small-events.json) | Matrice completa | NoSnoop disabilitato:3 errori su 4 da 64 KiB. |
| 22:16:33 | [ce-small](../gpu-followup-20261020/p2p-driver/ce-small-events.json) | Matrice completa | Motore copia,4 combinazioni: passa solo 1 → 0 quando avviata dalla GPU 1. |
| 22:17:21 | [acs-zero-small](../gpu-followup-20261020/p2p-driver/acs-zero-small-events.json) | Matrice completa | ACS azzerato:3 errori su 4 da 64 KiB. |
| 22:21:11 | [packet128-small](../gpu-followup-20261020/p2p-driver/packet128-small-events.json) | Matrice completa | Pacchetti 128 byte:3 errori su 4 da 64 KiB. |
| 22:23:07 | [packet128-word](../gpu-followup-20261020/p2p-driver/packet128-word-events.json) | Matrice completa | Pacchetti 128 byte, payload 4 byte:3 errori su 4. |
| 22:26:29 | [xen-alias-word](../gpu-followup-20261020/p2p-driver/xen-alias-word-events.json) | Matrice completa | Alias GPA:3 errori su 4 da 4 byte. |
| 22:27:33 | [static-word-v2](../gpu-followup-20261020/p2p-driver/static-word-v2-events.json) | Senza confronto dati | Secondo tentativo statico: nvidia-smi non trova device; nessun confronto dati. |
| 22:27:57 | [mailbox-word](../gpu-followup-20261020/p2p-driver/mailbox-word-events.json) | Senza confronto dati | Preparazione/tentativo mailbox senza output dei confronti. |
| 22:28:45 | [coherent-config-gate](../gpu-followup-20261020/p2p-driver/coherent-config-gate-events.json) | Senza confronto dati | Tentativo con gate senza output dei confronti. |
| 22:30:29 | [coherent-config-gate-v2](../gpu-followup-20261020/p2p-driver/coherent-config-gate-v2-events.json) | Matrice completa | Ripetizione con gate/coerenza:3 errori su 4 da 4 byte. |
| 22:31:00 | [mailbox-word-clean](../gpu-followup-20261020/p2p-driver/mailbox-word-clean-events.json) | Matrice completa | Ripetizione mailbox:3 errori su 4 da 4 byte. |
| 22:33:59 | [ccfg-peer-word](../gpu-followup-20261020/p2p-driver/ccfg-peer-word-events.json) | Ridotta/interrotta/timeout | Il programma arriva al gate ma termina GATE_TIMEOUT; nessun trasferimento confrontato. |

Le prove a 16/64 MiB non sono misure di banda P2P valide: verificano solo i dati nei percorsi che completano il confronto. Nelle matrici complete passa una delle quattro operazioni per dimensione; le altre falliscono. La riduzione fino a 4 byte rende insufficiente una spiegazione basata soltanto sulla saturazione della banda.

La sonda CPU conferma che le finestre BAR1 contengono i pattern attesi per entrambe le GPU; non dimostra che una GPU possa leggerle attraverso l'altro root. [cpu-bar-observations.json](../gpu-followup-20261020/p2p-driver/cpu-bar-observations.json). Il port dinamico mappa allocazioni esplicite senza richiedere BAR1 statica globale; i tentativi statici con VRAM limitata non hanno prodotto una matrice dati utilizzabile. Le varianti Xen GPA/HPA e alias non hanno risolto il problema. Alcuni sorgenti successivi contengono indirizzi diagnostici fissi: non rappresentano la build dinamica conservata per gli ultimi test. [Audit dei moduli effettivi](driver/build-audit.json).

## ACS, IOMMU, firmware SaSetup e primo Linux nativo

| Gruppo | Stato ed esito | Evidenza primaria |
| --- | --- | --- |
| ACS, NoSnoop, Relaxed Ordering, coerenza e dimensione pacchetti nella VM | Eseguiti nelle varianti sopra; nessuna matrice interamente corretta. Non equivalgono ad aver rimosso ogni possibile controllo del root. | Log `acs-*`, `nosnoop-*`, `coherent-*`, `packet128-*` nella tabella precedente |
| Scrittura runtime CCFG prima dei trial FSP | Tentata, ma i bit riletti non cambiano. Non si può descriverla come test con bit realmente disabilitati. | [ccfg-writability.json](../gpu-followup-20261020/p2p-driver/ccfg-writability.json), [log del primo nativo valido](../gpu-followup-20261020/baremetal-probe/result.log) |
| SaSetup: scrittura diretta UEFI della voce P2P | Tentata e rifiutata con `EFI_WRITE_PROTECTED`; non abilitata da questo tentativo. | P2P-enable-result.txt *(artefatto locale non pubblicato)* |
| SaSetup: apertura del form BIOS nascosto | Eseguita, form non pubblicato nel database HII disponibile. Non è un'attivazione riuscita del menu. | native-form-log.txt *(artefatto locale non pubblicato)* |
| SaSetup: scrittura controllata del byte di configurazione | Eseguita con FPT, settore 4 KiB a 01024000, byte 010243F9 da 0 a 1; altri byte invariati. SaSetup[3E3]=1 persiste. CCFG D1 cambia 0E008077→04008077; D7 resta 0E009077. | [verifica scrittura](../gpu-followup-20261020/firmware-mod/nv-write-verified.json), [persistenza variabile](../gpu-followup-20261020/firmware-mod/SaSetup-persisted.verified.json), [stato persistente](../gpu-followup-20261020/firmware-mod/nv-p2p-state.json) |
| Tre prove VM dopo SaSetup | Tutte eseguite: standard, ACS off, coherent/NoSnoop off; ciascuna 3 errori su 4. Il successo della scrittura BIOS non era successo P2P. | [standard](../p2p-review-20261020/bios-slot-enabled-word-events.json), [ACS off](../p2p-review-20261020/bios-slot-enabled-acs-off-word-events.json), [coherent/NoSnoop](../p2p-review-20261020/bios-slot-enabled-coherent-nosnoop-off-events.json) |
| Primo boot Linux in RAM | Eseguito ma invalido per P2P: GPU count 1, tunnel USB4 non autorizzato, entrambi i tentativi RC 3. Non consente deduzioni sul P2P nativo. | log prima autorizzazione USB4 *(artefatto locale non pubblicato)* |
| Boot Linux in RAM corretto, prima dei trial FSP | Eseguito con due GPU, senza Xen, DMA IOMMU disabilitata. Driver diagnostic e coherent: entrambi 3 errori su 4 con payload 4 byte. Il secondo tenta anche ACS/NoSnoop/ordering e CCFG; CCFG resta 04008077/0E009077. | [result.log](../gpu-followup-20261020/baremetal-probe/result.log), kernel.log *(artefatto locale non pubblicato)*, [verifica](../gpu-followup-20261020/baremetal-probe/verified-result.json) |

I vecchi file chiamati `SaSetup-enabled.verified.json` non sostituiscono la verifica persistente successiva: il valore finale corretto della variabile è quello documentato in `firmware-mod/SaSetup-persisted.verified.json`. Il primo nativo valido elimina Xen come condizione necessaria al difetto; usa però driver e libcuda sperimentali, perciò non esclude errori in quel codice.

## Ricerca TCSS e due flash FSP effettivamente eseguiti

| Passaggio | Stato ed esito osservato | Evidenza |
| --- | --- | --- |
| Confronto BIOS 1.26/1.27 e disassemblaggio TCSS | Analisi locale eseguita: SiInitFsp identico fra le immagini esaminate; ricostruito il percorso D7 e distinto dalle porte PCH. Non è stato installato il BIOS 1.27 come prova P2P. | confronto moduli *(artefatto locale non pubblicato)*, [analisi D7](../p2p-thunderbolt-firmware-20261020/firmware-analysis/TCSS-D7-analysis.md) |
| Sonda runtime REGBAR C6 | Quattro tentativi eseguiti: bit 25, 26, 27 separati e insieme. Tutti ignorati, letture REGBAR/ECAM/sysfs concordi immediate e dopo 50 ms; registro finale ripristinato. Nessun test GPU attribuito a bit che non cambiarono. | [runtime-c6/result.json](runtime-c6/result.json) |
| Lettura nativa sicurezza e dump SPI | Eseguita: CPUID 906A3 senza hypervisor, MSR13A=1000000000, TXT status zero; due dump freschi uguali. KM/BPM verificati come placeholder FF. È una lettura di preparazione, non un collaudo P2P. | native-security.txt *(artefatto locale non pubblicato)*, [verifica dump](fresh-spi-verification.json), [interpretazione e limiti](firmware-candidate/bootguard-review.md) |
| Primo candidato FSP: D7 bit 25–27 | **Flash eseguito e riletto**,19 settori nell'intervallo01B16000–01B29000. Una modifica semantica nel PE. D7:F0/F2=00009077 realmente persistenti; D1 resta 04008077. | rilettura flash D7 *(artefatto locale non pubblicato)*, stato flash *(artefatto locale non pubblicato)*, [registri dopo D7](firmware-trial-registers.json) |
| GPU nella VM dopo D7 | Test 4 byte eseguito,3 errori su 4, stessi versi; driver stock ripristinato. | log GPU VM *(artefatto locale non pubblicato)*, [verifica risultati](driver/candidate/gpu-result.json), [ripristino driver](driver/candidate/restore.json) |
| GPU nativa dopo D7 | Test 4 byte eseguito,3 errori su 4. D7=00009077 prima/dopo driver/test; Xen assente. Assert IOVAS presenti, vecchio programma liberava fra le due coppie di confronti. La prima lettura falliva comunque prima di qualsiasi free esplicito. | [log nativo D7](native-gpu-results/result.log), kernel nativo D7 *(artefatto locale non pubblicato)*, [verifica D7](native-gpu-results/verified-result.json) |
| Secondo candidato FSP: D7 più D1 bit 26 | **Flash eseguito e riletto**,30 settori nell'intervallo01B0B000–01B29000. Due byte semantici rispetto al PE originale, uno rispetto a D7-only. D1=00008077 e D7:F0/F2=00009077. | rilettura combinata *(artefatto locale non pubblicato)*, stato flash *(artefatto locale non pubblicato)*, [registri combinati](firmware-d1-trial-registers.json), [audit delle due modifiche](firmware-candidate-d1/combined-verification.json) |
| GPU nativa dopo D7+D1, tutti i free ritardati | Test 4 byte eseguito,3 errori su 4. Quattro confronti completati prima di tutti i free. Identità GPU, hash del pacchetto e file nell'initrd verificati. IOVAS residui circa 266 ms dopo `context_exit_begin`, primo assert circa 290 ms dopo: gli errori di chiusura osservati non causano retroattivamente quei confronti falliti.15 marker kmsg soppressi dal rate limit, presenti in stdout; ordine ricostruito con 10 marker comuni. | [log dati e fasi](native-d1-gpu-results/result.log), kernel *(artefatto locale non pubblicato)*, [verifica completa](native-d1-gpu-results/verified-result.json), [analisi temporale](native-d1-gpu-results/ANALISI.md) |
| Ripristino finale di entrambe le modifiche FSP | **Eseguito e riletto**, blocco originale30 settori identico, zero byte differenti. D1 torna 04008077, D7:F0/F2 tornano 0E009077. SaSetup P2P precedente conservato. Avvii temporanei rimossi, boot originale invariato, VM/GPU disponibili e driver stock. | rilettura ripristino *(artefatto locale non pubblicato)*, [registri finali](final-registers.json), [pulizia verificata](cleanup-verified.json), stato finale *(artefatto locale non pubblicato)* |

Gli interventi FSP sono quindi **due flash sperimentali realmente eseguiti e poi annullati**, separati dalla precedente modifica della variabile SaSetup tuttora conservata. Non sono stati scritti i dump SPI integrali marcati `ANALYSIS-ONLY`; sono stati scritti e confrontati soltanto i blocchi indicati.

## Altre prove eseguite, senza successo P2P diretto

Le copie attraverso memoria host e NCCL sono state effettivamente provate e possono produrre dati corretti pur con P2P indisponibile. Questo storico le include per evitare che un successo NCCL venga scambiato per P2P diretto: non propone un cambio di trasporto come soluzione richiesta.

- NCCL baseline, copie tramite motore di copia in invio/ricezione/entrambi,4 e 8 canali:8 esecuzioni RC 0. I nomi `direct_4ch`/`direct_8ch` sono etichette del piano, non prova di VRAM→VRAM diretta. [communication/stages.json](../gpu-followup-20261020/communication/stages.json), conferma del percorso *(artefatto locale non pubblicato)*.
- Prove multiprocesso `shm` e `ce_send`: eseguite, RC 0. [multiprocess_validation/stages.json](../gpu-followup-20261020/multiprocess_validation/stages.json).
- Collaudo sintetico DDP32 con P2P disabilitato: eseguito, un aggiornamento misurato, repliche coincidenti sul campione; circa 3534 token/s. Non è qualità linguistica, non è il training di produzione e non dimostra superiorità su una GPU. La matrice di confronto successiva si ferma a `dual16_default` RC 137; le righe successive nel file di piano non sono esecuzioni. [risultato DDP32](../gpu-followup-20261020/verified_smoke_ddp32.json), [stadi realmente conclusi](../gpu-followup-20261020/model_benchmarks_verified/stages.json), [prova SHM separata](../gpu-followup-20261020/ddp_direct_check/stages.json).

## Preparato o analizzato, senza esito hardware dimostrato

| Oggetto | Classificazione corretta |
| --- | --- |
| Modifica del menu BIOS per mostrare la voce P2P | Candidato e confronto binario preparati; la modifica realmente confermata è il byte della variabile SaSetup, non l'installazione della patch del menu. [analisi menu](../gpu-followup-20261020/firmware-mod/menu-patch-analysis.json). |
| BIOS ufficiale1.27 | Analizzato/confrontato localmente; nessuna prova in questo storico dimostra installazione e soluzione P2P con 1.27. |
| Firmware SPI integrali `ANALYSIS-ONLY` | Artefatti per confronto; non descriverli come flash integrali del chip. I trial reali sono limitati ai19/30 settori documentati. |
| Correzione del cleanup/lifetime del port BAR1 | Difetti identificati staticamente e osservati nei log; nessuna nuova build correttiva né prova riuscita di tale fix in questo ciclo. Il test finale modifica solo il momento dei free nel programma, non il driver. [analisi cleanup](native-d1-probe/CLEANUP-ANALYSIS.md). |
| Suite locale dei gate UEFI e revisioni indipendenti | Eseguite come controlli dei file/CRC/stati e del codice; non sono trasferimenti GPU. I gate poi realmente eseguiti dal firmware hanno log separati nelle cartelle `native-*-flash-results`. [gate D7](firmware-candidate/TcssRegionGate.validation.json), [gate D7+D1](firmware-candidate-d1/TcssRegionGate.validation.json). |
| Nativo con modulo e libcuda originali, seguito da copie ufficiali se supportate | Mancante nelle evidenze esaminate. La baseline originale disponibile è nella VM; tutti i nativi numerici di questo storico usano driver/libreria sperimentali. |
| Supporto P2P completo, atomiche, managed-memory o training di produzione sulle due GPU | Non dimostrato. La prova minima 4 byte non qualifica tutte le API CUDA e il successo di una sola direzione non abilita le altre. |

Questo indice non trasforma intenzioni, script o file di configurazione in attività eseguite. Il limite di sincronizzazione dei primi programmi è stato affrontato mediante la ripetizione corretta sotto documentata. Nessuna delle prove dimostra l'impossibilità assoluta del percorso hardware né esclude altre restrizioni o errori di mapping.

## Aggiornamento: sincronizzazione, PTE e allineamento

| Passaggio | Stato ed esito | Evidenza |
| --- | --- | --- |
| Riapplicazione candidato FSP combinato per ripetizione sincronizzata | Flash limitato agli stessi30settori eseguito e verificato. D1=00008077,D7:F0/F2=00009077. È una successiva riapplicazione, non il precedente stato ripristinato. | gate readback *(artefatto locale non pubblicato)*, [registri](firmware-sync-trial-registers.json) |
| Nativo con owner sincronizzati e verificati, snapshot PCI | Eseguito: owner4/4corretti, peer3/4errati. PCI_STATUS passa0010→2010 sul lettore e sul relativo root durante ciascuna lettura. | [verifica](native-sync-gpu-results/verified-result.json), [analisi](native-sync-gpu-results/ANALISI.md) |
| Prima immagine con logging RM/UVM | Boot interrotto prima del caricamento NVIDIA: nome dei file snapshot con due punti incompatibile con FAT. Nessuna prova GPU da contare. Corretto solo il nome dei file nell'immagine successiva. | [log abort](native-instrumented-gpu-results/result.log) |
| Driver strumentato ricostruito dall'archivio originale, con puntatori espliciti | Compilato ed eseguito: quattro catene PTE complete, stessa matrice3/4errata. Scoperto disallineamento A2000: PTE2MiB verso BAR1offset2A0000/4A0000. RM/UVM riportano indirizzi uguali, ma questo non verificava la granularità; parser corretto per distinguere uguaglianza e allineamento. | [provenienza/build](driver-instrumented/build-verification.json), [catene reali](native-instrumented2-gpu-results/pte-chain-validation.json), [analisi allineamento](native-instrumented2-gpu-results/PTE-ALIGNMENT.md) |
| Parametro esistente RM64KBBAR1Mappings=0 | Eseguito senza rebuild del driver: A2000offset4MiB/6MiB, tutte le pagine allineate2MiB; dati e variazioni PCI identici,3/4errati. Correzione del disallineamento confermata, soluzione P2P non ottenuta. | [confronto prima/dopo](native-regalign-gpu-results/alignment-comparison.json), [analisi](native-regalign-gpu-results/ANALISI.md) |
| Clamp sperimentale UVM4KiB | In questa fase preparato come backup; **successivamente compilato e realmente eseguito**, come documentato nell’appendice seguente. Parametro disattivato per default, crossGPUvidmem soltanto. | [manifest](driver-uvm4k/manifest.json) |
| Probe peer_push da4byte a8MiB | In questa fase preparato; **successivamente eseguiti tutti i trenta confronti**, come documentato nell’appendice seguente. Kernel legge VRAM locale e scrive VRAM peer, con quattro buffer da 8 MiB. | sorgenti/contratto *(artefatto locale non pubblicato)*, manifest *(artefatto locale non pubblicato)* |

Il candidato firmware attivo nelle prove di questa appendice deve essere distinto dal ripristino precedente. Per lo stato operativo attuale consultare il resoconto dell'operatore e `ESITO.md`; questo storico documenta eventi e non certifica lo stato live del server.

## Aggiornamento: direzione, BAR1 bassa, pagine piccole e controlli CPU

Le righe seguenti descrivono prove successive, con inizializzazioni dei proprietari sincronizzate e verificate. Sostituiscono la precedente classificazione «solo preparato» per peer_push e UVM4KiB. Nessuna misura di velocità viene qualificata come banda P2P valida per una direzione che fallisce il confronto dati.

| Prova | Stato ed esito | Evidenza |
| --- | --- | --- |
| Controllo CPU sulle finestre vive prima del peer | Eseguito: due pattern letti correttamente per entrambe le GPU, stessi quattro byte e catene nonce/handle/BAR/PTE. Le letture peer restano errate e soltanto la scrittura A2000→Ada passa. | [risultati](native-cpubar-gpu-results/verified-result.json) |
| Trasferimenti solo scrittura peer_push | Eseguiti 30 confronti: 4 B, 4 KiB, 64 KiB, 1 MiB e 8 MiB, tre ripetizioni e due direzioni. Tutti i 15 A2000→Ada passano, tutti i 15 Ada→A2000 falliscono. Nessuna lettura peer precede la prima scrittura fallita: una precedente lettura UR non è necessaria al difetto. | [log](native-push-gpu-results/result.log), [verifica e limiti](native-push-gpu-results/verified-result.json) |
| A2000 BAR1/BAR3 e finestre dei tre bridge sotto 4 GiB | Ricollocazione realmente eseguita prima di NVIDIA: BAR1 0x80000000, BAR3 0x90000000, tre finestre 0x80000000–0x91FFFFFF. Resource tree e rilettura configurazione concordi; CPU legge la parola a 0x80600000. P2P ancora 3/4 errato. Il solo indirizzo alto non basta a spiegare il guasto. | [verifica ricollocazione e dati](native-lowmmio-gpu-results/verified-result.json), [log](native-lowmmio-gpu-results/result.log) |
| CPU legge la destinazione immediatamente dopo la scrittura peer | Eseguito con BAR1 alta e prima del D2H del proprietario: la CPU vede a5a42468 sulla Ada e ancora zero sulla A2000. Il D2H concorda. Nessuna reinizializzazione fra peer e lettura CPU; nessuna scrittura CPU in questa prova. | [analisi](native-cpubar-postwrite-gpu-results/ANALISI.md), [log](native-cpubar-postwrite-gpu-results/result.log) |
| UVM 4 KiB con medesimo controllo CPU dopo scrittura | Eseguito: quattro mapping con page=0x1000, entry=8 e count=512; tutti gli indirizzi allineati e prima parola PTE RM/UVM coincidente. Stessi 3/4 errori e zero osservato sulla A2000 sia da CPU sia da D2H. Questo restringe l’ipotesi della sola granularità 2 MiB; non è lettura delle tabelle hardware. | [verifica](native-uvm4k-postwrite-gpu-results/verified-result.json), [catene](native-uvm4k-postwrite-gpu-results/pte-chain-validation.json) |
| Lettura effettiva registri VT-d prima e dopo il test 4 KiB | Eseguita in sola lettura: DRHD fed91000 GSTS=47000000 stabile, TES=0, PMEN=0, EPM=PRS=0. QIES/IRES sono 1 ma non equivalgono a traduzione DMA attiva. Le quattro TCSS VTDBAR MCH+7888/7890/7898/78A0 sono zero/disabilitate. È evidenza hardware aggiuntiva rispetto al solo parametro intel_iommu=off. | prima *(artefatto locale non pubblicato)*, dopo *(artefatto locale non pubblicato)*, DMAR binaria *(artefatto locale non pubblicato)* |
| CPU scrive la stessa parola BAR1 dopo tutti i confronti P2P | Eseguito: due pattern distinti per GPU scritti dalla CPU, riletti dalla CPU e verificati con D2H del proprietario; tutti passano. Valore precedente ripristinato e verificato per entrambe. Sulla A2000 la parola è esattamente 0x4600600000, destinazione della scrittura peer fallita. Esclusa l’ipotesi di quella finestra universalmente non scrivibile; non dimostra quali TLP emetta la GPU. | [analisi](native-cpubar-rw-gpu-results/ANALISI.md), [verifica](native-cpubar-rw-gpu-results/verified-result.json), [log](native-cpubar-rw-gpu-results/result.log) |

Il confronto a cinque fasi degli attributi PCIe è stato successivamente eseguito, come documentato sotto. Il candidato RM `RMCaskPeerCoherent=1` (`driver-peer-coherent`) è stato successivamente compilato ed eseguito; il suo esito è documentato nell’appendice SYS_COH seguente. Le vecchie prove VM coherent/NoSnoop sono realmente eseguite e già elencate; non sostituiscono queste ripetizioni con sincronizzazione, allineamento e provenienza verificati. I difetti di cleanup IOVAS restano separati e non corretti nei moduli di questi confronti.

## Aggiornamento: attributi PCIe nelle stesse allocazioni

Il confronto nativo a cinque fasi è stato **realmente eseguito** mantenendo vive le medesime quattro allocazioni: baseline iniziale, NoSnoop/RelaxedOrdering disattivati sulla sola Ada, baseline ripristinata, entrambi gli attributi disattivati su entrambe le GPU, baseline finale ripristinata. Tutte le cinque fasi completano quattro confronti con tre errori: 15 fallimenti su 20, sempre le due letture e la scrittura Ada→A2000. Le sei scritture DeviceControl sono rilette e verificate; il programma conferma ripristino finale e conclusione del protocollo. I due bit sono modificati insieme (mask0x0810): non è una prova che li separa.

Il programma CUDA termina RC5, coerentemente con i dati falliti. Lo script esterno termina RC23 perché un suo controllo AWK non inizializzava esplicitamente due contatori: riproduzione CPU con lo stesso BusyBox e gli stessi log, originale RC1 e variante con soli contatori inizializzati RC0. **I log originali non sono stati corretti.** Il marker `PROBE_COMPLETED` manca e la lettura CCFG finale dello script non è stata eseguita; la conclusione si fonda sui risultati delle cinque fasi e sul ripristino DeviceControl verificati, senza attribuire successo allo script esterno.

- [Log originale](native-nosnoop-gpu-results/result.log)
- [Verifica indipendente](native-nosnoop-gpu-results/verified-result.json)
- [Riproduzione del falso negativo](native-nosnoop-gpu-results/busybox-gate-reproduction.json)

## Aggiornamento: mapping SYS_COH realmente eseguito

Il nativo SYS_COH completa quattro confronti, ancora con tre errori e la sola scrittura A2000→Ada corretta. Non è una mancata applicazione del parametro: tutte le quattro PTE hanno enum software4 e encoding hardware2, stessa parte indirizzo e stessi altri attributi della baseline, XOR2 esatto sulla prima parola raw. UVM rimane il medesimo binario2MiB. I controlli CPU non sono saltati: dopo la scrittura verso A2000 la CPU legge ancora zero, concorde con il D2H proprietario. Tutti i dieci controlli locali passano; i residui IOVAS iniziano270,88 ms dopo context_exit. Il programma e lo script restituiscono RC5 con PROBE_COMPLETED, e i CCFG previsti sono riletti anche dopo il test.

- [Analisi e limiti](native-coherent-postwrite-gpu-results/ANALISI.md)
- [Verifica17hash e risultati](native-coherent-postwrite-gpu-results/verified-result.json)
- [Confronto PTE con baseline](native-coherent-postwrite-gpu-results/coherent-chain-validation.json)
- [Log originale](native-coherent-postwrite-gpu-results/result.log)

## Aggiornamento: confronto reale SM e Copy Engine con CUPTI

Il nuovo nativo completa **12 confronti**: trasferimenti solo scrittura da 4 B, 64 KiB e 1 MiB, in entrambi i versi, con kernel SM e richiesta CUDA DtoD osservata da CUPTI. L’audit della traccia conferma sei attività di copia e sei kernel, senza record persi o errori di tracing. Per ogni taglia e motore, Ada→A2000 fallisce su tutte le parole confrontate; A2000→Ada passa. Sono dunque sei fallimenti e sei successi. Il cambio del motore non risolve la direzione difettosa. La traccia CUPTI non è una cattura TLP e non prova da sola l’assenza di un percorso interno alternativo del driver: `direct_route_proven=0` resta esplicito.

Sono vive quattro allocazioni da 8 MiB, due sorgenti accessibili soltanto dal rispettivo proprietario e due ricezioni condivise. Gli unici due mapping peer sono quelli delle ricezioni: Ada a 0x4000400000 e A2000 a 0x4600400000. Nonce, GPU VA, finestra BAR1, indirizzo DMA e prima PTE RM/UVM coincidono; pagine da 2 MiB allineate, quattro entrate per mapping, aperture3 e permessi di scrittura presenti. Viene loggata soltanto la prima PTE di ogni mapping, ma tutti i payload della prova ricadono entro quella prima pagina da 2 MiB. I 24 confronti locali d’inizializzazione e i 104 controlli di accesso passano.

Tutti i 150 snapshot PCI sono leggibili e non mostrano variazioni dei campi rilevati, neppure nuovi RMA. Questo distingue il comportamento della scrittura fallita dalle letture remote che provocavano RMA; non certifica l’assenza di rifiuti o perdite non segnalati. Le liberazioni seguono tutti i confronti: `data_done=13.837442182`, poi entrambe le finestre riportano `WINDOW_DESTROY_DONE`; i quattro residui IOVAS compaiono 369,011 ms dopo `context_exit_begin`, seguiti da otto assert. Nessun Xid. Il difetto di cleanup resta separato e non corretto.

I 17 file raccolti sono ricalcolati e concordi con gli hash; il programma e lo script terminano RC5 con `PROBE_COMPLETED`. D1=00008077 e D7:F0/F2=00009077 sono confermati prima del driver, dopo il driver e dopo la prova. Il pacchetto era stato verificato in streaming: sei payload richiesti, quattro librerie CUPTI ausiliarie e tutti i 50 input di compilazione. Nessuna modifica SYS_COH, UVM4KiB, DeviceControl o ricollocazione BAR è presente in questa immagine.

- [Audit CUPTI e dati](native-ce-gpu-results/cupti-independent-log-audit.json)
- [Audit indipendente di mapping, PCI, provenienza e cleanup](native-ce-gpu-results/independent-mapping-lifetime-review-storico.json)
- [Log originale](native-ce-gpu-results/result.log)
- Log kernel *(artefatto locale non pubblicato)*
- [Verifica dei payload effettivi nell’immagine](native-ce-probe/independent-package-review-storico.json)

### Nota operativa sulle VM, distinta dalle prove P2P

L’operatore riferisce che Windows `03-Windows_11` (UUIDc1343d2f-8b8a-c957-a51c-c397f4ac0034) è stata sospesa correttamente con stato salvato sul VDI39affde2… . Dopo il test SYS_COH il tentativo di ripresa è stato rifiutato per memoria insufficiente: Windows resta sospesa, non risulta riavviata e lo stato salvato è conservato. Docker usa26GiB fissi, Windows8GiB e dom0 4GiB; non è stata modificata la configurazione RAM. Windows si era avviata automaticamente al timestamp00:54 riportato dall’operatore, dopo l’arresto di Docker, non contemporaneamente a Docker. Questa nota registra il resoconto dell’operatore; non è una nuova interrogazione remota svolta dall’autore dello storico.

## Ripristino finale verificato — 21 ottobre 2026, 03:19 CEST

Dopo il confronto SM/CE, il ripristino del candidato firmware è stato **realmente completato**. La rilettura UEFI dei 30 settori, da 0x01B0B000 per 0x1E000 byte, coincide integralmente con l’originale: SHA256 `b81e705a87c89a668c4bbddd3538a82ccd5ebea4b156ce2d79762147310deba9`, zero byte differenti. Il dump del candidato precedente coincide con `c37f53ee…edf4`. Sono stati ricalcolati tutti i 28 hash della raccolta; flag RESTORED, stato e log del gate UEFI concordano. CCFG torna a D1=04008077 e D7:F0/F2=0E009077. La variabile SaSetup si trova fuori dallo span riscritto: la sua conservazione è dedotta dall’ambito della scrittura, non da una nuova lettura indipendente della variabile.

Alle **03:19:41 CEST** la pulizia registra la rimozione delle due voci temporanee 0002/0003 e delle sole directory CaskLogicTcssSyncTest/CaskLogicTcssNative. Prima della rimozione sono stati conservati integralmente i due alberi: 28 file firmware e 19 file nativi, **47 file verificati**, comprese immagini kernel e initrd. La copia locale è stata ricalcolata contro entrambi i manifest, inclusi struttura delle directory, dimensioni e hash. Il journal coincide con il rapporto di pulizia. Restano BootCurrent0000, BootOrder0000,0001 e nessun BootNext; i controlli dell’operatore attestano file EFI originali invariati.

Il rapporto successivo, rilevato fra le 03:20 e le 03:21 CEST, registra Docker avviata, entrambe le GPU visibili con driver595.99.02, servizi ventole/persistence/Docker attivi, training inattivo e disabilitato, nessun processo compute e nessun Xid nel controllo effettuato. Il modulo risolto su disco è `/lib/modules/7.0.0-38-generic/updates/dkms/nvidia.ko.zst`, SHA256 `0b3110fde7eb34d578ea50b7da21d2539b1ff228fd017efc03e71a6aeace008d`; srcversion su disco e caricata coincidono (`919309EF6954372EFADD77E`). **Quel solo srcversion non prova l’identità completa stock**, perché compare anche nel modulo dinamico sperimentale conservato. In questa verifica locale non è stata trovata una baseline autorevole precedente per l’hash del file compresso: l’identità stock va sostenuta da un’eventuale verifica separata, non dedotta da quel campo.

Windows rimane **sospesa**, con VDI dello stato `39affde2-d364-4e72-9d0e-cb422542db75` conservato. Il tentativo di ripresa con Docker attiva è stato rifiutato per RAM insufficiente; non viene descritto come avvio riuscito o perdita di dati. La configurazione rimane Docker26GiB e Windows8GiB. Queste sono osservazioni registrate dall’operatore e poi verificate localmente nei report, non un nuovo collaudo CUDA né un audit completo dei dati del server.

Il ripristino e la pulizia sono conclusi; **il problema P2P bidirezionale resta irrisolto**. Le prove fallite non vengono promosse a soluzione e non giustificano lasciare attive le modifiche firmware sperimentali.

- [Rilettura integrale e stato del ripristino](native-sync-restore-results/restore-verification.json)
- [Pulizia verificata e manifest completi](cleanup-sync-verified.json)
- Stato finale osservato del sistema *(artefatto locale non pubblicato)*
- [Audit indipendente locale di 28 hash e 47 file](final-sync-independent-review-storico.json)
- Backup completo degli artefatti *(artefatto locale non pubblicato)*
