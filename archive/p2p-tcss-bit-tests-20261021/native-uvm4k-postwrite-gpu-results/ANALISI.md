> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Esito della prova P2P con pagine da 4 KiB

**La variante è stata applicata realmente e non risolve il problema: tre confronti falliscono su quattro.** GPU0 è RTX 2000 Ada, GPU1 è RTX A2000. Il parametro osservato è `UVM_PEER_SMALL_PAGES=Y`; RM rimane il modulo strumentato precedente.

| Operazione | Esito | Riscontro CPU dopo peer write |
|---|---|---|
| A2000 legge VRAM Ada | Fallisce | — |
| A2000 scrive VRAM Ada | Passa | `a5a42468`, atteso e concorde con D2H |
| Ada legge VRAM A2000 | Fallisce | — |
| Ada scrive VRAM A2000 | Fallisce | `00000000`, concorde con D2H, atteso `a5a42468` |

Tutte le dieci verifiche locali dei proprietari passano; entrambi i controlli CPU BAR1 iniziali passano con due pattern. D1 resta `00008077`, D7:F0/F2 restano `00009077` prima e dopo. Il programma completa e restituisce 5.

Il parser ricostruisce tutte e quattro le catene con puntatori PROBE_PTR diretti, senza controlli mancanti o discordanti. Ogni mapping riporta **page=0x1000, entry=8, pte_count=512**, con allineamento valido. BAR1, offset, indirizzo DMA e indirizzo codificato/decodificato coincidono; RM e UVM riportano lo stesso primo PTE, writable e aperture=3. L'uso delle pagine 4 KiB è quindi confermato dai log, non soltanto dal parametro.

| Finestra | Proprietario | Ruolo | GPU VA | Indirizzo fisico osservato |
|---|---|---|---|---|
| 1 | Ada | Target peer | 76095f400000 | 4000400000 |
| 2 | A2000 | Output locale read | 76095f600000 | 4600400000 |
| 3 | A2000 | Target peer | 76095f800000 | 4600600000 |
| 4 | Ada | Output locale read | 76095fa00000 | 4000600000 |

Dopo ciascuna lettura peer compare PCI_STATUS bit13 sul richiedente e sulla sua root: A2000/D7 per la lettura della Ada, Ada/D1 per la lettura della A2000. Le scritture non aggiungono cambiamenti nei registri PCIe campionati. La lettura CPU successiva alla scrittura fallita conferma il valore zero anche attraverso BAR1, senza mostrare una divergenza rispetto al D2H in questa prova.

Tutte quattro le finestre riportano WINDOW_DESTROY_DONE. La prima segnalazione di quattro mapping residui IOVAS arriva **269,087 ms dopo context_exit_begin**; seguono otto assert. Nessun Xid. Questi messaggi appartengono al teardown, successivo ai quattro confronti; il difetto di cleanup resta separato.

Sono stati ricontrollati gli SHA-256 di 21 file raccolti. La verifica completa e riproducibile è in [verified-result.json](verified-result.json); la catena dettagliata è in [pte-chain-validation.json](pte-chain-validation.json). Le fonti sono result.log *(artefatto locale non pubblicato)* e kernel.log *(artefatto locale non pubblicato)*.

Limite: il log stampa il primo PTE di ogni gruppo e il conteggio totale; non verifica tutte le 512 entry né legge le page table hardware o i TLP sul collegamento. Una catena software coerente non dimostra correttezza del trasporto. La verifica VT-d è riportata separatamente dall'agente audit.
