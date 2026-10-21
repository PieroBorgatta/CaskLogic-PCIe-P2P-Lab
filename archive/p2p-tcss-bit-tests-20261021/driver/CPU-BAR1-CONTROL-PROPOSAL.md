> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Controllo CPU della stessa finestra BAR1 usata dal peer

Proposta locale, 21 ottobre 2026. Nessun codice del probe modificato, nessun accesso hardware eseguito. Obiettivo: verificare che la finestra BAR1 dinamica traduca veramente verso i quattro byte CUDA del test, prima di attribuire una scrittura persa all'instradamento Ada→TCSS→A2000.

## Perché serve e che cosa non prova

Il controllo locale CUDA verifica la VRAM tramite il mapping del proprietario. Non attraversa necessariamente la finestra BAR1 dinamica creata per l'altra GPU. Una lettura CPU dello stesso byte fisico usato dal peer verifica un percorso ulteriore: CPU→root port/tunnel→BAR1→VRAM. Se questa lettura segue due cambiamenti distinti applicati dal proprietario, la corrispondenza fra offset BAR e allocazione è verificata sul dato, non soltanto inferita dalle PTE costruite dal driver.

Il controllo non dimostra che il root complex instradi una richiesta proveniente da un'altra GPU nello stesso modo della CPU. Non certifica la PTE hardware della GPU richiedente. Un risultato positivo renderebbe però molto meno plausibile un'apertura BAR1 che punta alla pagina VRAM sbagliata.

Non richiede preliminarmente una BAR sotto 4 GiB: un processo Linux x86_64 può mappare una risorsa PCI a 64 bit. Il caso BAR basso può essere una prova separata del percorso peer, non un requisito del controllo CPU.

## Correlazione obbligatoria, senza cercare valori nella memoria

Il probe deve stampare un identificatore locale univoco dell'allocazione, BDF/UUID del proprietario, GPU VA, dimensione effettiva e dimensione utile di quattro byte. Il valore CUmemGenericAllocationHandle non è da trattare come un handle RM.

La catena da risolvere nello stesso processo e nello stesso avvio è:

1. GPU VA esatta del probe → `UVM_ALLOCATION.gpu_va`, GPU richiedente e `rm_mem`.
2. `rm_mem` → `RM_REQUEST.mem`, GPU sorgente/owner, descriptor e offset.
3. Descriptor, owner e mapping → `WINDOW_CREATE.id`, `bar1_off`, `window_phys`, dimensione e DMA.
4. `RM_PTE`/`UVM_PTE` devono confermare offset iniziale zero, stessa PTE e completamento del mapping senza errori. La variante attuale usa cuMemMap con offset zero: rifiutare un offset diverso anziché improvvisare il calcolo.
5. `window_phys` deve uguagliare la base CPU di BAR1 letta in `resource` più `bar1_off`; BDF, vendor/device e intervallo della risorsa devono coincidere. Non usare l'indirizzo DMA al posto dell'indirizzo CPU fisico quando fossero differenti.

La selezione deve essere univoca. Descriptor stampati come `(ptrval)`, log persi, due candidati o un evento `WINDOW_DESTROY` annullano il controllo. La vicinanza delle righe e un indirizzo copiato da un boot precedente non sono criteri accettabili. Non scansire BAR1 alla ricerca del pattern.

L'allocazione, l'accesso peer e il contesto restano vivi per tutta la prova. Il medesimo thread controlla il ciclo di vita; nessun free/remap/riavvio o carico concorrente durante la finestra CPU. Munmap/close precedono la normale deallocazione GPU.

## Prima prova: soltanto letture CPU

