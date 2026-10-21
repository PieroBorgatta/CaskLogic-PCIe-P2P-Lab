> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Gate D1 v3: tre immagini distinte

Il sorgente è separato dal precedente `firmware-candidate/TcssRegionGate.c`, rimasto invariato. Questa variante usa il profilo generato dopo la verifica dei tre blocchi da parte dell'audit firmware.

Intervallo SPI: **`0x01B0B000`, lunghezza `0x1E000` = 122.880 byte = 30 settori**. Il gate non accede alla SPI e non esegue FPT: verifica file già acquisiti, usando gli stessi valori del profilo. Il coordinatore deve associare alla lettura/scrittura FPT l'indirizzo e la lunghezza di questo nuovo intervallo.

| File di riferimento | Significato | CRC32 IEEE |
| --- | --- | --- |
| `ORIGINAL.bin` | FSP originale, prima delle due modifiche | `4A14C7B5` |
| `CURRENT.bin` | Stato intermedio con la sola modifica D7 già applicata | `C98D61F9` |
| `CANDIDATE.bin` | Modifiche D7 e D1 combinate | `549D8326` |

Tutte le modalità richiedono tutti e tre i riferimenti con lunghezza e CRC esatti. Il readback viene poi confrontato integralmente, byte per byte:

| Modalità di compilazione | Readback | Riferimento da uguagliare | Marker |
| --- | --- | --- | --- |
| Default PRE | `region-before.bin` | **CURRENT.bin** | `READY.flag` |
| `-DPOST_CHECK` | `region-after.bin` | CANDIDATE.bin | `VERIFIED.flag` |
| `-DRESTORE_CHECK` | `region-restored.bin` | **ORIGINAL.bin** | `RESTORED.flag` |

La scelta è intenzionale: il controllo prima della seconda modifica richiede lo stato intermedio realmente previsto; il ripristino verifica invece il ritorno del FSP alla versione originale, annullando entrambe le modifiche entro l'intervallo. Non viene richiesto che CURRENT coincida con ORIGINAL e non si accetta ORIGINAL come baseline del PRE.

Tutti i percorsi ESP sono sotto `\EFI\CaskLogicTcssD1Test\`. I nomi dei log restano `region-pre-gate.txt`, `region-post-gate.txt` e `region-restore-gate.txt`. La guardia nativa PRE conserva esattamente la logica v2: CPUID `906A3` GenuineIntel senza hypervisor, MSR `1000000000`, rifiuto esplicito del bit 6, DIDVID `1B00C8086` e ACM policy/bootstatus/status zero. Nessuna scrittura MSR/PCI/SPI o variabile EFI. Le fonti e i limiti dell'interpretazione sono nel precedente `firmware-candidate/bootguard-review.md`.

Il programma elimina i marker precedenti come nella variante v2; un errore di cancellazione interrompe l'esecuzione. Il coordinatore deve controllare il codice di uscita oltre alla presenza del marker. Deve inoltre eliminare il vecchio readback prima di ogni dump e verificarne il successo: la validazione dei contenuti non dimostra da sola la freschezza di un file identico.

Le tre modalità compilano freestanding x86_64 con header GNU-EFI e `-Wall -Wextra -Werror`. Il collaudo host comprende **43 casi passati**: 15 PRE, 14 POST, 14 RESTORE. Il PRE esercita direttamente la stessa funzione di validazione file usata dall'applicazione, senza invocare la guardia MSR/MMIO sul computer di analisi. In particolare, CURRENT corretto passa; ORIGINAL e CANDIDATE come readback PRE vengono rifiutati. POST e RESTORE rifiutano il readback CURRENT. Sono inclusi CRC errati per ciascun riferimento, file mancanti, letture parziali, dimensioni errate, errore all'ultimo byte, errori I/O e marker non cancellabile.

`TcssRegionGate.validation.json` conserva hash, dimensioni, CRC e risultati dei collaudi. SHA256 sorgente: `3899971657667fa2be3e9c7c93294c70c3d273d30e2c53cd68b9738743a730af`. SHA256 header: `6683455c94f6f96c63871d9474a8a8509c38ebc856ca130ebdd758613a0a3e6c`.

Nessuna build o prova su server è stata eseguita da questo sottocompito; la qualificazione numerica P2P e l'avviabilità del candidato restano riscontri separati del coordinatore.
