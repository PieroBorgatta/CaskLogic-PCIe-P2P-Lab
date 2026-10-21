> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# SYS_COH effettivo, stesso difetto P2P

La variante è stata realmente compilata e provata in Linux nativo. Tutti i quattro mapping esterni passano da SYS_NONCOH a SYS_COH, ma rimangono tre confronti falliti su quattro: le due letture e la scrittura Ada→A2000. Passa ancora soltanto A2000→Ada. Il programma e lo script terminano RC5 con `PROBE_COMPLETED`; questa esecuzione non presenta il falso negativo AWK della precedente prova NoSnoop.

| Operazione | Esito P2P | Osservazione CPU dopo scrittura |
| --- | --- | --- |
| A2000 legge Ada | FAIL | — |
| A2000 scrive Ada | PASS | `a5a42468`, atteso `a5a42468` |
| Ada legge A2000 | FAIL | — |
| Ada scrive A2000 | FAIL | `00000000`, atteso `a5a42468` |

Le osservazioni CPU sono dopo la sincronizzazione della GPU scrivente e prima del D2H del proprietario; concordano con il confronto successivo. Nessuno SKIP. I due controlli CPU precedenti, ciascuno a due pattern, passano; passano anche tutti i dieci controlli locali del proprietario. Gli oggetti restano vivi fino al termine dei quattro confronti.

## Variazione verificata nei PTE

Il modulo RM è `c89df9be…052e7eb`, UVM resta esattamente `9b993671…89c4d0`. La sorgente CUDA è invariata rispetto al precedente postwrite; il solo cambiamento nel programma è la traduzione diagnostica dell'enum coerente. Parametri osservati: `RM64KBBAR1Mappings=0;RMCaskPeerCoherent=1`.

| Finestra | Proprietario | GPUVA | Fisico/DMA | Primo PTE raw |
| --- | --- | --- | --- | --- |
| 1 | Ada | `753b03400000` | `4000400000` | `060000040004000d` |
| 2 | A2000 | `753b03600000` | `4600400000` | `060000046004000d` |
| 3 | A2000 | `753b03800000` | `4600600000` | `060000046006000d` |
| 4 | Ada | `753b03a00000` | `4000600000` | `060000040006000d` |

In ogni catena il log RM riporta **enum software4**, il PTE contiene **encoding hardware2**, e UVM copia lo stesso PTE. Rispetto alla baseline postwrite, gli indirizzi fisici sono identici e la differenza raw è esattamente XOR2. Restano invariati: formato2, entry16 byte, pagina2 MiB, readonly0, volatile1, atomic1, valid1. Tutti gli indirizzi sono allineati a2 MiB. Le quattro catene nonce→allocazione→handle→finestra→DMA→RM→UVM sono complete e tutte le attese/submission terminano correttamente.

Questa verifica dimostra che il cambiamento previsto è arrivato alla rappresentazione software consegnata a UVM; non è una cattura delle transazioni PCIe né una rilettura delle tabelle MMU hardware.

## Identità, PCIe e chiusura

Verificati i17 hash raccolti e la corrispondenza del manifest con il pacchetto previamente ispezionato dentro l'initrd. UUID/BDF identificano Ada0 a01:00.0 e A2000 1 a06:00.0. D1 CCFG00008077 e D7 F0/F2 CCFG00009077 sono riletti prima di NVIDIA, dopo NVIDIA e dopo il test.

Tutte le126 letture PCIe sono complete da4096 byte e senza errori. Le sole quattro variazioni fra fotografie consecutive sono PCI_STATUS0010→2010, Received Master Abort:

- A2000 e D7 quando A2000 legge Ada;
- Ada e D1 quando Ada legge A2000.

Non appaiono ulteriori variazioni AER o header durante le scritture e i controlli CPU. Questo non equivale ad assenza di errore PCIe: RMA è presente. Non sono registrati Xid.

`data_done` è a13.669963975 secondi monotonic, `context_exit_begin` a13.670357475. Tutte le quattro finestre raggiungono `WINDOW_DESTROY_DONE`. I quattro residui IOVAS compaiono circa270,88 ms dopo l'uscita dal contesto; il primo assert circa297,64 ms dopo. La correlazione usa41 marker comuni, con dispersione39,4 µs. Questi difetti di cleanup restano reali e separati dai confronti già conclusi.

## Conclusione delimitata

L'attributo SYS_COH, da solo e nelle condizioni verificate, non corregge il difetto. L'allineamento, l'indirizzo software e il successo della lettura/scrittura CPU della stessa finestra non bastano a garantire la consegna da una GPU all'altra. Questa prova non localizza il componente che rifiuta le letture o impedisce la scrittura verso A2000, non verifica operazioni atomiche e non qualifica il driver per produzione.

Dati strutturati: [verified-result.json](verified-result.json). Catene e confronto integrale dei PTE: [coherent-chain-validation.json](coherent-chain-validation.json). Verifica ripetibile locale: [analyze_result.py](analyze_result.py).
