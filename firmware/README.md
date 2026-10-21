# BIOS sperimentali MS-01 AHWSA 1.26

**Nessuna variante pubblicata risolve il P2P bidirezionale.** Destinazione: ricerca e revisione tecnica sul modello indicato. Questi file non sono aggiornamenti approvati dal produttore né immagini universali per tutti gli MS-01.

## File e stato delle prove

| File | Origine | Stato |
|---|---|---|
| `images/AHWSA.1.26-P2P-MENU-CANDIDATE.bin` | Candidato già creato dal BIOS OEM 1.26, modulo Setup modificato | **Mai flashato.** Due byte del modulo decompresso cambiano il riferimento form `2AE2→27C4`; il contenitore è ricompresso. Non promette che il menu diventi utilizzabile. |
| `images/AHWSA-1.26-PEG-TCSS-D1-D7-EXPERIMENTAL.bin` | Ricostruzione offline: OEM 1.26 + regione FSP combinata già provata | **Immagine completa mai flashata.** Soltanto la regione è stata flashata e riletta nella macchina originale; modifica dei registri riuscita, P2P non risolto. |
| `regions/tcss-d7.bin` | Regione candidata di 77.824 byte, offset OEM `0x1B16000` | Variante D7 effettivamente provata; non risolve. **Non è un BIOS completo.** |
| `regions/peg-tcss-d1-d7.bin` | Regione candidata di 122.880 byte, offset OEM `0x1B0B000` | Variante combinata effettivamente provata; non risolve. **Non è un BIOS completo.** |

[Manifest con hash, offset e differenze](manifest.json). Il numero elevato di byte differenti nel contenitore deriva dalla ricompressione: non equivale al numero di istruzioni modificate. La modifica per il menu e quella FSP sono **candidati separati**, non cumulati.

## Provenienza e privacy

La preimmagine è il file OEM `AHWSA.1.26.bin`, 33.554.432 byte, SHA-256:

`223d9966ef2fd75b11eb0400fa6f988806d534a8b48632aafead7345a43968af`

Le due regioni ORIGINAL dei trial coincidono esattamente con le rispettive porzioni dell'immagine OEM. L'immagine completa PEG/TCSS pubblicata conserva **ogni byte OEM fuori dalla regione FSP**. Non deriva dal dump SPI personale e non contiene le variabili private del server. Il candidato menu ha la stessa preimmagine OEM; l'audit storico dei moduli identifica una sola foglia PE modificata.

- [Analisi del menu](../archive/gpu-followup-20261020/firmware-mod/menu-patch-analysis.json)
- [Confronto semantico dei moduli](../archive/gpu-followup-20261020/firmware-mod/semantic-module-comparison.json)
- [Catena firmware/registri](../archive/p2p-next-investigation-20261021/firmware-review.md)
- [Storico dei trial e del ripristino](../archive/p2p-tcss-bit-tests-20261021/STORICO-PROVE.md)

## Ricostruzione locale, senza flash

Procurarsi dal produttore la **stessa preimmagine esatta** e confrontarne l'hash. Lo script rifiuta immagini differenti e non sovrascrive file esistenti.

```bash
python3 tools/rebuild_fsp_image.py /percorso/AHWSA.1.26.bin /percorso/output.bin
```

Scrive soltanto un normale file su disco; non accede alla memoria SPI. Il risultato deve coincidere con l'hash dell'immagine PEG/TCSS nel manifest. Non aggiorna automaticamente checksum o policy di altre versioni: il suo ambito è esclusivamente questa preimmagine verificata.

## Prima di un eventuale uso hardware

Un'immagine completa OEM può sovrascrivere impostazioni e identificativi del proprio dispositivo. Non usare il dump o il backup di un'altra macchina come proprio ripristino. Identificare esattamente scheda/revisione, predisporre backup verificato del proprio SPI e un recupero hardware indipendente dal sistema operativo. Il solo accesso SSH non recupera un computer che non si avvia.

Non sono inclusi utility proprietarie FPT, script di flash automatico o dump NVRAM personali. Il materiale rende le modifiche ispezionabili e ricostruibili; non certifica una procedura di installazione sicura su macchine altrui. Le licenze del firmware OEM rimangono applicabili.
