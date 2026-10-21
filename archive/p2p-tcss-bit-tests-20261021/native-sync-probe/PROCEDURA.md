> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Prova nativa con sincronizzazione dell'owner

Sorgente separato dalla prova precedente: `peer_vmm_word_sync.cu`, con `pcie_diag.h` nella stessa directory. Il programma mantiene i due kernel e i quattro confronti da 4 byte; sincronizza il proprietario dopo H2D e dopo azzeramento, quindi verifica localmente il valore atteso prima dell'accesso peer. Non inoltra il dato all'altra GPU tramite CPU. Tutti i free restano dopo `data_done`.

Il memset della destinazione e il kernel di lettura sono ordinati sullo stesso device/default stream. Ogni kernel termina con una sincronizzazione del device che lo esegue prima del confronto CPU. Le letture PCIe prima/dopo ogni operazione e alla baseline non cancellano gli status sticky: confrontare i cambiamenti, non soltanto la presenza di bit già impostati.

Compilazione nella VM con il toolkit esistente, senza avviare un carico GPU:

```sh
cd /mnt/llm/riscrivo/runtime/reports/p2p-tcss-bit-tests-20261021/native-sync-probe
nvcc -O2 -std=c++17 --cudart=static -gencode arch=compute_86,code=sm_86 -gencode arch=compute_89,code=sm_89 peer_vmm_word_sync.cu -lcuda -o peer_vmm_word_sync_native
python3 build_native_repeat.py
```

Il builder clona la precedente estrazione `native-probe/unpacked` senza modificarla. I tre file destinati all'ESP e `build-manifest.json` vengono prodotti nella cartella sorella `native-sync-probe-package`; la cartella non deve già esistere. L'ESP resta `EFI/CaskLogicTcssNative` e l'identità resta `CaskLogic-TCSS-native-20261021`.

Questo builder non installa il pacchetto, non arma BootNext, non scrive il firmware e non esegue il test. Richiede il profilo D1=00008077/D7=00009077 prima/dopo driver e dopo i confronti, dunque il candidato firmware combinato deve essere realmente attivo per la prova hardware dell'operatore. Il precedente codice di produzione e i reperti delle prove anteriori restano invariati.

Per interpretare il risultato occorrono quattro `OWNER_CHECK ... valid=1`, tutti e quattro i confronti peer e il marcatore `data_done`. Un errore nell'owner interrompe con codice10 e rende incompleta la prova peer. La presenza di capability CUDA true, da sola, continua a non dimostrare dati corretti. Gli hash dei sorgenti e la revisione delle dipendenze sono in `source-review.json`.
