> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Stato PCI sconosciuto e stato hardware

Analisi statica; nessuna modifica del modulo o operazione hardware.

`PCI_UNKNOWN` vale 5 nei kernel header effettivi. Il core PCI assegna questo
stato durante la scansione e può riassegnarlo durante la rimozione di un
driver anche quando il dispositivo risulta ancora D0. Quindi UNKNOWN non
dimostra D3: [probe.c](https://raw.githubusercontent.com/torvalds/linux/v7.0/drivers/pci/probe.c)
e [pci-driver.c](https://raw.githubusercontent.com/torvalds/linux/v7.0/drivers/pci/pci-driver.c).

`pci_update_current_state()` legge PMCSR e aggiorna la cache, considerando
anche il caso D3cold della piattaforma; `pci_refresh_power_state()` aggiunge
il refresh della piattaforma. Entrambe sono interne e non esportate nel
`Module.symvers` effettivo. `pci_enable_device()` comprende il refresh, ma
può abilitare risorse e non è un'API di sola lettura. `pci_set_power_state()`
può attivare operazioni di piattaforma anche partendo da UNKNOWN.
Fonte: [pci.c](https://raw.githubusercontent.com/torvalds/linux/v7.0/drivers/pci/pci.c).

La guardia alternativa proposta è coerente **solo se i nuovi dati provano
UNKNOWN e hardware D0**: mantenere intatta la cache, accettare UNKNOWN
soltanto con identità viva corretta, capability PM verificata, letture PMCSR
riuscite e non `ffff`, stato D0, riferimenti PM mantenuti e nessuna
transizione runtime in corso. Ripetere la lettura immediatamente prima e
dopo la transazione. Rifiutare D3, letture ambigue e capability mancante.
Non è ancora implementata.

La lettura userspace di `sysfs/config` può chiamare il resume del parent
e del dispositivo in D3cold; il normale accesso config del modulo non usa
questo wrapper. L'ordine delle osservazioni PM va quindi conservato:
[pci-sysfs.c](https://raw.githubusercontent.com/torvalds/linux/v7.0/drivers/pci/pci-sysfs.c).

Le copie primarie v7.0 e i loro hash sono in `reference/sources.json`.
La verifica delle esportazioni usa il `Module.symvers` del kernel Ubuntu
7.0.0-38 effettivamente compilato; le copie upstream chiariscono la semantica,
non sostituiscono i dati del prossimo avvio.
