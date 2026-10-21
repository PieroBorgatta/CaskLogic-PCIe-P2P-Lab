> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Audit indipendente di mapping, PCIe e durata delle allocazioni

La prova a firmware originale riproduce l’asimmetria delle scritture: PUSH Ada→A2000 fallisce in tutti i 6 casi, PUSH A2000→Ada riesce in tutti i 6; PULL fallisce in entrambi i versi, 12 casi su 12. CE e SM mostrano lo stesso esito numerico. Questo chiude il precedente dubbio sulla mancanza di un controllo sincronizzato con FSP originale, senza dimostrare l’impossibilità assoluta di un’altra soluzione.

I 17 file grezzi locali corrispondono agli SHA256 raccolti dall’ESP nel manifesto preliminare. Gli input del pacchetto corrispondono ai sorgenti revisionati; RM `ab41b0…6b1b5` e UVM `9b9936…9c4d0` sono le stesse build strumentate precedenti. Le tre letture prima/dopo driver e dopo prova riportano D1 `04008077`, D7:F0/F2 `0e009077`; i dump binari precedenti al driver confermano gli stessi valori. Questo audit non attesta il successivo completamento del backup integrale o della pulizia ESP.

Le quattro catene BAR1→DMA→RM→UVM hanno 68 controlli specifici coerenti; ulteriori 78 controlli di completamento RM/UVM sono positivi. Il nonce dell’allocazione, il suo intervallo begin/end nel log kernel e il VA esatto collegano ogni catena al buffer corretto, senza ricorrere all’inferenza temporale del vecchio programma.

| Buffer condiviso | Proprietario → richiedente | VA GPU | BAR1 + offset = fisico/DMA/PTE decodificata |
|---|---|---|---|
| PUSH receive | Ada → A2000 | `734d95600000` | `4000000000 + 400000 = 4000400000` |
| PUSH receive | A2000 → Ada | `402800000` | `4600000000 + 400000 = 4600400000` |
| PULL send | Ada → A2000 | `403000000` | `4000000000 + c00000 = 4000c00000` |
| PULL send | A2000 → Ada | `404000000` | `4600000000 + c00000 = 4600c00000` |

Tutte le pagine peer registrate sono da 2 MiB, con indirizzi allineati, permesso di scrittura e parole PTE RM/UVM uguali; non emerge un errore aritmetico di mapping. Le PTE sono log software, non riletture della MMU hardware. Viene stampata la prima PTE di ciascuna allocazione da 8 MiB: i payload testati di 4 B, 64 KiB e 1 MiB ricadono interamente in quella prima pagina. I 48 controlli del contenuto inizializzato sul proprietario e i 208 controlli dei permessi VMM sono validi.

Nei 294 snapshot PCIe le uniche quattro variazioni sono `PCI_STATUS 0010→2010`: D7:F0 e A2000 nel primo CE PULL Ada→A2000, caso 13 (`result.log` righe 1257–1271); D1 e Ada nel primo CE PULL inverso, caso 19 (righe 1460–1474). Si tratta del bit Received Master Abort; per questi root port il datasheet Intel 710723-003, §5.4 e §12.5.4, descrive una completion UR dal backbone. Il registro conserva l’errore: la stabilità nei casi successivi non esclude ulteriori UR. Non cambiano AER, header o registri d’errore durante i PUSH; i CES non nulli del bridge ASMedia e dell’A2000 erano già presenti al baseline e non vanno attribuiti ai trasferimenti. La mancanza di variazioni AER non identifica da sola il punto che scarta una scrittura posted.

Il caso 13 è già fallito prima di qualsiasi lettura peer precedente in questa prova: il CE è realmente osservato sull’esecutore destinatario. Non è quindi una semplice ripetizione del vecchio CE eseguito dalla sorgente. Questo non certifica l’intero percorso fisico o esclude ogni eventuale staging interno.

Tutti i 24 confronti precedono `data_done` a 14,090378 s nel clock kernel. Gli 8 free e i 4 `WINDOW_DESTROY_DONE` terminano prima di `context_exit_begin` a 14,094247 s. Il primo avviso dei 4 mapping IOVAS residui arriva a 14,454609 s, 360,362 ms dopo, seguito dagli 8 assert già noti; nessun Xid. Il difetto di cleanup persiste, ma questi eventi successivi non spiegano gli errori dei dati già confrontati. Rispetto alla prova CE precedente i mapping peer passano da 2 a 4, mentre il conteggio residui resta 4 e quello degli assert resta 8.

Le due catene PUSH conservano fisico/DMA e prima PTE identici alla precedente prova con FSP modificato. Il firmware originale non corregge né peggiora l’esito PUSH osservato. Nessun nuovo controllo firmware specifico risulta identificato da questa analisi; restano non osservati il TLP effettivamente emesso, il suo instradamento nel fabric e il punto esatto di rifiuto.

Evidenze riproducibili: `independent-mapping-pci-lifetime-review-firmware.json`, generato da `../audit_pushpull_mapping.py`; fonti primarie locali in `../../p2p-tcss-bit-tests-20261021/reference/next-investigation/intel-710723-003.txt`. Confronto precedente: `../../p2p-tcss-bit-tests-20261021/native-ce-gpu-results/independent-mapping-lifetime-review-storico.json`.
