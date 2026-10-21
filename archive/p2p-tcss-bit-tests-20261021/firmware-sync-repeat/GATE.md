> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Ripetizione sincronizzata: gate Sync v4

Questa cartella prepara soltanto i controlli e riusa il candidato combinato già verificato. Non genera un altro firmware e non effettua accessi remoti, installazione ESP o scritture hardware.

L'intervallo resta `0x01B0B000`, lunghezza `0x1E000` (122.880 byte, 30 settori). Lo stato di partenza è il firmware originale, dopo il ripristino già verificato: **CURRENT.bin e ORIGINAL.bin sono identici**.

| File | CRC32 IEEE | SHA256 |
|---|---|---|
| ORIGINAL.bin | 4A14C7B5 | b81e705a87c89a668c4bbddd3538a82ccd5ebea4b156ce2d79762147310deba9 |
| CURRENT.bin | 4A14C7B5 | b81e705a87c89a668c4bbddd3538a82ccd5ebea4b156ce2d79762147310deba9 |
| CANDIDATE.bin | 549D8326 | c37f53eec3a5702d4a3e7b9d55bf382050100e324f2ec1210d9b98439cabedf4 |

PRE verifica il readback `region-before.bin` contro CURRENT/originale; POST verifica `region-after.bin` contro CANDIDATE; RESTORE verifica `region-restored.bin` contro ORIGINAL. Ogni confronto copre tutti i byte e verifica le dimensioni esatte. I tre file di riferimento devono avere CRC coerenti con il profilo compilato.

Il percorso atteso è `\EFI\CaskLogicTcssSyncTest\`. Il coordinatore prepara i pacchetti e assicura la freschezza dei dump: eliminazione del readback precedente, successo di FPT, successo del gate e marker corrente prima del passo seguente. Nessuno di questi passaggi viene eseguito dagli script di collaudo locale.

La guardia nativa PRE è identica alla versione D1 v3: CPU GenuineIntel 906A3 senza hypervisor, MSR13A `1000000000`, rifiuto esplicito di Verified Boot bit6, TXT DIDVID `1B00C8086` e policy/bootstatus/ACM zero. Il significato del bit36 resta non interpretato. Non contiene scritture MSR, PCI, SPI o variabili EFI.

`build_region_gates.py` è la copia dello script di compilazione già usato, pronta per l'esecuzione del coordinatore nella VM: produce RegionPre/RegionPost/RegionRestore dalla cartella in cui è collocato. Il gate sorgente include il profilo dalla stessa cartella.

Il collaudo host è adattato alla nuova uguaglianza CURRENT=ORIGINAL. PRE accetta l'originale e rifiuta il candidato; POST rifiuta originale/current; RESTORE rifiuta il candidato. I controlli coprono anche errori CRC di ogni riferimento, ultimo byte errato, file mancanti, dimensioni errate, letture parziali, errori I/O e marker non cancellabile. Il risultato effettivo è registrato in `TcssRegionGate.validation.json`; il PRE host non esegue istruzioni privilegiate e non sostituisce la verifica nativa.
