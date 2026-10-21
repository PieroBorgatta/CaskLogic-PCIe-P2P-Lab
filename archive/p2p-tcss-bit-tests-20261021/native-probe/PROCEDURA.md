> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Ripetizione nativa minima dopo la modifica TCSS

Preparazione locale, 21 ottobre 2026. Il coordinatore esegue tutte le operazioni sulla macchina; questi file non installano un avvio EFI e non avviano prove GPU da soli.

La prova precedente è documentata in `gpu-followup-20261020/baremetal-probe/result.log` e `verified-result.json`: Linux `7.0.0-38-generic` avviato direttamente in RAM, IOMMU disabilitata, due GPU presenti. CCFG D7 era ancora `0E009077`. I driver diagnostic e coherent producevano entrambi tre errori su quattro: passava soltanto la scrittura A2000 → Ada. Il primo avvio con una sola GPU non era valido perché mancava l'autorizzazione del tunnel USB4.

Il nuovo giro cambia il firmware già verificato e usa soltanto la build `compiled-dynamic`, la stessa scelta per il confronto corrente nella VM. Non ripete la matrice di driver e non applica scritture PCIe/ACS. Il codice prova resta il `peer_vmm_word_native` già contenuto nell'immagine nativa precedente: quattro byte, lettura e scrittura SM in entrambe le direzioni. Il builder controlla che l'eseguibile coincida con la copia nell'immagine estratta precedente.

I sorgenti e gli artefatti precedenti risiedono nella VM in:

```text
/mnt/llm/riscrivo/runtime/reports/gpu-followup-20261020/baremetal-probe/unpacked/
/mnt/llm/riscrivo/runtime/reports/gpu-followup-20261020/baremetal-probe/peer_vmm_word_native
/mnt/llm/riscrivo/runtime/reports/gpu-followup-20261020/p2p-driver/compiled-dynamic/nvidia.ko
/mnt/llm/riscrivo/runtime/reports/gpu-followup-20261020/p2p-driver/libcuda-experiment/libcuda.so.1
/boot/vmlinuz-7.0.0-38-generic
```

Copiare esclusivamente `init-tcss-native.sh` e `build_native_repeat.py` nella directory nuova della VM, poi eseguire:

```bash
python3 /mnt/llm/riscrivo/runtime/reports/p2p-tcss-bit-tests-20261021/native-probe/build_native_repeat.py
```

Il builder copia l'albero precedente in un nuovo `unpacked`, senza modificarne l'origine. Verifica gli hash del kernel, del modulo dynamic e della libcuda patchata, verifica i collegamenti dinamici nel chroot e produce:

- `probe-kernel.efi`: kernel EFI già usato nella prova precedente.
- `probe-initrd.img`: filesystem RAM nuovo, con un solo test.
- `IDENTITY.txt`: contenuto esatto `CaskLogic-TCSS-native-20261021`.
- `build-manifest.json`: hash effettivi, percorsi e parametri dell'avvio.

La destinazione ESP prevista è `\EFI\CaskLogicTcssNative`, sulla partizione con PARTUUID `3c6ae711-bbc9-4653-bf09-0baac6b3b380`. Il coordinatore gestisce il trasferimento, la nuova entry temporanea e BootNext. Il vecchio ID `0002` e la vecchia directory `CaskLogicBaremetal` risultano rimossi dopo la prova precedente e non vanno assunti ancora disponibili. L'avvio deve essere singolo e lasciare disponibile il BootOrder XCP-ng originale per il successivo riavvio.

Parametri kernel:

```text
initrd=\EFI\CaskLogicTcssNative\probe-initrd.img rdinit=/init intel_iommu=off iommu=off module_blacklist=nouveau,nvidia_drm,nvidia_modeset panic=10 loglevel=4 console=tty0
```

L'init monta soltanto la ESP nota per scrivere risultati. Dopo aver caricato Thunderbolt, autorizza esclusivamente il dispositivo ASMedia con ID `0x2463`, come nel precedente giro valido, e attende la comparsa della A2000 `10DE:2571`. Registra inventario PCI, BAR di tutti i dispositivi NVIDIA, UUID/nome/BDF/temperatura GPU e CCFG della porta interna D1. Richiede D7:F0 e D7:F2 esattamente `00009077` prima e dopo il caricamento driver, e dopo la prova.

Carica il modulo dynamic con gli stessi parametri usati nella VM, UVM e i nodi di dispositivo; esegue una sola volta `peer_word`, con timeout 25 secondi. La prova termina con log e riavvio immediato verso il normale avvio; un watchdog userspace indipendente richiede comunque il riavvio a 180 secondi. Questa difesa non costituisce garanzia contro un blocco totale del kernel.

I risultati sono `result.log` e `kernel.log` nella directory ESP nuova. Un risultato completo richiede entrambe le GPU, i gate CCFG passati, quattro righe `REMOTE_READ/REMOTE_WRITE bytes=4`, `PROBE_COMPLETED` e il codice del test. Un successo numerico richiede quattro `valid=1`, `TOTAL_FAILURES 0` e `NATIVE_TEST_RC=0`. Un fallimento del gate, un timeout o un dispositivo assente non è una misura P2P valida. Conservare i file e verificare il ritorno XCP-ng e lo stato dei servizi prima di qualsiasi altro esperimento.

Solo sintassi shell e AST Python sono stati verificati localmente. L'effettiva build, installazione e prova sono di competenza del coordinatore e vengono registrate separatamente.
