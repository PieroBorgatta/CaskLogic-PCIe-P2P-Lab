> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Criteri di interpretazione, definiti prima dei risultati

NVML restituisce per ciascuna GPU una misura PCIe in KB/s su un intervallo di 20 ms. Non fornisce in questa API un indirizzo, un Requester ID, il tipo di TLP o un collegamento al singolo buffer. La documentazione specifica anche i return code non supportato, GPU persa ed errore: nessuno di questi può essere interpretato come traffico zero. [NVIDIA, Device Queries](https://docs.nvidia.com/deploy/nvml-api/latest/api/group__nvmlDeviceQueries.html).

La tabella seguente è un’interpretazione diagnostica proposta, non una proprietà garantita dall’API. “Aumenta” deve riferirsi a una differenza persistente rispetto al baseline quieto della stessa fase e dello stesso contatore, con campioni validi sufficienti; riportare comunque tutti i numeri senza una soglia inventata a posteriori. Il verso A2000→Ada con confronto dati valido è un controllo utile per verificare che la misura rilevi l’attività attesa su questa configurazione.

| PUSH fallito | Osservazione sostenibile | Cosa non dimostra |
|---|---|---|
| TX della sorgente e RX della destinazione aumentano | Entrambi i contatori registrano attività PCIe durante il lavoro, mentre il contenuto finale resta errato. | Che i medesimi byte attraversino i due punti, raggiungano il BAR1 giusto o vengano accettati come scritture corrette. |
| TX della sorgente aumenta, RX destinazione resta al baseline | È osservata attività trasmessa dalla sorgente senza aumento corrispondente nel contatore ricevente della destinazione. È compatibile con una perdita/rifiuto prima di quel punto, ma richiede conferma indipendente. | Quale root port o componente blocchi il payload; che tutto il TX sia payload; che il contatore RX veda ogni tipo di transazione pertinente. |
| Nessuno dei due aumenta, controllo inverso positivo | Non si rileva traffico aggiuntivo nei contatori selezionati durante il verso fallito, con sensibilità verificata almeno nel controllo inverso. | Che il kernel non abbia emesso richieste, che la MMU le abbia bloccate o che il fabric non le abbia già scartate prima del punto contato. |
| RX destinazione aumenta senza TX sorgente corrispondente | Serve controllare i quattro contatori, la temporizzazione, la baseline e l’attività di controllo: la coppia attesa non basta a spiegare il dato. | Una nuova via di trasferimento o lo staging in RAM. |

Riportare per ciascuno dei quattro canali baseline e finestra attiva: numero di campioni, minimo, massimo e media; conservare i timestamp grezzi. Le chiamate sono seriali: non sottrarre un singolo TX da un RX come se fossero simultanei. Il filtro esclude i primi 40 ms e le letture a cavallo dei confini; non rende la misura atomica.

La quantità `submitted_payload_bytes` è lavoro richiesto: non è una misura dei byte arrivati. Il programma riscrive lo stesso MiB più volte; il confronto verifica il contenuto finale, non tutte le ripetizioni. Anche una coppia TX/RX di valore simile resta aggregata e non prova P2P diretto o assenza di RAM intermedia. Questa variante richiede CUDA COPY ma non osserva CE con CUPTI; non trasferire automaticamente a essa la certificazione CE del programma precedente.

Il sampler e le richieste GPU possono generare traffico di controllo. La prova isola temporalmente H2D/D2H e diagnostica PCI dal periodo attivo, ma non può eliminare tramite log software ogni altra transazione del driver. `NVML_ERROR_NOT_SUPPORTED`, finestra troppo breve o cardinalità insufficiente rendono la misura non qualificata; l’eventuale confronto dati resta un fatto distinto.
