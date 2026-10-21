> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Candidato combinato D7 + D1, sola preparazione locale

Il file CANDIDATE.bin aggiunge esclusivamente il cambio F634 04→00 al candidato D7 già in prova. Il confronto delle estrazioni contiene 2.999 oggetti per immagine: soltanto due byte del PE SiInitFsp differiscono dall’originale (F634 e20304); un solo byte rispetto allo stato D7-only. Nessun altro modulo cambia.

Intervallo SPI: **01B0B000–01B29000**, lunghezza **0001E000** (122.880 byte, 30 settori da4KiB). Include tutta la precedente area di19settori. La FFS originale resta nello stesso offset e conserva lunghezza154845byte e header.

| File | Significato | SHA256 | CRC32 |
|---|---|---|---|
| ORIGINAL.bin | FSP originale, ripristino finale | b81e705a87c89a668c4bbddd3538a82ccd5ebea4b156ce2d79762147310deba9 | 4A14C7B5 |
| CURRENT.bin | D7-only, confronto obbligatorio prima della scrittura | 9ed07429f558302804219c07af3c357afbc46f20127abf65a4cdc24284a9b3f2 | C98D61F9 |
| CANDIDATE.bin | D7 e D1bit26, prova combinata | c37f53eec3a5702d4a3e7b9d55bf382050100e324f2ec1210d9b98439cabedf4 | 549D8326 |

CURRENT.bin è ricavato dalla precedente immagine D7-only verificata su base dump SPI nativo cfe6…. Il confronto pre-scrittura deve rileggere **tutto** l’intervallo ampliato e richiederne identità byte per byte; questo preparatore non dichiara un nuovo dump hardware.

ORIGINAL.bin ripristina il codice SiInitFsp non modificato, compreso il ramo D7. La voce SaSetup P2P già attivata è fuori dall’intervallo e resta tale.

I log del lettore indipendente UEFIExtract A75 per originale e combinato sono identici. Il confronto binario dimostra che gli avvisi generici sui padding non hanno comportato modifiche fuori dalla FFS bersaglio.

La verifica locale non prova avvio, accettazione del bit da parte del silicio o correttezza P2P. La modifica D1 agisce nel ramo della famiglia D1 con P2P attivo; può comprendere anche D1:F1 sui tipi CPU pertinenti. Nessuna scrittura remota o hardware è eseguita da prepare_combined.py.

Profilo per gli strumenti: flash-profile.json e TcssRegionProfile.h. Risultato completo: combined-verification.json.