Usare `/sys/bus/pci/devices/<BDF-owner>/resource1`, senza suffisso `_wc`. La documentazione [Linux PCI sysfs](https://docs.kernel.org/PCI/sysfs-pci.html) distingue le risorse mappabili, quelle write-combining e i normali file di configurazione. Verificare ogni errore di open/mmap; non aggirare un rifiuto con `/dev/mem` o scollegando il driver.

Mappare in sola lettura una pagina con offset relativo `align_down(bar1_off, page_size)`. Verificare overflow, allineamento a quattro byte, appartenenza dei quattro byte all'allocazione e dell'intera pagina alla risorsa. L'arrotondamento della mappatura non autorizza a dereferenziare gli altri byte della pagina. Eseguire solo un load volatile uint32_t all'offset autorizzato, senza memcpy dell'intera pagina o prefetch software.

Sequenza proposta:

1. Proprietario scrive il primo pattern, sincronizza e lo verifica con copia locale D2H.
2. CPU legge esattamente la word della finestra BAR1 e registra il risultato.
3. Proprietario sostituisce il valore con un secondo pattern distinto, sincronizza e lo verifica localmente.
4. CPU rilegge esattamente lo stesso offset già risolto; deve vedere il secondo pattern.
5. Ripristinare il pattern del probe, sincronizzare e verificare prima di qualsiasi confronto peer successivo.

Ogni accesso è delimitato da marcatori temporali e snapshot PCIe in sola lettura. Errori di mapping o SIGBUS producono un risultato diagnostico fallito, senza tentare altri indirizzi. Il test in volo resta invariato: questa è una successiva variante isolata.

## Seconda prova opzionale: una scrittura CPU controllata

Solo dopo le due letture corrette e una correlazione unica: mappare la medesima pagina non-WC in lettura/scrittura, salvare il contenuto valido della word, scrivere un nuovo pattern in quei quattro byte, eseguire il readback MMIO sulla medesima word e quindi avviare dal thread CPU una nuova operazione CUDA sul proprietario per verificarlo. Un semplice fence CPU non sostituisce il completamento della scrittura PCIe; il readback e la successiva API CUDA hanno scopi distinti. Nessun kernel deve essere concorrente alla scrittura CPU.

La guida [NVIDIA GPUDirect RDMA, sincronizzazione](https://docs.nvidia.com/cuda/gpudirect-rdma/index.html#synchronization-and-memory-ordering) richiede consistenza fra registrazione BAR e operazioni CUDA e spiega che submission/sincronizzazione avviate dalla CPU ordinano le scritture esterne prima dell'uso GPU. Indica SYNC_MEMOPS per le allocazioni compatibili. Questa prova usa VMM e mapping dinamico modificato: non va assunto che cuPointerSetAttribute sia supportato né che il solo mmap sysfs realizzi la registrazione GPUDirect ufficiale. Registrare il risultato dell'eventuale query e non ignorare un errore. Un write CPU seguito da readback CPU corretto ma lettura CUDA vecchia lascia aperta la causa di ordinamento/cache; non autorizza a dichiarare il BAR errato.

Ripristinare e verificare i quattro byte iniziali prima di proseguire. Nessun accesso a BAR0, PCI config, registri di comando, finestre bridge o firmware fa parte del controllo.

## Lettura degli esiti

| Esito | Conclusione consentita |
| --- | --- |
| CPU segue entrambi i pattern del proprietario | Finestra BAR1→word VRAM corretta per quel mapping vivo e percorso CPU. |
| CPU legge FFFFFFFF e cresce PCI status/errore | Accesso CPU a quella finestra fallito; non isola da solo driver, decode o GPU. |
| CPU vede valori fissi/diversi senza errori | Mapping o visibilità da indagare; nessuna conclusione automatica sul cross-root. |
| CPU write/readback e successivo controllo CUDA passano | Anche il percorso CPU di scrittura verso quella word è valido. |
| CPU controlli passano, peer write resta zero e PTE coincide | Il percorso della GPU richiedente diventa il sospetto principale; manca ancora una cattura TLP o readback della PTE hardware. |

L'eventuale lettura/inizializzazione CPU è strumentazione diagnostica di quattro byte. Non è un trasporto con staging in RAM e non può essere presentata come soluzione P2P.
