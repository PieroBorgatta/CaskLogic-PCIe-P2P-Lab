> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# CaskLogic — ordine dei confronti P2P e cleanup IOVAS

## Evidenza del test nativo con solo modifica D7

La prova in `../native-gpu-results` usa il programma SHA256 `612a93dd9f912941ad9870fdd9403265ca4216f0c3ebfbf2917925f24f872dc5`, identico al binario locale `../../gpu-followup-20261020/p2p-driver/peer_vmm_word`. Il sorgente corrispondente chiama `free_peer(src)` e `free_peer(dst)` alla fine di ciascuna iterazione s=0, s=1 (riga26). `free_peer` esegue `cuMemUnmap`, `cuMemRelease`, `cuMemAddressFree` (riga17). Non chiama `cudaDeviceReset` o `cuCtxDestroy`.

Ordine del programma precedente:

1. Alloca src0/dst1, legge0→1: dato corrotto (`EDCBA987`, atteso `12346641`).
2. Scrive1→0: confronto riuscito.
3. Libera src0/dst1.
4. Alloca src1/dst0, legge1→0: dato corrotto identico.
5. Scrive0→1: dato `00000000`, confronto fallito.
6. Libera src1/dst0, stampa tre fallimenti ed esce con5.

**Conclusione certa:** la prima lettura fallita avviene prima del primo rilascio esplicito del programma. Gli errori dei rilasci intermedi non possono spiegarla. Il valore osservato è coerente con una lettura remota `FFFFFFFF` seguita dallo XOR del kernel; questa è una deduzione aritmetica, non una cattura del traffico PCIe.

Il vecchio `kernel.log` registra quattro mapping residui nell'IOVAS `0x100` a13.372954s, poi quattro coppie di assert `pIOVAS != NULL` a13.397920–13.399993s. Il vecchio `result.log` non registra tempi delle fasi. **Non è quindi dimostrato dai soli log se tali assert precedano o seguano l'ultimo confronto.**

## Significato preciso degli assert

Nel sorgente driver locale `../../gpu-followup-20261020/p2p-driver/source/NVIDIA-open-gpu-kernel-modules-19f3b34`:

- `src/nvidia/src/kernel/mem_mgr/io_vaspace.c:60`: `iovaspaceDestruct_IMPL` stampa i mapping residui quando viene distrutta l'intera IOVAS.
- Nello stesso file, `iovaspaceFromMapping:589` e `iovaMappingDestroy:603` cercano la IOVAS associata al mapping. Gli assert598/607 indicano che quella IOVAS non esiste più; il commento del driver descrive esplicitamente il mapping rimasto vivo oltre la IOVAS.
- `src/nvidia/arch/nvalloc/unix/src/osinit.c:1244`: `RmTeardownDeviceDma` distrugge la IOVAS. Il suo chiamante è `RmShutdownAdapter:2537`.
- `kernel-open/nvidia/nv.c:2134`: `nv_close_device` ferma il device se il conteggio di utilizzo arriva a zero; `nvidia_close_callback` lo chiama a2192. Il percorso passa da `nv_stop_device` a `nv_shutdown_adapter` e alla chiusura RM.

Questa catena rende plausibile una comparsa alla chiusura finale dei device, ma il percorso interno della libreria CUDA e il momento effettivo non sono catturati nel test precedente. Non si equiparano gli assert a un errore fisico del collegamento PCIe.

Il modulo realmente usato è `../driver/nvidia-dynamic.ko`, SHA256 `41a3025b63192242bda4f9eb692d8a000fc85850d009c45f679f9ef46f9bef80`. La disassemblatura allegata di `nvGpuOpsDeviceDestroy` conferma che il rilascio RM del sottodispositivo precede la distruzione di tutte le finestre BAR1 dinamiche. La coda delle finestre e il ciclo di vita dei mapping meritano quindi una correzione separata. Non si ricompila il working tree del driver: contiene esperimenti successivi con indirizzi fissi che non appartengono a questo modulo.

## Ripetizione controllata

`peer_vmm_word_delayed.cu` mantiene gli stessi kernel, dati e ordine dei quattro confronti; conserva però tutte e quattro le allocazioni fino al marcatore `data_done`. Solo dopo avvia `cleanup_begin`, libera ogni allocazione nel suo device proprietario, emette `cleanup_done` e `context_exit_begin`. Ogni marcatore contiene `CLOCK_MONOTONIC`, viene scritto su stdout senza buffering e, se disponibile, su `/dev/kmsg`. Un errore di accesso a kmsg è dichiarato e non nascosto.

Il payload utile resta4byte per operazione; le allocazioni VMM rispettano comunque la granularità minima imposta da CUDA. Non è un benchmark di banda. Una chiamata CUDA fallita interrompe il programma prima di `data_done`: in quel caso non si attribuiscono i confronti mancanti a successi/fallimenti dati.

Criteri di lettura del prossimo log:

- Quattro confronti + `data_done` prima degli assert: dati osservati prima del cleanup problematico.
- Assert prima di `data_done`: non dichiarare innocuo il difetto di lifetime; localizzare la prima fase coinvolta.
- Nessun `data_done`, timeout o errore CUDA: prova incompleta, non trasformare in quattro confronti validi.

La ripetizione contiene un solo caricamento del modulo dinamico già verificato e richiede D1CCFG=`00008077`, D7F0/F2CCFG=`00009077` prima del driver, dopo il driver e dopo il test. Non scrive registri PCI. Il nuovo sistema RAM resta separato dal precedente e ritorna automaticamente a XCP-ng.
