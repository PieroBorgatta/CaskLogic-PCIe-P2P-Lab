> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Prova nativa di sole scritture peer

**Esito verificato: 15/15 copie A2000→Ada corrette; 15/15 Ada→A2000 fallite.** Il primo trasferimento da4byte fallisce già prima di qualsiasi lettura peer: una precedente lettura remota fallita non è quindi una causa necessaria del problema di scrittura.

| Payload | Ada→A2000 | A2000→Ada |
|---|---:|---:|
| 4byte | 0/3 corretti | 3/3 corretti |
| 4KiB | 0/3 | 3/3 |
| 64KiB | 0/3 | 3/3 |
| 1MiB | 0/3 | 3/3 |
| 8MiB | 0/3 | 3/3 |

Il kernel legge il buffer locale dell'esecutore e scrive quello del peer, con `__threadfence_system` e sincronizzazione dell'esecutore. Tutti i60 controlli dell'intero payload sui proprietari, prima delle copie, passano. Quattro buffer separati da8MiB restano vivi fino alla fine dei30confronti. Tutte le parole dei15payload falliti differiscono dall'atteso; la prima parola stampata di ciascuno coincide con il poison iniziale. I log non contengono tutte le parole osservate, quindi non si afferma che l'intero payload sia rimasto identico al poison.

Identità confermate: GPU0 RTX2000Ada, `01:00.0`, UUID`2cad53ce…fb3c5`; GPU1 RTX A2000, `06:00.0`, UUID`9734a8d9…65dbb`. Avvio nativo kernel7.0.0-38, IOMMU disabilitato; D1CCFG=`00008077` e D7F0/F2CCFG=`00009077` prima/dopo driver e dopo test. Impostazione `RM64KBBAR1Mappings=0` presente.

Le quattro catene BAR1→DMA→PTE RM→PTE UVM coincidono; indirizzi allineati a2MiB, permesso di scrittura presente. Le destinazioni effettive sono la finestra Ada ID2, BAR1+`0xC00000`, e A2000 ID4, BAR1+`0xC00000`. Il logger espone la prima PTE di ciascun gruppo da4: non è una lettura delle page table hardware.

Nessuna variazione dei registri PCIe/AER nei sei dispositivi osservati prima/dopo; nessun nuovo RMA. Gli indicatori già presenti nei bridge restano identici. L'assenza di errori segnalati non dimostra che le scritture postate siano arrivate.

Tutte le quattro finestre risultano distrutte dopo `data_done`. I quattro mapping residui compaiono nella IOVAS`0x600`, 385,88ms dopo `context_exit_begin`, seguiti da8assert suGPU0; nessun Xid. Negli avvii precedenti la IOVAS residua era`0x100`: il difetto di cleanup resta separato dai confronti dati e dipende plausibilmente dall'ordine di chiusura, ancora da identificare per descrittore.

Controllati gli hash di tutti i17file raccolti, il sorgente e l'header rispetto al manifest, gli ordini di sincronizzazione e confronto, tutte le30combinazioni, le60inizializzazioni e le12fotografie PCIe. Gli hash dei moduli e del binario di prova sono riportati dal manifest; i binari non sono presenti qui per un nuovo calcolo indipendente. Dati e limiti in [verified-result.json](verified-result.json), evidenze primarie [result.log](result.log) e kernel.log *(artefatto locale non pubblicato)*.

Il percorso bidirezionale non è risolto. Per distinguere scrittura scartata e visibilità della destinazione, un controllo successivo può rileggere via CPU la stessa parola BAR1 subito dopo la scrittura peer, prima di reinizializzarla. Le durate dei casi falliti non misurano banda utile.
