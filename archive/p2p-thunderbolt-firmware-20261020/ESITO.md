> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# P2P Ada 2000 ↔ A2000: ricerca del controllo Thunderbolt

Data: 21 ottobre 2026. Sistema: Minisforum MS-01, i9-12900H, BIOS AHWSA 1.26; RTX 2000 Ada interna e RTX A2000 sul percorso Thunderbolt/ASMedia. Vincoli ricevuti: nessuno scambio delle schede, nessuno switch comune, nessun nuovo test o soluzione alternativa tramite RAM.

## Esito effettivo

È stato individuato il codice del firmware installato che inizializza la porta Thunderbolt interessata, compreso il suo accesso privato ai registri. **Non è stato individuato un controllo di abilitazione P2P la cui funzione e scrivibilità siano dimostrate per quella porta. Il P2P non è stato sbloccato.**

La distinzione è essenziale: conoscere l'indirizzo di un registro non dimostra che i bit sospetti siano un interruttore P2P implementato e modificabile. Non è dimostrato nemmeno il contrario, cioè che il silicio renda definitivamente impossibile il percorso.

Questa fase ha utilizzato analisi dei file, documentazione primaria e sole letture del server. Nessun carico GPU, benchmark, scrittura di registro, flash, riavvio o caricamento di driver. L'ultima lettura hardware riportata è delle 00:04:11 del 21 ottobre, ora italiana.

## Punto firmware identificato

La porta fisica è `0000:00:07.0`, Intel `8086:466e`. Non è il root dello slot interno `00:01.0`.

Il modulo `SiInitFsp`, GUID `80a845ac-210f-43b0-995b-477be41ab4e8`, è presente byte per byte nel backup SPI reale. Il relativo FFS di 154.845 byte si trova all'offset fisico `0x1B02B60`; SHA-256 `fcde1a912de75df1a95fdd9553d141712dd49e7bcc89dbb603839535d4a64abf`. Gli indirizzi seguenti sono RVA del modulo estratto, non offset a cui scrivere nella flash.

| Elemento | Riscontro |
|---|---|
| Mappatura delle porte iTBT | Tabella RVA `0x3A6C0`: struttura segmento/bus/device/funzione/abilitazione; device 7, funzioni 0–3 |
| Configurazione dei root D7 | Funzione RVA `0x20692`; indirizzo ECAM costruito con `(0x38 | funzione) << 12` |
| Accesso ai registri privati | Chiamata `0x20728 → 0x203F5`; PortId `C6/C7/CE/CF`, base REGBAR `0xFB000000` |
| Scrittura del registro D0 via REGBAR | RVA `0x2043D…0x20447`: `old | 0x00008000` |
| Scrittura del registro D0 via ECAM | Chiamata `0x207E8 → 0x1FFDD`; RVA `0x202F1…0x20305`: `(old & 0xFEFFCF88) | 0x00001077` |
| Effetto sui bit 25, 26 e 27 | Entrambe le operazioni li preservano; non leggono una policy peer per modificarli |

Il percorso privato usa lettura/scrittura MMIO diretta. Nel codice individuato non compare uno sblocco o una verifica di riuscita per quei tre bit. Non è quindi provato che REGBAR consenta di modificarli dove le vecchie scritture ECAM non avevano effetto.

Le letture del server confermano la corrispondenza concreta:

- MCHBAR: `0xFEDC0001`; REGBAR letto a MCHBAR + `0x7110`: `0xFB000001`.
- Porta 0: `0xFBC600D0 = 0x0E009077`, uguale a D7:F0 offset D0.
- Porta 2: `0xFBCE00D0 = 0x0E009077`.
- PortId C7 e CF restituiscono `0xFFFFFFFF`; questo valore non va interpretato come una configurazione peer valida.

Le definizioni pubbliche CCFG relative a D6/DMI non dimostrano il significato degli stessi bit su D7. Le precedenti scritture senza effetto non dimostrano da sole un lock rimovibile nel BIOS: sono compatibili anche con campi non implementati, riservati o protetti da un altro livello.

## Controlli presenti che non risolvono questo problema

