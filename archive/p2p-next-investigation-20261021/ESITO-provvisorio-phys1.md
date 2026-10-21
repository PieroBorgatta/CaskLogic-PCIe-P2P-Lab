> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# CaskLogic — approfondimento P2P RTX 2000 Ada / RTX A2000

Stato al 21 ottobre 2026: **non risolto; indagine ancora in corso**. MS-01 i9-12900H, Ada interna, A2000 esterna tramite ASM2464/USB4. Schede e topologia conservate. Nessuna pubblicazione GitHub o messaggio esterno: la condizione richiesta dall’utente è una soluzione verificata.

## Risultati precedenti confermati

Il [rapporto precedente](../p2p-tcss-bit-tests-20261021/ESITO.md) conserva firmware, varianti del driver e risultati numerici. I bit CCFG D7 25–27 e D1 26 sono stati modificati realmente nel FSP e riletti, senza risolvere Ada→A2000. Lo span FSP sperimentale è stato poi ripristinato e confrontato byte per byte. Allineamento BAR1/PTE corretto, pagine UVM4KiB, aperture SYS_COH, NoSnoop/Relaxed Ordering, BAR sotto4GiB e prove native senza Xen non hanno eliminato l’asimmetria. Le prove sincronizzate trovano scritture A2000→Ada corrette e Ada→A2000 errate; le letture peer falliscono in entrambe le direzioni.

La nuova [analisi firmware](firmware-review.md) ricostruisce SaSetup[3E3]→EnablePeerMemoryWrite→FSP→D1+D0: conduce al controllo già sperimentato. Non identifica una nuova abilitazione PEG→TCSS. I moduli FSP/ITbtDxe/Usb4CmDxe dei BIOS1.26/1.27 confrontati sono identici; alcuni wrapper differiscono per la dimensione del buffer Setup. Non è stato completato il confronto semantico di ogni funzione OEM e non si sostiene che ogni possibile controllo sia stato escluso.

## Nuove prove sul firmware ripristinato

| Prova | Riscontro | Limite |
|---|---|---|
| PUSH/PULL nativo, 24 confronti SM/CE | PUSH Ada→A2000:6/6 errati; PUSH inverso:6/6 corretti; PULL:12/12 errati. | Non è una cattura TLP. |
| CE osservato con CUPTI nella stessa prova |12CE+12SM, traccia completa, zero record persi;48controlli iniziali delle allocazioni corretti. Il primo PULL è CE prima di qualsiasi PULL SM. | L’evento CE non dimostra da solo la consegna remota. |
| Traffico NVML1, quattro PUSH da1MiB | Due direzioni forward errate, due reverse corrette. | Baseline200ms insufficiente:0/4finestre qualificate. Conservato, non usato come misura qualificata. |
| Traffico NVML2, baseline2s | Stessi risultati dati;4/4finestre qualificate,624campioni,48statistiche ricalcolate. | Contatori aggregati, non pacchetti né banda del payload utile. |
| Primo prototipo CE fisico privilegiato | Driver caricato e parametri verificati; interruzione nella validazione della memoria, prima di qualsiasi confronto o submissionCE. | Non è un esito negativo del percorso fisico. |

Dati grezzi e analisi: PUSH/PULL *(artefatto locale non pubblicato)*, Traffic1 *(artefatto locale non pubblicato)*, Traffic2 *(artefatto locale non pubblicato)*, [primo prototipo fisico](native-physical-ce-results/root-outcome.json). Tutti questi avvii sono stati raccolti integralmente e rimossi dall’ESP dopo verifica dei backup; gli originali di avvio sono stati ricontrollati.

Nel Traffic2 Ada→A2000, TX Ada cresce da circa400KB/s dichiarati dall’API a circa1,14–1,57milioni, mentre RX A2000 rimane circa292–299. Nella direzione inversa crescono sia TX A2000 sia RX Ada. Questo restringe le ipotesi, ma **non localizza ancora il punto di perdita**: occorre prima verificare che RX A2000 risponda a un trasferimento positivo noto. Le calibrazioni proprietario↔host previste servono a quel controllo, non costituiscono un trasferimento P2P fra GPU e non sono una soluzione tramite RAM CPU.

## Driver fisico sperimentale

Il nuovo ioctl privilegia una copia di soli4byte su allocazioni VMM già vive. Ricava gli indirizzi dal gestore NVIDIA, verifica CPU, GPU, proprietà, permessi, intervalli, BAR1 e durata dei riferimenti; non accetta indirizzi fisici dall’utente. Usa un canale CE privilegiato con sorgente LOCAL_FB e destinazione NONCOHERENT_SYSMEM, senza ripiegare sul percorso virtuale. Il confronto finale legge il dato dalla GPU proprietaria. Se il completamento è incerto, i riferimenti restano vivi fino al riavvio automatico.

Il primo avvio ha fermato la validazione con NV_ERR_INVALID_STATE prima delle copie. I PTE delle sei mappe mostrano KIND6, GENERIC_MEMORY; il prototipo accettava soltanto KIND0. La correzione è in preparazione e aggiunge diagnostica dei singoli controlli. Le fonti NVIDIA distinguono Generic Memory, non compresso e non swizzled, dai formati compressi o block-linear. Nessun risultato della versione corretta è ancora disponibile.

La prima compilazione aveva inoltre segnalato un azzeramento oltre il confine di un campo secondo FORTIFY: quella versione non è mai stata caricata. La versione effettivamente usata impiega assegnazioni esplicite dei13campi di risposta e ha compilato senza avvisi sul codiceC. ABI, gestione dei riferimenti, installer, raccolta e ritorno automatico sono stati controllati separatamente.

## Cosa si può concludere

Il P2P richiesto non è abilitato. Una segnalazione positiva delle API, la presenza di dueGPU o il completamento di un comando non bastano: serve corrispondenza dei dati in entrambe le direzioni. Non c’è ancora una patch risolutiva da installare o presentare come soluzione.

Resta plausibile una limitazione nella consegna fra PEG e TCSS, oppure nel modo in cui il requester/driver emette l’operazione. Il punto preciso non è dimostrato. La [documentazione Linux](https://www.kernel.org/doc/html/latest/driver-api/pci/p2pdma.html) spiega che l’inoltro fra domini di gerarchia PCIe non è definito dalla specifica generale; non dimostra l’impossibilità specifica di questo MS-01. I [contatori NVML](https://docs.nvidia.com/deploy/nvml-api/latest/api/group__nvmlDeviceQueries.html) non sostituiscono una traccia delle transazioni.

Nessuna nuova scrittura SPI è stata effettuata in questo approfondimento. Le prove temporanee montano soltanto l’ESP per salvare i risultati; i dischi delle VM restano smontati. Corpus, checkpoint e codice del training non sono stati modificati. Non è stata eseguita una verifica integrale per hash di tutti i dati del server. Windows resta sospesa con stato conservato per insufficienza di RAM insieme a Docker; non viene descritta come attiva.
