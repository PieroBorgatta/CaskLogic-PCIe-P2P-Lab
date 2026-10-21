> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Verifica in sola lettura delle finestre sotto 4 GiB

`verify_low_mmio.c` verifica l'assetto previsto dopo la rilocazione, sia prima
sia dopo il caricamento del driver. Non esegue scritture PCI, sizing dei BAR,
allocazioni di risorse, caricamento o scaricamento di driver.

Compilazione statica Linux, da eseguire nell'ambiente CPU di build:

```sh
cc -std=c11 -O2 -Wall -Wextra -Werror -static verify_low_mmio.c -o verify_low_mmio
```

L'esecuzione senza argomenti legge `/sys/bus/pci/devices`, verifica CPUID
`000906a3` e assenza del bit hypervisor, nove identità PCI, BAR1
`8000000c/00000000` e risorsa `80000000–8fffffff`, BAR3
`9000000c/00000000` e risorsa `90000000–91ffffff`. Le tre finestre bridge
devono avere registri `24=91f18001`, `28=0`, `2c=0`, risorsa
`80000000–91ffffff` e flag esatti `00102201`. I flag dei BAR sono
`0014220c`. Il kernel catturato abilita CONFIG_PCI_IOV: l'indice della
finestra prefetch nel file resource è **15**, non 9.

Il wrapper deve richiedere exit status zero e la riga finale esatta
`LOW_MMIO_NATIVE_PASS` a entrambe le verifiche. Un risultato vale soltanto
per l'istante della lettura; non certifica che successivamente il driver
non cambi risorse. I registri statici sono riletti dopo le risorse del
kernel per rifiutare variazioni durante la verifica. COMMAND e STATUS
non vengono confrontati perché possono variare normalmente dopo il driver.

Il programma non confronta tutte le allocazioni PCI della macchina con un
baseline: controlla i cinque intervalli richiesti. Le guardie del modulo
kernel restano necessarie per autorizzare l'operazione di rilocazione.

`--fixture ROOT` è esclusivamente per dati offline: usa
`ROOT/sys/bus/pci/devices` e `ROOT/cpu.identity` con EAX/ECX del CPUID1
scritti in esadecimale. Il successo emette `LOW_MMIO_FIXTURE_PASS`, mai il
token nativo. Il test locale sintetico ha superato **75/75 casi**, inclusi
identità, dimensioni, flag, registri alterati, file mancanti o malformati.
Ogni caso verifica inoltre che nessun file della fixture cambi.

```sh
python3 test_verify_low_mmio.py ./verify_low_mmio --report verifier-offline-tests.json
```

La compilazione e i test eseguiti localmente usano clang su macOS ARM64;
non sostituiscono la compilazione statica Linux x86_64. L'esperimento di
rilocazione è sospeso mentre si verifica il problema di allineamento delle
finestre dinamiche BAR1 nel driver.
