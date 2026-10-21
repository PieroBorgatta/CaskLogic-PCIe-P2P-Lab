> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Prossima indagine P2P: TCSS, transazioni e trasporto a scritture

Aggiornamento del 21 ottobre 2026. Ricerca locale/web; questo documento non certifica una soluzione e non sostituisce ESITO.md. La ripetizione nativa sincronizzata è terminata: ancora tre fallimenti su quattro, con quattro OWNER_CHECK validi e nuovo Received Master Abort sul richiedente e sul suo root port dopo ciascuna lettura. AER non cambia; non è corretto dire che tutti i registri PCIe restano puliti. L'analisi completa è in native-sync-gpu-results/ANALISI.md e verified-result.json. Nessuna operazione remota o scrittura hardware è stata eseguita da questa ricerca.

## Punto concreto

Il primo obiettivo resta ottenere anche la scrittura Ada interna → A2000 esterna. Se entrambe le scritture funzionano, un protocollo GPU→GPU basato su invio può trasportare dati nelle due direzioni senza usare la RAM come deposito intermedio, anche se le letture peer rimangono indisponibili. Al momento ciò è un candidato: negli esperimenti precedenti passa solo la scrittura A2000 → Ada.

Le due modifiche firmware già provate hanno realmente cambiato D7 CCFG a 00009077 e D1 CCFG a 00008077; non hanno corretto i tre confronti falliti neppure nel test sincronizzato. Il significato P2P dei bit D7 resta ipotetico: non è stato trovato un documento pubblico che lo attribuisca esattamente al dispositivo 8086:466e. Resta da verificare a runtime il mapping del verso di scrittura fallito: la ripetizione corretta esclude la lacuna di sincronizzazione come causa unica, non tutti i difetti possibili del driver.

## 1. Lacuna del test eliminata nella nuova ripetizione

Il test precedente inizializzava memoria sulla GPU proprietaria tramite H2D da std::vector pageable o cudaMemset, quindi cambiava dispositivo senza sincronizzare il proprietario. L'API non garantisce in entrambi i casi che il dato sia pronto quando la GPU diversa lo usa. Fonte primaria: [NVIDIA CUDA API synchronization behavior](https://docs.nvidia.com/cuda/cuda-runtime-api/api-sync-behavior.html).

La nuova variante aggiunge sincronizzazione del proprietario e verifica locale dei dati prima dell'operazione peer; mantiene tutte le liberazioni dopo i quattro confronti. La prova corretta ha riprodotto i tre fallimenti: la lacuna di sincronizzazione è quindi esclusa come loro spiegazione unica.

Gli assert IOVAS della prova nativa precedente compaiono dopo i confronti e dopo il marcatore di uscita dal contesto. Restano difetti da risolvere per stabilità del driver, ma non dimostrano un indirizzo errato durante i confronti. L'analisi statica non ha trovato un nuovo errore concreto nella composizione BAR1+offset della build utilizzata; non certifica i PTE effettivamente installati a runtime. Vedi driver/final-mapping-review.md.

## 2. Nuova evidenza NVIDIA sui processori client Intel

