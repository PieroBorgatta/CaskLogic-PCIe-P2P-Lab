> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Lacune che possono cambiare la diagnosi P2P

## Aggiornamento: lacune ora collaudate

L’avvio nativo del 21 ottobre, rientrato alle 03:46:53 CEST, ha eseguito i 24 confronti sul FSP ripristinato: D1 `04008077`, D7:F0/F2 `0e009077`, invariati prima e dopo. I risultati verificati sono 18 fallimenti: PUSH Ada→A2000 6/6 falliti, PUSH A2000→Ada 6/6 riusciti, PULL in entrambi i versi 12/12 falliti. CUPTI registra 12 operazioni CE e 12 SM; proprietari sincronizzati e confrontati, mapping e identità verificati. Il primo PULL è CE sulla A2000 e precede qualsiasi lettura peer SM. Queste due lacune sperimentali sono quindi chiuse con esito negativo.

Il PUSH corretto sul firmware ripristinato riproduce l’asimmetria vista con i bit FSP modificati: non è necessario tenere attive quelle modifiche per riprodurla. Questo confronto non prova quale componente scarti o alteri le transazioni. Nei PULL il primo valore è `ffffffff`; il log conta tutti i mismatch ma non stampa tutte le parole, perciò non consente di attribuire quel valore all’intero payload.

Evidenze: [analisi numerica e CUPTI](native-pushpull-results/ANALISI.md), [catene PTE, PCI e vita delle allocazioni](native-pushpull-results/independent-mapping-pci-lifetime-review-firmware.json), [risultato verificato](native-pushpull-results/verified-result.json). Il testo seguente conserva l’analisi **precedente** che ha motivato questo test, non descrive più prove mancanti.

21 ottobre 2026. Revisione indipendente delle sole copie locali, dopo il ripristino FSP delle 03:19 CEST. Nessun accesso remoto o nuovo test GPU. Questo documento circoscrive ciò che manca: non annulla i confronti numerici già raccolti.

## 1. Manca una baseline nativa con protocollo corretto sul FSP ripristinato

**Lacuna confermata.** Tutti i risultati nativi successivi all'introduzione di sincronizzazione esplicita e readback del proprietario riportano D1=00008077 e D7:F0/F2=00009077: sync, instrumented2, regalign, cpubar, push, lowmmio, postwrite, UVM4KiB, CPU-RW, NoSnoop, SYS_COH e CE. Nessuna matrice corretta in questa raccolta usa la coppia FSP originale D1=04008077 / D7=0E009077. Dopo il ripristino finale sono presenti controlli di stato, non nuovi confronti CUDA.

Esiste un nativo precedente con FSP originale, quindi non è corretto dire «mai provato senza patch firmware»: `gpu-followup-20261020/baremetal-probe/result.log`, due prove da 4 byte con driver diagnostic/coherent, entrambe 3/4 errate. La scrittura CCFG runtime è ignorata e le riletture restano 04008077/0E009077. Ma il programma preesistente non ha il successivo sync/readback sul proprietario, non impone l'allineamento BAR1 tramite RM64KBBAR1Mappings=0 e non registra la catena PTE completa. La seconda prova cambia inoltre driver, ACS e NoSnoop/RO insieme.

Il nativo `native-gpu-results` usa già D7 modificato, anche se D1 è ancora 04008077; `native-d1-gpu-results` usa il combinato e ritarda i free, ma non ha ancora i due sync owner. Il successivo `native-sync-gpu-results/result.log:123` contiene il primo OWNER_CHECK esplicito; nello stesso log, alle righe101–103, i registri sono già quelli combinati.

**Implicazione:** il confronto firmware originale/modificato è confuso con le revisioni del programma e del mapping. Le vecchie prove rendono poco plausibile che la sola patch abbia creato da zero l'asimmetria; non dimostrano però che la patch sia neutra usando il protocollo attuale. Un nativo corretto sul FSP già ripristinato chiude una lacuna reale senza richiedere un altro flash. «Originale» qui significa FSP prima degli esperimenti, con la precedente impostazione SaSetup conservata: non BIOS di fabbrica integrale.

## 2. CE avviato dal destinatario: storico esistente, ma nessuna prova nativa corretta e osservata

**Il pull non è completamente inedito.** `gpu-followup-20261020/p2p-driver/peer_ce_small.cu:21–26` esegue per ogni verso sia caller=destination sia caller=source. Nel corrispondente `ce-small-events.json`, il container termina RC5 e registra:

