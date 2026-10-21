> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Preparazione della sola immagine RAM

Eseguire nella VM Linux, con training fermo, dopo aver copiato in questa directory `peer_vmm_word_delayed.cu`, `init-tcss-native.sh` e `build_native_repeat.py`. Non esegue la prova GPU, non installa file nell'ESP e non modifica BootNext.

Compilazione con il CUDA toolkit già disponibile (se si usa il container esistente, non sono necessarie GPU assegnate):

```sh
cd /mnt/llm/riscrivo/runtime/reports/p2p-tcss-bit-tests-20261021/native-d1-probe
nvcc -O2 -std=c++17 --cudart=static -gencode arch=compute_86,code=sm_86 -gencode arch=compute_89,code=sm_89 peer_vmm_word_delayed.cu -lcuda -o peer_vmm_word_delayed_native
python3 build_native_repeat.py
```

Se il linker nel container non trova `libcuda`, aggiungere il percorso `stubs` del toolkit già installato alla ricerca delle librerie di link. La libreria usata a runtime nell'immagine è invece il file `libcuda-experiment/libcuda.so.1` dal report, verificato dal builder tramite SHA256.

Il builder copia `native-probe/unpacked` in `native-d1-probe/unpacked`, rifiuta di sovrascrivere un'estrazione già presente, verifica kernel/modulo/libcuda/sorgente, risolve le dipendenze del programma e controlla sintassi init e caricamento ELF dentro chroot. Produce `probe-kernel.efi`, `probe-initrd.img`, `IDENTITY.txt` e `build-manifest.json`.

L'installazione ESP e il singolo avvio restano responsabilità dell'operatore root, che deve prima conservare e verificare l'immagine precedente. Directory ESP invariata: `EFI/CaskLogicTcssNative`. Identità invariata: `CaskLogic-TCSS-native-20261021`. I risultati andranno raccolti in una nuova directory, distinguendoli da `native-gpu-results` della modifica D7.

I controlli locali eseguiti sul Mac sono sintassi shell, parsing AST del builder e confronto degli hash. Compilazione CUDA, chroot e prova hardware devono risultare dai successivi log della VM e del boot nativo.
