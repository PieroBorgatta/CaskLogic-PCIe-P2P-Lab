> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Parametro BAR1: allineamento corretto, trasferimenti ancora errati

Il parametro esistente `RM64KBBAR1Mappings=0` modifica effettivamente l'allocazione BAR1 dell'A2000: gli offset precedenti `0x2a0000` e `0x4a0000` diventano `0x400000` e `0x600000`. Tutte le quattro finestre ora sono allineate alla pagina RM da2MiB. Le due finestre Ada mantengono gli stessi offset.

Il parser rileva quattro catene complete fra puntatore del programma, mapping DMA, BAR1, PTE RM e PTE UVM. Uguaglianza degli indirizzi, allineamento e ritorni delle operazioni software passano tutti. I quattro controlli di inizializzazione locale dei proprietari passano. D1/D7 mantengono i valori attesi prima del driver, dopo il driver e dopo il test.

| Operazione dei quattro byte | Esito |
| --- | --- |
| A2000 legge Ada | Errato |
| A2000 scrive Ada | Corretto |
| Ada legge A2000 | Errato |
| Ada scrive A2000 | Errato |

La matrice è identica alla prova strumentata precedente. Anche le variazioni PCI restano le stesse: durante la lettura dell'A2000 cambiano i PCI_STATUS dell'A2000 e del rootD7 da`0010` a`2010`; durante la lettura della Ada cambiano quelli della Ada e del rootD1 nello stesso modo. Le due scritture non aggiungono variazioni negli snapshot.

Il primo errore del cleanup IOVAS compare circa277ms dopo `context_exit_begin`, dopo tutti i confronti e le deallocazioni esplicite. Non viene usato per spiegare retroattivamente i tre confronti errati.

La correzione dell'allineamento elimina una condizione errata del mapping ma non risolve il P2P osservato. La catena software coerente non certifica il contenuto della finestra BAR1 né l'indirizzo del TLP sul collegamento: il prossimo discriminante è il controllo della stessa finestra attraverso un accesso CPU in sola lettura.

Evidenza completa: `pte-chain-validation.json`; confronto riproducibile con la prova precedente e hash delle fonti: `alignment-comparison.json`. Nessuna operazione hardware è stata eseguita durante questa analisi locale.
