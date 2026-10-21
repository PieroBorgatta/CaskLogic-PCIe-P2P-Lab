> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Confronto nativo con BAR1 e BAR3 A2000 sotto 4 GB

Stato: **candidato locale, non compilato e non eseguito**. Revisione statica indipendente richiesta. Nessuna nuova patch BIOS e nessun accesso remoto da questo agente.

## Ipotesi e limite

Il confronto cerca una dipendenza della scrittura Ada→A2000 dall'indirizzo fisico alto. Non è stato dimostrato un filtro peer a 32 bit. Le finestre standard D7 supportano 64 bit e sono attualmente coerenti. La prova sincronizzata elimina la race di inizializzazione ma lascia una sola scrittura funzionante; le due letture provocano RMA nelle coppie GPU/root port. Questo non dimostra che lo spostamento della BAR risolverà la scrittura rimanente.

Lo snapshot dom0 `../decode-snapshot-20261021/decode-analysis.json` mostra spazio non occupato `0x6EB01000–0xBFFFFFFF`, considerando iomem, tutte le risorse PCI e firmware_memmap. Nello stesso snapshot BAR1 A2000 è ancora 8 GiB. Negli avvii nativi, dopo ricreazione del tunnel, BAR1 è 256 MiB e BAR3 32 MiB. **Solo quest'ultima configurazione è accettata dal candidato.**

Layout proposto, da riservare nuovamente nel kernel nativo:

| Risorsa | Nuovo intervallo |
|---|---|
| A2000 BAR1, 256 MiB | `0x80000000–0x8FFFFFFF` |
| A2000 BAR3, 32 MiB | `0x90000000–0x91FFFFFF` |
| Prefetch D7:F0, ASM 04:00.0 e 05:00.0 | `0x80000000–0x91FFFFFF` |

L'intervallo completo di 288 MiB è all'interno della finestra root MMIO bassa osservata `0x50400000–0xBFFFFFFF`. Non attraversa BAR0/nonprefetch. Il modulo rifiuta qualunque occupazione rilevata dal modello PCI e dalla prenotazione atomica nel resource tree del kernel. Il valore non viene dedotto come libero dal solo snapshot dom0.

## Alternativa standard valutata

`resourceN_resize` di Linux gestisce la dimensione ReBAR; non imposta una base fisica. `pci=resource_alignment=` impone un allineamento e può causare riassegnazione, ma non specifica un limite massimo d'indirizzo per la sola A2000. `pci=realloc` rialloca finestre insufficienti. Nessuna di queste interfacce documentate realizza da sola il confronto mirato richiesto, e una riallocazione generale aggiungerebbe altre variabili.

Fonti: [ABI PCI Linux v7.0](https://raw.githubusercontent.com/torvalds/linux/v7.0/Documentation/ABI/testing/sysfs-bus-pci), [parametri kernel Linux v7.0](https://raw.githubusercontent.com/torvalds/linux/v7.0/Documentation/admin-guide/kernel-parameters.txt).

## Candidato `cask_low_mmio.c`

Il codice usa le API PCI di configurazione del kernel e le API esportate di gestione delle risorse; evita di modificare soltanto i registri lasciando Linux con indirizzi vecchi. `pci_update_resource` e `pci_setup_bridge` non sono assunti esportati. Il modulo effettua gli aggiornamenti standard dei registri con `pci_write_config_*`, controlla ogni rilettura e aggiorna anche le sole copie `saved_config_space` corrispondenti. API/export sono stati confrontati con gli header e `Module.symvers` effettivi del kernel `7.0.0-38-generic` forniti dal coordinatore in `../low-mmio-kernel-headers/`.

In modalità predefinita `execute=false` controlla e riserva/rilascia temporaneamente soltanto risorse software; non scrive configurazione PCI. Con `execute=true`:

1. Richiede CPU nativa CPUID `906A3`, hypervisor assente, i sette ID attesi e stato PCI D0. Tutte le funzioni di entrambe le GPU devono essere prive di driver. Acquisisce il lock di rescan/remove e i device lock. Riferimenti runtime-PM senza resume impediscono nuove sospensioni; una transizione già in corso causa rifiuto. Non viene risvegliato un dispositivo per superare il gate.
2. Conferma topologia esatta, nessun figlio aggiuntivo, BAR1 da 256 MiB, BAR3 da 32 MiB, finestre a 64 bit e corrispondenza tra indirizzi hardware e risorse Linux. Rifiuta risorse fisse, non assegnate, occupate e traduzioni host/bus non identity.
3. Prenota l'intervallo basso e mantiene riservata la vecchia finestra durante tutta la fase che può richiedere rollback. Salva e stampa i registri originali prima delle scritture.
4. Disabilita bus mastering nei sette dispositivi, disabilita MSE lungo il solo percorso esterno e attende l'assenza di transazioni pending. I valori originali COMMAND sono conservati.
5. Sgancia le cinque risorse dalla foglia alla radice, ricostruisce i parent nella nuova finestra e aggiorna BAR1, BAR3 e tre finestre prefetch. Le risorse nonprefetch restano ai loro indirizzi.
6. Verifica configurazione e parent delle risorse. Soltanto dopo ripristina i COMMAND originali. Il risultato richiesto è esattamente `relocated_verified_reboot_to_restore`.
7. In caso di errore tenta ripristino completo di risorse, registri e COMMAND. Se non può verificarlo, mantiene il modulo e le eventuali risorse statiche in memoria, lascia i dispositivi senza mastering/decode e pubblica `FATAL_REBOOT_REQUIRED`: il programma esterno deve fermarsi senza caricare NVIDIA e riavviare.

Dopo un commit riuscito il modulo e i riferimenti runtime-PM vengono mantenuti fino al riavvio. Il ritorno alla configurazione BAR ordinaria avviene col reboot; non esiste un comando di unload che sposti risorse mentre un driver GPU le usa. Questo modulo non ripristina il BIOS: i due byte FSP già applicati sono gestiti dal pacchetto di ripristino separato del coordinatore.

## Controlli esterni necessari nello stesso avvio nativo

Il programma di avvio deve mantenere le VM spente, autorizzare il tunnel e attendere la topologia prevista prima del preflight. Deve acquisire iomem, risorse di tutti i dispositivi, configurazioni e BAR prima e dopo; confermare il baseline CCFG combinato `D1=00008077`, `D7:F0/F2=00009077`; non caricare driver GPU prima del risultato esatto del modulo.

La compilazione contro gli header effettivi e una revisione del binario restano da eseguire. Prima del carico NVIDIA vanno riletti anche da userspace i due BAR e le tre finestre, confrontandoli alle risorse Linux. Dopo il carico, verificare che il driver non abbia riallocato o ingrandito BAR1; soltanto allora usare la stessa sonda sincronizzata. Gli indirizzi delle PTE raccolti dalla diagnostica driver daranno la conferma del target effettivo.

## Fonti del protocollo delle risorse

Le copie locali `reference/resource.c`, `setup-res.c`, `setup-bus.c` provengono dal tag [Linux v7.0](https://github.com/torvalds/linux/tree/v7.0). `request_resource` esclude sovrapposizioni, `insert_resource` permette di mantenere una guardia contenente la vecchia finestra, `remove_resource` promuove i figli al parent originale. Il codice candidato usa queste operazioni per preservare gli oggetti risorsa originali del `pci_dev`, ai quali i bus subordinati continuano a fare riferimento.

Rischio pratico residuo: un errore di configurazione PCI, perdita del tunnel o comportamento del driver potrebbe richiedere il riavvio dell'avvio RAM. La verifica statica non prova il funzionamento hardware o la soluzione P2P.
