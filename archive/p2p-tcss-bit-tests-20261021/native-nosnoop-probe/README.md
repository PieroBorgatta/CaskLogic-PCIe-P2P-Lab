> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Confronto controllato NoSnoop / Relaxed Ordering

Candidato locale, non eseguito sulle GPU durante la preparazione. Modifica esclusivamente i bit standard Device Control 11 e4 (`0x0810`) delle due GPU note, con scritture da16bit. Non modifica CCFG, ACS, BAR, registri Thunderbolt, firmware o contenuto dei dischi.

Il programma crea prima tutti e quattro gli handle/allocazioni/VMM della prova da4byte e conserva gli stessi indirizzi per cinque fasi:

1. `baseline_initial`: entrambi attributi originali attivi.
2. `ada_off`: NoSnoop e Relaxed Ordering disattivati solo sulla GPU Ada interna.
3. `baseline_restored`: ripristino verificato e ripetizione della baseline.
4. `both_off`: entrambi attributi disattivati sulle due GPU.
5. `baseline_final`: ripristino verificato e ripetizione finale.

Ogni fase esegue entrambe le letture e entrambe le scritture peer,20 confronti complessivi. Inizializzazione e azzeramento owner sono sincronizzati; anche la destinazione della lettura viene azzerata e sincronizzata prima del kernel. Restano i controlli CPU BAR1 in sola lettura, compresa la rilettura dopo peer-write prima di owner-D2H. Nessuna scrittura CPU alla BAR e nessun inoltro dei dati di una GPU all'altra via RAM. I pattern di inizializzazione e i risultati di verifica passano normalmente dalla CPU, come nella baseline.

## Guardie e ripristino

Il controller richiede CPUID906A3 senza flag hypervisor, assenza di `/sys/hypervisor/type`, host4641:8086 e UUID/BDF/ID delle due GPU conosciute. Percorre la capability list con limiti, controllo cicli/duplicati e tipo endpoint. Rifiuta baseline con attributi già disattivati o transazioni non-posted indicate pendenti. Salva il Device Control originale solo dopo inizializzazione CUDA e mapping completi, prima dei pattern.

Una scrittura usa due byte a `capability+8`, preservando tutti i bit fuori0x0810. Non scrive il Device Status adiacente, che contiene bit W1C. Dopo la modifica pretende readback identico; ai confini delle operazioni controlla entrambe le GPU, includendo i bit non modificati. Le letture del registro e i risultati sono identificati da fase/owner/operazione e timestamp monotonic.

Il ripristino cambia solamente0x0810 sul valore corrente e verifica i bit salvati; non sovrascrive variazioni degli altri campi. Un mismatch interrompe ulteriori confronti e tenta il ripristino. Prima di modificare i controlli si sincronizzano entrambe le GPU; il registro impone inoltre TransactionsPending=0. In ripristino il polling di quel bit è limitato a100ms e resta in sola lettura.

Tutti i percorsi C++ di errore dopo capture attraversano il tentativo esplicito di restore prima del cleanup. SIGTERM/SIGINT richiedono arresto al successivo confine controllato. Un kernel bloccato, SIGKILL o perdita del dispositivo possono impedire il ripristino dal processo: **il pacchetto RAM deve mantenere il watchdog di reboot e la verifica dello stato al rientro**. Timeout proposto programma60s, watchdog180s. Il candidato non installa o avvia questi meccanismi autonomamente.

## Risultati e limiti

`ATTR_PHASE_RESULT` è valido solo con `valid_protocol=1`; la fase completa4confronti e tutti i readback richiesti. `ATTR_PROGRAM_END protocol_complete=1 restored=1` è necessario per considerare completato il confronto. RC5 significa uno o più confronti P2P negativi in un protocollo completato, mentre RC12/13/14 segnalano abort/ripristino non verificato/errore cleanup. Le baseline intermedie controllano la modifica dovuta all'anticipazione delle allocazioni e alla ripetizione nella stessa sessione.

La persistenza dei bit di controllo non certifica direttamente gli attributi di ogni TLP. TransactionsPending riguarda le richieste non-posted e non certifica da solo l'assenza di tutte le scritture postate. Il CPU-postread può influire sul completamento delle scritture postate e rimane diagnostico. Le condizioni PCIe/AER sticky non vengono cancellate: il primo errore può restare presente nelle fasi successive.

`test_pci_attrs.cpp` esercita decoder e maschera in memoria ordinaria:262161casi ASan/UBSan, nessun dispositivo aperto. `main_syntax.cpp` deriva dall'include effettivo rimuovendo soltanto la sintassi dei due lanci CUDA e usando stub dichiarativi; verifica C++17, non sostituisce la compilazione NVCC o una prova GPU. Il sorgente originale postwrite e i suoi header rimangono invariati.

Le fonti e i precedenti tentativi sono in `../driver/USB4-ROUTING-ATTRIBUTES.md`.
