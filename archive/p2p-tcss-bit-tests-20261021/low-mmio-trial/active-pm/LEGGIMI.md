> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Preparazione runtime PM per la prova MMIO bassa

Questa variante risolve il blocco del preflight dovuto alle due funzioni audio senza cambiare gli indirizzi obiettivo o l'algoritmo di riallocazione. La baseline `../cask_low_mmio.c` e la variante `../diagnostic/` restano intatte. La capacità del percorso PCIe di inoltrare le scritture P2P sotto 4 GiB rimane da misurare.

Nel boot `native-cpubar-gpu-results/kernel.log`, righe 1073–1079, le funzioni `06:00.1` (10de:228e) e `01:00.1` (10de:22be) sono senza driver, con `current_state=PCI_D0`, `runtime_status=RPM_SUSPENDED`, `disable_depth=0`, `runtime_error=0`. La lettura separata PMCSR è 0008, quindi D0. Non si tratta di uno stato PCI UNKNOWN o D3.

È un caso previsto da Linux: [pci_pm_runtime_suspend](https://github.com/torvalds/linux/blob/v7.0/drivers/pci/pci-driver.c#L1311) lascia in D0 un dispositivo senza driver, salvandone la configurazione. Il corrispondente resume ripristina la configurazione prima di tornare; può pertanto effettuare scritture PCI anche quando l'hardware era già D0. I sorgenti primari verificati e i relativi SHA sono in `../diagnostic/reference/`.

Il parametro `activate_audio` è disabilitato per default. Con opt-in esplicito, la nuova preparazione:

1. Verifica CPU nativa 906a3 e intervallo richiesto prima di qualsiasi callback.
2. Acquisisce una reference `get_noresume` su tutti i sette dispositivi; nessun `device_lock` è ancora detenuto.
3. Verifica identità PCI live, capability PM e PMCSR D0, stato cache D0, assenza di VF/driver endpoint, assenza di errori o transizioni PM. Fotografa i primi 64 byte config e tutte le risorse kernel dei sette dispositivi.
4. Invoca `pm_runtime_resume_and_get` solo sui due audio attesi se sospesi, PM abilitato e con la sola reference già acquisita dal modulo. Dopo un successo, `put_noidle` scambia la reference preliminare con quella attiva; dopo un errore non decrementa una reference inesistente. Nessuna assegnazione a `current_state`, `runtime_status` o PMCSR.
5. Confronta configurazione e risorse dopo ogni callback. Esclude dal confronto soltanto PCI STATUS del primo dword COMMAND/STATUS; il SECONDARY STATUS dei bridge rimane conservativamente incluso, quindi un evento può fare rifiutare la prova.
6. Acquisisce tutti i `device_lock`, ricontrolla quanto fotografato e poi esegue le guardie precedenti, inalterate. La verifica live di identità e D0 viene ripetuta prima della disabilitazione COMMAND, dopo la riallocazione e dentro `restore_commands`, anche nel rollback.

Sul commit o su un esito fatale il modulo rimane caricato e mantiene una reference PM su ciascun dispositivo fino al reboot. La prevenzione della sospensione usa questi riferimenti; non imposta `pm_runtime_disable`. Sulle uscite senza commit rilascia le reference con `put_noidle`: non forza un nuovo suspend e può lasciare audio runtime-active dopo il preflight. Se un callback fallisce o cambia la fotografia config/risorse, la riallocazione non inizia e il wrapper deve interrompere la prova. Un callback PM già eseguito non è annullato artificialmente.

## Build e collaudo locale

I tre input necessari alla build sono `cask_low_mmio.c`, `audio_pm.inc` e `Makefile`. Compilazione CPU sul kernel effettivo:

```sh
make -C /lib/modules/7.0.0-38-generic/build M="$PWD" W=1 KCFLAGS=-Werror modules
```

Il coordinatore ha riportato build PASS con tali opzioni, modulo SHA256 `2f643a3bffc6f8fe8a7a8c07da4d6ac66145d59eb99b8260f8f87951a0ee4b8d`. Questo agente non ha caricato il modulo.

`python3 run_offline_checks.py` compila la vera `audio_pm.inc` con API simulate ed esegue 163 scenari con Clang, `-Wall -Wextra -Werror`, AddressSanitizer e UndefinedBehaviorSanitizer. Verifica inoltre 17 invarianti di integrazione, inclusa l'identità delle funzioni di riallocazione e rollback rispetto alla variante diagnostica. Esito PASS in `offline-validation.json`. Sono verifiche CPU: non dimostrano l'esito dei callback del kernel reale o della riallocazione hardware.

## Contratto con il wrapper nativo

Il wrapper rimane l'unico responsabile del boot RAM isolato, di nessuna VM attiva, delle funzioni GPU/audio senza driver e dei controlli CCFG del firmware combinato. Parametri previsti per la riallocazione: `execute=1 activate_audio=1 base=0x80000000`. Un ritorno positivo di `insmod` da solo non autorizza il caricamento NVIDIA: esigere `/sys/module/cask_low_mmio/parameters/result` esattamente `relocated_verified_reboot_to_restore` e il verificatore esterno sia prima sia dopo NVIDIA.

Per il preflight senza riallocazione, `execute=0 activate_audio=1` ha come token `preflight_ok_pm_ready`. Il token rende esplicito che i callback PM possono avere ripristinato configurazione. `FATAL_REBOOT_REQUIRED` richiede il percorso di riavvio previsto; non caricare le GPU e non forzare la rimozione del modulo. `failed_original_restored` certifica soltanto il rollback della transazione, non autorizza la prova GPU.

L'indirizzo BAR1 resta 80000000–8fffffff, BAR3 90000000–91ffffff, con finestre dei tre bridge 80000000–91ffffff. Nessuna modifica firmware o disco è parte del modulo. Il reboot ripristina l'allocazione BAR del boot; il ripristino delle precedenti patch firmware FSP resta un'operazione separata del coordinatore.