| Source | Destination | Caller | Primo valore osservato | Esito |
|---|---|---|---|---|
| 0 | 1 | 1, destinatario | ffffffff, atteso00003039 | FAIL |
| 0 | 1 | 0, sorgente | 00000000, atteso00003039 | FAIL |
| 1 | 0 | 0, destinatario | ffffffff, atteso00003039 | FAIL |
| 1 | 0 | 1, sorgente | tutti corretti | PASS |

Dimensione65536byte. Limiti concreti: eseguito nella VM con `compiled-diagnostic`, senza CUPTI, senza controllo dell'identità/context del motore effettivo, senza readback owner o sync esplicito del sorgente dopo H2D e prima del cambio device, senza logging/allineamento PTE verificati. Il confronto interrompe al primo mismatch e non conta tutte le parole corrotte. Il vecchio log non stampa una mappatura CUDAindex→UUID: la tabella conserva deliberatamente gli indici, senza promuoverli da soli a identità fisiche.

L'ultimo nativo CE, programma7184d44d…fa4d, **avvia tutti i dodici casi sulla sorgente**: `native-ce-probe/peer_ce_cupti.cu:188–198` seleziona source, verifica contesto/stream source e chiama cuMemcpyDtoDAsync sullo stream source. `native-ce-gpu-results/result.log` contiene dodici CE_EXECUTOR concordi con s, e il manifest/audit confermano il binario effettivo. È quindi prova forte del PUSH, non del PULL nativo corretto.

**Non basta cambiare device o stream nel programma esistente:** i send buffer sono volutamente accessibili solo dal proprietario; l'altro device ha permission NONE. Un pull così modificato sarebbe invalido per costruzione. La nuova variante deve autorizzare lettura remota della sorgente sul destinatario, destinazione locale scrivibile, sync/readback di entrambi i proprietari e verifica CUPTI sul contesto/stream dell'esecutore effettivo. Non va assunto che il device sorgente dei dati coincida con l'esecutore.

## 3. Lettura SM da 4 byte non equivale a bulk CE pull verificato

Il kernel SM legge e applica XOR0x12345678. Il risultato edcba987 riportato nei log corrisponde a una parola remota ffffffff, non al pattern atteso00003039. È coerente con il primo valore ffffffff dei vecchi pull CE, ma non è una misura del contenuto di ogni parola di un trasferimento bulk. Nei nativi corretti si osservano anche PCI_STATUS0010→2010 sul lettore e sul relativo root; questo indizio va nuovamente correlato se si prova un pull CE in un contesto pulito.

I dodici casi CE recenti non contengono letture peer esplicite e non mostrano alcun cambiamento nei150 snapshot PCI. Il CE pull nativo potrebbe riprodurre i RMA delle letture SM, riuscire oppure fallire diversamente: nessuno dei tre esiti è già dimostrato dai log recenti.

## Prova minima che aggiunge informazione

Un singolo avvio nativo sul FSP **già ripristinato**, senza nuove scritture PCI o firmware, può confrontare prima PUSH e poi PULL, con allocazioni separate e permessi che ammettano un solo esecutore per ruolo. Sono necessari lo stesso RM/UVM baseline strumentato, RM64KBBAR1Mappings=0, owner sync/readback completo, tre taglie, entrambe le direzioni, identità/context/stream verificati e attività CUPTI correlata. In questo modo il primo blocco PUSH colma la baseline mancante e il secondo verifica il nuovo esecutore. Non si dovrebbe chiamare il PULL «una nuova soluzione» prima del confronto integrale dei dati, né una cattura CUPTI prova assoluta del percorso fisico.

Il coordinatore ha nel frattempo richiesto un candidato di24confronti (12PUSH seguiti da12PULL,8buffer separati); alla redazione di questa nota è preparazione, **non un test eseguito**.

## Evidenze locali principali

- [Sorgente CE storico](../gpu-followup-20261020/p2p-driver/peer_ce_small.cu)
- [Esecuzione CE storica](../gpu-followup-20261020/p2p-driver/ce-small-events.json)
- [Primo nativo, FSP originale](../gpu-followup-20261020/baremetal-probe/result.log)
- [Prima sorgente con sync/readback owner](../p2p-tcss-bit-tests-20261021/native-sync-probe/peer_vmm_word_sync.cu)
- [Risultato sync e CCFG combinati](../p2p-tcss-bit-tests-20261021/native-sync-gpu-results/result.log)
- [CE nativo: sorgente e executor](../p2p-tcss-bit-tests-20261021/native-ce-probe/peer_ce_cupti.cu)
- [CE nativo: dati, permessi e mapping verificati](../p2p-tcss-bit-tests-20261021/native-ce-gpu-results/independent-mapping-lifetime-review-storico.json)
- [Ripristino originale, seguito solo da controllo di stato](../p2p-tcss-bit-tests-20261021/final-sync-independent-review-storico.json)