Il `P2P Support` già modificato nella variabile SaSetup, offset `0x3E3`, appartiene alla porta CPU dello slot interno. La separazione dei root CPU e TBT è confermata dalle tabelle [coreboot Alder Lake](https://github.com/coreboot/coreboot/blob/main/src/soc/intel/alderlake/pcie_rp.c).

Le policy pubbliche [Intel FSP Alder Lake-P](https://github.com/intel/FSP/blob/master/AlderLakeFspBinPkg/IoT/AlderLakeP/Include/FspsUpd.h) comprendono abilitazione delle porte iTBT, tunneling PCIe su USB4 e modalità del gestore delle connessioni. Non dichiarano una policy peer D7. Il tunnel esistente rende già visibile l'A2000: abilitarlo non equivale a consentire transazioni fra le due GPU.

Nel [driver Linux Thunderbolt](https://github.com/torvalds/linux/blob/master/drivers/thunderbolt/switch.c), il comando di abilitazione dell'adattatore PCIe agisce nello spazio USB4. Non configura il peer decode del root Intel D7. La ricerca nei sorgenti pubblici non ha trovato una patch di `thunderbolt.ko` che svolga quest'ultima funzione.

Il payload interno TCSS Thunderbolt `TBTP/tbt`, estratto dal backup SPI, è identico nei BIOS ufficiali 1.26 e 1.27: 262.144 byte, SHA-256 `b50d0f9fb732564cf8920349eba9795c06634e4f959254515962288ec77dd6c3`. Sono identici anche SiInitFsp, SiInitPreMemFsp, ITbtDxe e Usb4CmDxe nelle due immagini. Alcuni moduli di policy cambiano: non si sostiene che i due BIOS siano integralmente uguali. Non emerge però una nuova implementazione del percorso peer dai componenti confrontati.

## Adattamento del driver

Il punto preciso che rifiuta le letture BAR1 su questa piattaforma è `_p2pCapsGetHostSystemStatusOverPcieBar1`, in `p2p_caps.c` del driver NVIDIA 595.99.02. Per root distinti ammette alcune famiglie CPU, fra cui Ryzen e Xeon Sapphire Rapids; il Core dell'MS-01 non rientra nelle condizioni accettate.

Forzare la capability o rimuovere i quattro controlli Ada/Ampere in libcuda non programma il root Thunderbolt. Le prove già archiviate avevano mostrato proprio questo limite: capability dichiarata disponibile e dati errati. Non sono state ripetute.

Se viene identificato un controllo hardware effettivo, l'adattamento va circoscritto a quel percorso configurato, con mapping BAR1 dinamico corretto. Il prototipo locale contiene inoltre difetti di durata dei mapping, gestione dei lock, controlli dei limiti e percorsi UVM incompleti; include esperimenti con indirizzi BAR fisici fissi che non devono entrare nel driver finale. Questi difetti sono documentati in `driver-analysis/ANALISI-DRIVER.md`; non sono dichiarati causa provata del blocco iniziale.

## Dato ancora necessario per una modifica motivata

Manca una descrizione o implementazione verificabile del controllo peer del root **Alder Lake-P D7 / 8086:466e**: significato dei campi, eventuale protezione, percorso di scrittura e momento dell'inizializzazione in cui applicarlo. I sorgenti pubblici esaminati e il codice ricostruito non forniscono questa parte.

Cambiare ora i bit 25–27 attraverso REGBAR o sostituire la maschera nel BIOS sarebbe una modifica esplorativa di bit non identificati. Non viene presentata come correzione e non è stata eseguita, coerentemente con il vincolo di non fare altri test.

## Reperti

- `firmware-analysis/tcss-d7-static.json` e `TCSS-D7-evidence-disassembly.txt`: chiamate, maschere, tabelle e codice.
- `letture-registro-host.json`: sole letture effettuate sul server.
- `modules/installed-module-verification.json`: corrispondenza dei moduli con il backup SPI e limiti del confronto diretto.
- `modules/compare-1.27.json`: confronto degli eseguibili delle due immagini vendor.
- `tcss-payload/manifest.json`: posizione, dimensione e hash dei payload TCSS estratti.
- `reference/tcss_public_source_findings.json`: ricerca primaria nei sorgenti pubblici con provenienza.
- `driver-analysis/ANALISI-DRIVER.md`: punti di intervento e difetti del prototipo.

L'esito rimane **non risolto**, con il percorso firmware identificato molto più precisamente e senza attribuire a una capability software il significato di P2P funzionante.