Nel [commento NVIDIA #1253 di Davide Rossetti](https://github.com/NVIDIA/open-gpu-kernel-modules/issues/1253#issuecomment-5035433619), marcato Member nel repository NVIDIA, si afferma che i processori client Intel sono noti per supportare solo scritture PCIe P2P e che il limite hardware non ha una soluzione semplice. La discussione concreta riguarda Arrow Lake/Z890, con una NIC che non riesce a leggere BAR1 ma riesce a scriverlo. Il [profilo ufficiale NVIDIA](https://developer.nvidia.com/blog/author/drossetti/) identifica Davide Rossetti come senior engineer; il profilo GitHub associa lo stesso nome a drossetti.

Questa fonte rende plausibile un limite alle letture tra root port, anche in assenza di errori AER. Non è una specifica Intel per Alder Lake-P TCSS e non prova che la scrittura Ada→A2000 sia impossibile. La conclusione più forte, contenuta nel commento successivo dell'autore della issue, non va confusa con la risposta NVIDIA.

## 3. NCCL può usare scritture, ma occorre controllare anche il protocollo

Fonti: [NVIDIA src/transport/p2p.cc](https://github.com/NVIDIA/nccl/blob/3e46c089f4ae4732722a419eb6096aead7e47a30/src/transport/p2p.cc), [prims_simple.h](https://github.com/NVIDIA/nccl/blob/3e46c089f4ae4732722a419eb6096aead7e47a30/src/device/prims_simple.h), [sendrecv_reg.cc](https://github.com/NVIDIA/nccl/blob/3e46c089f4ae4732722a419eb6096aead7e47a30/src/register/sendrecv_reg.cc). Copie e blob SHA sono in reference/next-investigation/source-manifest.json; controllata anche la versione v2.28.9-1.

NCCL_P2P_READ_ENABLE=0 seleziona il trasferimento del contenuto tramite scritture. Nel percorso Simple senza registrazione diretta degli user buffer:

- il mittente legge il credito head nella propria memoria;
- il ricevente scrive il nuovo head nella memoria del mittente;
- il ricevente legge tail nella propria memoria;
- il mittente scrive il contenuto nella VRAM ricevente, esegue fence_acq_rel_sys e scrive tail remoto.

Il polling dei crediti è locale; i dati e gli aggiornamenti di controllo attraversano il collegamento con scritture. Questo rende una strada write-only concreta nel codice, subordinata alla correttezza delle scritture nelle due direzioni e della sincronizzazione di sistema.

Un dettaglio impedisce di considerare sufficiente una sola variabile: nel ramo Direct && ipcReg il ricevente legge remotamente ptrExchange per aspettare che lo slot sia nullo. Nella versione master esaminata è prims_simple.h:848; il puntatore remoto è assegnato in p2p.cc:605. P2P_DIRECT_DISABLE=1 cambia la modalità di importazione della memoria nello stesso processo ma non elimina da solo tutti i flag P2P_WRITE/registrazione. Quindi non basta a dimostrare assenza di peer read.

Configurazione candidata da collaudare soltanto dopo il successo delle due scritture elementari: Simple e Ring; P2P_READ_ENABLE=0; LOCAL_REGISTER=0; GRAPH_REGISTER=0; nessuna registrazione diretta user buffer né uso del percorso CE/memcpy. Va verificata sulla versione NCCL effettivamente caricata. Il passaggio tramite i buffer interni di NCCL rimane interamente in VRAM, non è staging in RAM. Il sorgente consente questa analisi del protocollo; non è una cattura dei TLP effettivi emessi da una GPU.

La selezione del trasporto va comunque provata dai log e dal confronto dei dati: disabilitare SHM non vieta un fallback di rete. La capacità CUDA/NVML forzata a OK non dimostra il funzionamento del canale.

## 4. Snapshot PCIe: cosa possono chiarire

Il file native-sync-probe/pcie_diag.h legge soltanto config sysfs dei sei dispositivi del percorso: root D1, root D7, due bridge ASM e due GPU. SHA256: 4820c6c0f296c9af7bb75403885f860a3f8d1837d0aed1e625143258001358ae. Revisione indipendente completata da audit_firmware. Nessuna scrittura, reset o pulizia di bit W1C.

Raccoglie monotonic timestamp, PCI status, secondary status, PCIe Device Status, AER status/mask/severity, Header Log e Root Error Status/Source dove applicabili. Baseline e snapshot prima/dopo ciascuna operazione possono distinguere:

| Riscontro nuovo | Ipotesi rafforzata |
| --- | --- |
| Unsupported Request, UES bit20 | destinazione/decode o transazione non supportata |
| Completer Abort, bit15 | risposta esplicita di rifiuto |
| Completion Timeout, bit14 | lettura senza completamento ricevuto |
| Unexpected Completion, bit16 | problema di completamento/tag/routing |
| ACS Violation, bit21 | rifiuto nel controllo accessi |
| Header Log nuovo con RID/indirizzo | possibilità di correlare richiesta e finestra BAR prevista |

Sono indicatori, non localizzazioni automatiche della causa. I bit già presenti nella baseline sono sticky e non attribuibili al nuovo tentativo. Il kernel potrebbe registrare/pulire un errore prima dello snapshot. AER pulito non prova che una lettura peer sia supportata.

## 5. Decode D7 realmente documentato: controllare prima di ipotizzare un'altra patch

Fonte primaria esatta: [Intel 710723-003, datasheet Volume 2](https://cdrdv2-public.intel.com/710723/710723-003.pdf), capitolo 12.5 Thunderbolt PCI Express Controller Registers D7:F0-3, pagine 959–1063. Testo locale: reference/next-investigation/intel-710723-003.txt.

Le finestre standard a 20h (memory), 24h (prefetchable base/limit), 28h e 2Ch (parti alte), più MSE nel comando a 04h, delimitano il percorso downstream. Vanno confrontate su D7 e su entrambi i bridge ASM con l'indirizzo fisico BAR1 realmente mappato per A2000, non con un indirizzo preso da una precedente VM.

La stessa sezione documenta un decode opzionale FPB:
- BA4 bit2: supporto del decode memoria alta;
- BB4 bit0: abilitazione;
- BB4[7:4]: granularità;
- BB4[31:28] e BB8: base del vettore memoria alta;
- BBC/BC0: accesso ai vettori.

Questo non è un interruttore P2P. Prima di qualsiasi ipotesi sul blocco bisogna leggere capability ed enable; campi di un meccanismo non supportato sono indefiniti e non vanno attivati. Non è stata identificata una modifica FPB risolutiva né una sua configurazione errata. Audit_firmware verifica in parallelo se il FSP installato lo programma.

Il rilievo successivo `decode-snapshot-20261021/decode-analysis.json`, acquisito in Xen dom0, ha chiarito questi punti: D7 e i due bridge ASM hanno MSE attivo e finestra prefetchable a 64 bit 4600000000–4801FFFFFF; i registri 24/28/2C sono 01F10001/00000046/00000048. D7 BA4 vale 00010207, ma BA8, BB0 e BB4 sono zero: i tre decode FPB sono disabilitati. Anche D7F2 ha gli enable a zero. Il solo supporto FPB non dimostra né un filtro attivo né un permesso P2P. Non emerge da questo rilievo una finestra standard errata. È una misura dom0, con BAR1 A2000 da 8 GiB: il nativo ricrea il tunnel con BAR1 da 256 MiB, quindi le finestre vanno ricontrollate nello stesso avvio delle PTE; non vanno copiate tra ambienti.

Le definizioni pubbliche CCFG/DMI o D6 non vanno trasferite a D7 o D1 come se fossero una prova. Il limite di ampiezza degli indirizzi PCIe citato nel Volume1 non spiega da solo i BAR nativi osservati, posti a circa 256 e 280 GiB e quindi ben sotto il limite pubblicato.

## 6. Thunderbolt e ASM2464: cosa è e cosa non è stato trovato

Nel [driver Linux thunderbolt/pci.c](https://github.com/torvalds/linux/blob/master/drivers/thunderbolt/pci.c) Alder Lake usa icl_nhi_ops. Le scritture VS_CAP per force-power/mailbox gestiscono alimentazione e firmware readiness, non documentano un filtro peer. Nel connection manager Linux i tunnel PCIe sono costruiti in entrambe le direzioni; l'abilitazione dell'adattatore PCIe è distinta dalle singole classi di richiesta PCIe. Finora nessun flag peer specifico e verificabile per 466e è stato individuato in questi sorgenti.

[ASMedia](https://www.asmedia.com.tw/news-main/e46Zz4cRqeTi7PQ3.html) descrive ASM2464PD con switch PCIe Gen4 integrato. Non pubblica in questa fonte una guida dei registri per routing peer.

Esiste un lavoro pubblico degli sviluppatori [tinygrad/asm2464pd-firmware](https://github.com/tinygrad/asm2464pd-firmware), con descrizioni di registri interni 8051/XDATA e una pipeline USB3 per inviare TLP. È reverse engineering del firmware, non documentazione ASMedia e non una correzione dimostrata dei tunnel Thunderbolt. Gli indirizzi B2xx/B4xx descritti lì non sono offset PCI config da scrivere su D7 o sul bridge. Non è giustificato caricare un firmware generico del progetto sul dock.

Linux espone, se presenti, registri e contatori del router/adattatore sotto debugfs thunderbolt. Il solo show dei contatori usa tb_port_read(TB_CFG_COUNTERS); il write azzera i contatori. Una futura acquisizione deve limitarsi alle letture. Occorre prima identificare il router reale e i contatori disponibili; non è stato dimostrato che distinguano specificamente Memory Read da Memory Write per questo dock.

## Sequenza utile dopo il test sincronizzato

1. Il confronto numerico e PCIe del test sincronizzato è concluso: tre fallimenti, con nuovo RMA dopo ciascuna lettura. Il primo read fallito A2000→Ada e il successivo write riuscito A2000→Ada usano la stessa allocazione/mapping vivo, senza rimappatura: un semplice indirizzo BAR1 sbagliato non spiega facilmente quella coppia. L'altro mapping resta da verificare.
2. Confrontare la PTE e il DMA address costruiti per la GPU Ada con BAR1 A2000 e finestre downstream D7/04/05. La patch di logging è stata revisionata indipendentemente in `driver-instrumented/independent-logging-review.json`; registra valori costruiti e sottoposti a UVM, non legge le page table hardware. Nessun successo di compilazione o prova è dedotto dalla sola revisione statica.
3. Se indirizzo e decode coincidono, verificare dalla CPU gli stessi quattro byte allocati attraverso quella precisa finestra BAR1, mantenendo viva l'allocazione. La proposta è in `driver/CPU-BAR1-CONTROL-PROPOSAL.md`: due valori distinti scritti dal proprietario e letti dalla CPU separano il mapping BAR1→VRAM dal percorso cross-root. Un successivo controllo di scrittura CPU deve rispettare l'ordinamento CUDA e non basta, da solo, a localizzare un eventuale errore di cache.
4. Indagare il controller del dock soltanto con identità/versione firmware reale e sorgente coerente con quel firmware. Nessun nuovo controllo Thunderbolt risolutivo è documentato dalla ricerca attuale.

Un caso pubblico diverso, [Intel compute-runtime #935](https://github.com/intel/compute-runtime/issues/935#issuecomment-5326802366), documenta una discussione di corruzione su Rocket Lake/Arc quando il percorso viene forzato attraverso un host bridge non supportato. Non fornisce un workaround TCSS né una specifica Alder Lake-P: conferma soltanto perché l'override della capability non può sostituire il confronto dei dati. Non viene usato per dichiarare impossibile la scrittura verso A2000.

Non risultano ancora dimostrati né il successo del P2P bidirezionale né l'impossibilità definitiva sulla topologia vincolata.

