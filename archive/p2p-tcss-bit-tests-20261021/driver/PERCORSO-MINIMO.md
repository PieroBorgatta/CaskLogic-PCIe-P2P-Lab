> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Prova mirata TCSS: un solo test P2P da 4 byte per configurazione

Preparazione locale del 21 ottobre 2026. Non sono stati eseguiti SSH, prove GPU o modifiche sul server da questa attività.

## Build selezionata

Usare la build già presente nella VM:

`/mnt/llm/riscrivo/runtime/reports/gpu-followup-20261020/p2p-driver/compiled-dynamic/nvidia.ko`

SHA-256 verificato sulla copia trasferita dal server: `41a3025b63192242bda4f9eb692d8a000fc85850d009c45f679f9ef46f9bef80`.

Versione `595.99.02`, vermagic `7.0.0-38-generic`, srcversion `919309EF6954372EFADD77E`. È la build con il port BAR1 dinamico, precedente alle varianti di tracing e indirizzi Xen. La copia `nvidia-dynamic.ko` e il suo disassemblato sono in questa directory.

Ho esaminato `nv_dma_map_peer` di questa build e di `compiled-diagnostic`: entrambi usano la DMA API o `pcibios_resource_to_bus` con l'offset della BAR. Non contengono il ramo per gli ID `0x28b0/0x2571` e gli indirizzi hardcoded introdotti dalle patch `xen-physical-bar-diagnostic.patch` e `xen-low-gpa-alias.patch`. Il modulo dynamic non contiene messaggi `RISCRIVO_DIAG`; quello diagnostic ne contiene quattro. La verifica e gli identificativi sono in `build-audit.json`.

Non usare `compiled-coherent`, `compiled-xen-bar`, `compiled-xen-alias`, `compiled-nosnoop`, `compiled-packet128` o `compiled-static` per questa prova: aggiungerebbero variabili estranee al cambiamento dei bit TCSS. Non ricompilare dalla directory sorgente corrente, che contiene ancora patch diagnostiche successive.

Parametri esclusivi della prova:

```text
ForceP2P=0x11;RMForceP2PType=1;RMPcieP2PType=1;RMForceStaticBar1=0
```

Non ridurre la VRAM con `OverrideFbSize`. Atomiche PCIe disabilitate; il test richiede solamente letture e scritture SM.

## Programma già compilato

`peer_vmm_config_gate` esegue quattro confronti sui dati: lettura e scrittura SM in ciascuna direzione, quattro byte per confronto. I buffer VMM sono arrotondati alla granularità minima CUDA, ma il payload verificato è un solo `unsigned`. Non è un benchmark di banda.

- SHA-256 programma gated: `2f7f01412a273b32f442be9e523e98a6f4fdc5611ae7338e99ba4031693afae7`.
- Variante senza gate `peer_vmm_word`: `612a93dd9f912941ad9870fdd9403265ca4216f0c3ebfbf2917925f24f872dc5`.
- SHA-256 libcuda patchata richiesta: `03271500dbda9456e3ba765270bd2609bef2631672809da50b19c67fb1f609a7`.

Attenzione: la copia **locale** preesistente `gpu-followup-20261020/p2p-driver/libcuda-experiment/libcuda.so.1` è originale (`192d4eed...`), anche se `patch.json` documenta la variante patchata. Non copiarla sopra quella server. Il runner controlla l'hash effettivo della libreria prima di toccare driver o servizi.

## Runner e comando esatto nella VM

`run_word_trial.py` è una variante isolata del runner precedente: fotografia attuale dei servizi, controllo training inattivo e nessun utilizzatore GPU, lock contro prove concorrenti, hash obbligatori, directory nuova per ciascuna configurazione, timeout e ripristino dei moduli stock senza sovrascrivere file di sistema. La sintassi è stata verificata localmente tramite AST; non è stato eseguito contro hardware.

Dopo aver copiato soltanto questo script nella corrispondente directory della VM, il comando per una configurazione è:

```bash
systemd-run --unit=riscrivo-tcss-word-candidate --collect \
  --property=RuntimeMaxSec=240 --property=TimeoutStopSec=40 \
  python3 /mnt/llm/riscrivo/runtime/reports/p2p-tcss-bit-tests-20261021/driver/run_word_trial.py \
  --trial-root /mnt/llm/riscrivo/runtime/reports/gpu-followup-20261020/p2p-driver \
  --module /mnt/llm/riscrivo/runtime/reports/gpu-followup-20261020/p2p-driver/compiled-dynamic/nvidia.ko \
  --module-sha256 41a3025b63192242bda4f9eb692d8a000fc85850d009c45f679f9ef46f9bef80 \
  --out /mnt/llm/riscrivo/runtime/reports/p2p-tcss-bit-tests-20261021/driver/candidate \
  --program peer_vmm_config_gate
```

