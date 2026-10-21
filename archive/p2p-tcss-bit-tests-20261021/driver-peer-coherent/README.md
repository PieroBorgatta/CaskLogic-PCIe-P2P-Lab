> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Accesso BAR1 coerente: candidato isolato

Candidato diagnostico, non ancora compilato né eseguito al momento della preparazione. La sola variazione funzionale è l'apertura GMMU usata per i mapping esterni BAR1 pre-Blackwell. Aggiungere `;RMCaskPeerCoherent=1` alla stringa `NVreg_RegistryDwords` esistente, mantenendo `RM64KBBAR1Mappings=0` e le altre impostazioni del confronto. Parametro assente, zero, valore diverso da uno o lettura registry fallita conservano il ramo precedente.

Il punto modificato è `nvGpuOpsGetExternalAllocAperture`, dentro `ADDR_FBMEM`, `isBar1P2PSupported` e il ramo che non abilita le atomiche BAR1. Restano invariati indirizzi, dimensione pagine, allocazioni, mapping BAR1, flag volatile/atomic, gestione cache e cleanup. Il codice sorgente NVIDIA motiva il ramo non coerente pre-Blackwell con la mancanza di supporto alle atomiche in ingresso (bug3264814): questa prova usa esclusivamente load/store ordinari. Il flag atomic del PTE resta invariato; non si rivendica supporto alle operazioni atomiche né idoneità per produzione.

## Motivo verificabile

Intel, documento710723-003, §2.15, **pagina stampata61**, descrive la decodifica PCIExpress e limita la semantica non-snoop alla memoria DRAM. Estratto breve:

> All “Snoop not required semantic” cycles should reference the direct DRAM address range.

Il seguito descrive un completamento non riuscito per letture non-snoop fuori dalla RAM e scritture con byte enable disabilitati. Questo rende utile verificare la classe della transazione emessa; non dimostra da solo che il pacchetto osservato sul collegamento Thunderbolt abbia NoSnoop, né equipara TCSS a DMI. Il PTE software è evidenza dell'attributo impostato dal driver, non una cattura TLP.

Fonte Intel: https://cdrdv2-public.intel.com/710723/710723-003.pdf

Fonte NVIDIA stock: https://github.com/NVIDIA/open-gpu-kernel-modules/blob/595.99.02/src/nvidia/src/kernel/rmapi/nv_gpu_ops.c

La memoria RAM di sistema segue normalmente `GMMU_APERTURE_SYS_COH`; la finestra BAR1 sperimentale pre-Blackwell seguiva `SYS_NONCOH`. Pertanto una copia GPU↔RAM riuscita non costituisce prova equivalente sul percorso GPU→BAR1.

## Risultato atteso nei log

L'enum software `GMMU_APERTURE_SYS_COH` vale **4**: il log `RM_PTE aperture` deve passare da3 a4. Il campo hardware APERTURE nel PTE vale invece **2**, contro3 per NONCOH. A parità degli altri campi, la prima parola raw del PTE cambia con XOR2, per esempio termina in`0d` invece di`0f`. Non confondere enum software ed encoding hardware. I log devono confermare indirizzi invariati, readonly0, volatile e atomic invariati, pagine2MiB allineate, copia RM→UVM e attese completate.

Il programma postwrite storico SHA603bea3c28a83bfa8d06dd13e358c43885ba9e4534f8bcd7e4e0250250ec1aea contiene un parser CPU che accetta soltanto enum2/3: con enum4 produrrà `SKIP rm_pte_mismatch`. I quattro confronti P2P restano eseguibili. Per mantenere anche il controllo CPU serve un clone con correzione esplicita enum4→encoding2, senza alterare il programma storico. Uno SKIP non è una lettura CPU fallita.

## Compilazione solo CPU

`build_rm_only.py` richiede archivio stock autenticato e build baseline strumentata completata. Ricostruisce da zero in una directory nuova mediante l'helper con hash fissato, applica le patch baseline e poi soltanto `peer-coherent.patch`. Compila il modulo kernel `nvidia`, copia `nvidia-uvm.ko` baseline SHA9b993671ef066c9d3e58fd52b0d70228861769a2e3dcf304bc3d80bca089c4d0 senza ricompilarlo, e confronta CRC/tipo/namespace di tutti gli export RM. Non installa né carica moduli.

Il manifest finale è `driver-peer-coherent-build-01/build-manifest.json`; soltanto `status=built_not_installed` indica compilazione e verifiche completate. Gli output restano distinti dalla baseline e dalle varianti precedenti. Le proprietà del parametro sono nel manifest del candidato, mentre le identità binarie definitive vengono calcolate dopo la compilazione target.
