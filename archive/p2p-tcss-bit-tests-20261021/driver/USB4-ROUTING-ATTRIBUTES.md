> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Instradamento USB4 e attributi PCIe: verifica mirata

**Esito della ricerca:** nel percorso pubblico Linux v7.0 esaminato non ho identificato un controllo del tunnel PCIe che autorizzi separatamente le richieste della CPU e quelle della GPU interna. La prova degli attributi NoSnoop/Relaxed Ordering è già stata tentata nello storico; un nuovo confronto avrebbe senso soltanto con il protocollo ora sincronizzato, le finestre allineate e readback dei bit durante la prova. Nessuna modifica hardware eseguita da questa analisi.

## Controlli reali nel codice Linux

Sono stati riletti nove file ufficiali a tag v7.0, commit `028ef9c96e96197026887c0f092424679298aae8`, salvati in `reference/linux7-thunderbolt/` e verificati contro il rispettivo Git blob; manifest con SHA-256 in quella cartella. È il codice upstream 7.0, non una verifica byte per byte del modulo Ubuntu 7.0.0-38 presente nel pacchetto.

- `usb4_switch_setup()` abilita il tunneling PCIe con **ROUTER_CS_5.PTO**, condizionato al consenso ACPI e alla presenza di un adattatore PCIe downstream sul parent. È abilitazione dell'intero protocollo, senza BDF sorgente. [Codice Intel/Linux](https://github.com/torvalds/linux/blob/028ef9c96e96197026887c0f092424679298aae8/drivers/thunderbolt/usb4.c#L229).
- `tb_pci_port_enable()` scrive **ADP_PCIE_CS_0.PE, bit31**, all'offset relativo 0 dell'adattatore. Non è il PCI config di D7 e non va confuso con CCFG. [switch.c](https://github.com/torvalds/linux/blob/028ef9c96e96197026887c0f092424679298aae8/drivers/thunderbolt/switch.c#L1385), [definizioni](https://github.com/torvalds/linux/blob/028ef9c96e96197026887c0f092424679298aae8/drivers/thunderbolt/tb_regs.h#L474).
- `tb_pci_set_ext_encapsulation()` usa **ADP_PCIE_CS_1.EE, bit0** soltanto se entrambi router sono almeno USB4 v2 e il link è generazione 4. Non è una manopola generale per il link Gen3 di questa generazione. [tunnel.c](https://github.com/torvalds/linux/blob/028ef9c96e96197026887c0f092424679298aae8/drivers/thunderbolt/tunnel.c#L299), [usb4.c](https://github.com/torvalds/linux/blob/028ef9c96e96197026887c0f092424679298aae8/drivers/thunderbolt/usb4.c#L3118).
- I path PCIe usano HopID 8 nelle due direzioni, crediti, priorità e flow control; `drop_packages=0`. I campi pubblici programmati in `tb_path_activate()` non contengono un RequesterID o una tabella di autorizzazione degli endpoint. L'assenza dal codice esaminato non esclude controlli interni del silicio o firmware. [tunnel.c](https://github.com/torvalds/linux/blob/028ef9c96e96197026887c0f092424679298aae8/drivers/thunderbolt/tunnel.c#L18), [path.c](https://github.com/torvalds/linux/blob/028ef9c96e96197026887c0f092424679298aae8/drivers/thunderbolt/path.c#L540).
- Il quirk esplicito Alder Lake limita la banda USB3; non documenta peer routing o un filtro PCIe. Nessun quirk ASM2464 specifico in questa tabella. [quirks.c](https://github.com/torvalds/linux/blob/028ef9c96e96197026887c0f092424679298aae8/drivers/thunderbolt/quirks.c#L68).

Il log nativo postwrite mostra ACPI USB4 che cede a Linux USB3/DP/PCIe/XDomain e identifica il router esterno come ASMedia vendor0xb8 device0x2463. Le funzioni PCIe del bridge riportano invece 1b21:2461: sono spazi di identificazione diversi, non una contraddizione.

L'autorizzazione Thunderbolt documentata dal kernel crea o elimina il tunnel PCIe intero. Un tunnel assente non è coerente con enumerazione GPU e CPU BAR1 read riuscite, ma questo **non** certifica ogni tipo di pacchetto transitabile. [Documentazione Linux](https://www.kernel.org/doc/html/latest/admin-guide/thunderbolt.html).

## Limiti della documentazione ASM

ASMedia conferma pubblicamente PCIe Gen4 e packet switch incorporato nell'ASM2464PD, ma la pagina letta non pubblica registri di source validation, selezione RequesterID, rilascio firmware o workaround P2P. [Annuncio del produttore](https://www.asmedia.com.tw/news-main/e46Zz4cRqeTi7PQ3.html).

È emerso il progetto pubblico `tinygrad/asm2464pd-firmware`: il sorgente handmade esaminato è un firmware USB3 vendor-class con comandi per generare TLP e trasferire SRAM, non una dimostrazione del comportamento del tunnel USB4 nativo installato. Non propongo flash o trasporto via USB3/SRAM: non risolverebbe il requisito di P2P diretto esistente. [README](https://github.com/tinygrad/asm2464pd-firmware), [main.c](https://github.com/tinygrad/asm2464pd-firmware/blob/master/handmade/src/main.c).

La specifica USB4 e i documenti di sicurezza descrivono protezioni della transazione rispetto all'identità del richiedente; non ho ricavato una mappa di registro applicabile a TCSS Alder Lake o al firmware ASM installato. Il testo completo USB-IF e un mirror PDF non erano scaricabili dai canali provati. Non uso questi risultati parziali per inventare un nuovo offset o riproporre ACS.

## NoSnoop / Relaxed Ordering: cosa è già stato provato

1. `gpu-followup-20261020/baremetal-probe/init-probe.sh:104` scriveva **CAP_EXP+8.w=0000:0810** su Ada01:00.0, A200006:00.0, D1, D7 e i due bridge dopo il caricamento del driver coerente. Il secondo test nativo completò con 3 fallimenti su4. Il log non registra readback DEVCTL; il probe precede la correzione della sincronizzazione owner e l'allineamento BAR1.
2. `p2p-driver/bar1-disable-nosnoop.patch` forzava `kbifEnableNoSnoop_HAL(...NV_FALSE)`; `nosnoop-off-small-events.json` documenta il driver caricato nella VM e 3 fallimenti su4 su65536byte. Non è una prova del solo bit RO né della piattaforma nativa nella configurazione attuale.
3. Il codice NVIDIA della build analizzata abilita normalmente RO e NoSnoop nella routine d'inizializzazione. Cita un workaround P2P NoSnoop per un chipset non identificato nel commento; non identifica Alder Lake e non dimostra un bug dell'ASM. Un clear effettuato prima che CUDA apra il contesto può venire sovrascritto dal driver. [kernel_bif.c NVIDIA](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/19f3b34/src/nvidia/src/kernel/gpu/bif/kernel_bif.c), [HAL NoSnoop](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/19f3b34/src/nvidia/src/kernel/gpu/bif/arch/maxwell/kernel_bif_gm107.c).
4. Nei dump postwrite prima-driver: PCIe capability0x78, DEVCTL Ada0x2930, A20000x2910: bit11 e bit4 entrambi1. Questi dump non provano i bit durante il kernel CUDA.

I bit standard interessati sono **PCI_EXP_DEVCTL_NOSNOOP=0x0800** e **PCI_EXP_DEVCTL_RELAX_EN=0x0010**. Il codice NVIDIA pubblicato definisce NoSnoop bit11 e il suo HAL modifica quel campo preservando gli altri. Non ho trovato una prova primaria che ogni PTE SYS_NONCOHERENT usata in questo esperimento implichi necessariamente un TLP NoSnoop, né che il bridge scarti quel TLP.

Un confronto utile deve mantenere identiche allocazioni e mapping, inizializzazioni sincronizzate e contenuto da trasferire; leggere DEVCTL subito prima e dopo ciascun kernel; modificare soltanto quei due bit con accesso16bit; ripristinarli prima dell'uscita. Non scrivere un dword DeviceControl+DeviceStatus, perché lo stato superiore contiene bit W1C. Il solo readback del controllo non sostituisce una cattura dei TLP.

**Aggiornamento dopo la prova nativa controllata:** il confronto è stato completato su cinque fasi con le stesse quattro allocazioni: baseline, clear dei soli bit 0x0810 sulla Ada, restore, clear su entrambe, restore finale. Tutte le fasi conservano tre fallimenti su quattro; 282 letture DEVCTL e sei scritture esatte confermano la modifica e il ripristino. Il gate shell ha prodotto un falso negativo BusyBox, riprodotto e distinto dai risultati completi della prova. Vedere `../native-nosnoop-gpu-results/ANALISI.md` e `verified-result.json`. Non è una correzione dimostrata e non localizza definitivamente il problema in TCSS, ASM o GPU.


## Conclusione operativa della ricerca sul controller

Il toggle NoSnoop/RO non è un presunto comando di abilitazione P2P del tunnel: è un confronto degli attributi emessi dal richiedente. Il codice Linux consultato non fornisce una nuova modifica motivata a RequesterID o downstream peer forwarding per questo host. Non propongo ri-autorizzazioni, riconfigurazioni dei path o cambi dei crediti: i controlli individuati riguardano l’intero tunnel e non discriminano la richiesta che qui fallisce. Questa conclusione è circoscritta ai registri pubblici e al codice esaminati; non esclude controlli privati TCSS/ASM, errata o una diversa implementazione firmware. Rimane da collegare il comportamento misurato al componente che scarta o termina la transazione.