Il nome `candidate` identifica una sola impostazione realmente letta e modificata dal coordinatore host. Per un'altra impostazione occorrono una nuova directory e un altro nome unit. Non lanciare una matrice indiscriminata: prima provare che i bit nel REGBAR D7:F0 siano scrivibili e che la modifica sopravviva alla lettura immediata.

### Protocollo dei due gate

Il test crea `candidate/config-gate-ready` **dopo** inizializzazione CUDA, mapping peer e azzeramento dei buffer. Il contenuto è inizialmente `0`, successivamente `1`. Per ciascun valore:

1. Il coordinatore legge dal lato host il registro fisico D7:F0. Applica solo il cambiamento già autorizzato e ne salva valore prima/dopo e verifica esatta. Questo runner non tocca il registro.
2. Solo dopo il read-back atteso, il coordinatore scrive nella VM lo stesso valore in `candidate/config-gate-go`, per esempio:

```bash
printf '0\n' > /mnt/llm/riscrivo/runtime/reports/p2p-tcss-bit-tests-20261021/driver/candidate/config-gate-go
```

3. Ripete per `1`, perché il secondo giro crea nuovi mapping e la configurazione va verificata di nuovo.

Ogni gate aspetta al massimo 20 secondi; il container ha limite complessivo di 65 secondi. Se il registro non mantiene il valore, non liberare il gate: il test termina per timeout e tenta il ripristino. Il coordinatore deve avere un proprio `finally`/watchdog per ripristinare i bit host anche quando la VM o il container non rispondono.

Per una misura di riferimento con nessuna modifica PCIe si può usare lo stesso protocollo, registrando semplicemente il valore e liberando i due gate senza scritture hardware. In questo modo il confronto usa la stessa build e lo stesso programma.

## Interpretazione e ripristino

`gpu-result.json` riporta `complete=true` solo con quattro righe di dati da quattro byte. `valid=true` richiede tutte e quattro `valid=1`, `TOTAL_FAILURES 0` e uscita zero. Una capability true o un container che termina non bastano. I nomi `s/d` nelle letture indicano proprietario sorgente/destinazione; nelle scritture indicano GPU che scrive/GPU destinataria. L'associazione GPU0/GPU1 va letta dalla query UUID/nome/PCI registrata negli eventi, non assunta.

Il runner termina con codice 0 per dati tutti corretti, 5 per prova completa con corruzione, 6 per prova incompleta, 70 per errore o ripristino non confermato. `restore.json` verifica che tornino le srcversion stock iniziali e il funzionamento di `nvidia-smi`. Conserva anche i log kernel prima e dopo. Non avvia il training.

Il ripristino può essere richiamato separatamente, dopo la terminazione del runner originale:

```bash
python3 /mnt/llm/riscrivo/runtime/reports/p2p-tcss-bit-tests-20261021/driver/run_word_trial.py \
  --out /mnt/llm/riscrivo/runtime/reports/p2p-tcss-bit-tests-20261021/driver/candidate \
  --restore-only
```

Un processo GPU bloccato nel kernel può impedire anche lo scaricamento del modulo: nessun timeout userspace garantisce il recupero. Il runner in quel caso lascia `stock_restored=false`, non prosegue con altre configurazioni e non annuncia un ripristino inesistente.

## Cleanup BAR1: limite della build, non confondere con il risultato dei dati

La build dinamica presenta il difetto di durata dei mapping già analizzato. Le prove precedenti sono riuscite a completare i quattro confronti e a ricaricare stock; quindi il difetto non impedisce di ottenere una singola osservazione mirata. Non attribuire però al solo risultato dei dati una convalida del driver.

Se il nuovo giro produce mapping residui IOVAS, assert o impossibilità di ripristinare stock, fermarsi. La correzione minima da progettare nel sorgente è drenare i mapping dinamici **prima** di liberare subdevice/IOVAS, coprire anche le uscite di `nvGpuOpsFreeDupedHandle` che liberano l'handle dopo un lookup fallito, e gestire gli errori nell'acquisizione del lock remoto senza proseguire con unmap non protetto. Va preservata la durata dell'allocazione fino a fine unmap. Non è corretto aggiungere semplicemente una chiamata dopo la distruzione della IOVAS o ignorare gli assert. Non ho applicato né compilato tale correzione: una nuova variante non è necessaria prima di stabilire se i bit TCSS possono realmente cambiare.
