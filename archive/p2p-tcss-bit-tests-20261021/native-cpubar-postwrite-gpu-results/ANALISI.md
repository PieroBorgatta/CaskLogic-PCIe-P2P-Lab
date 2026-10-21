> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Esito della rilettura CPU dopo le scritture P2P

La CPU vede il dato nuovo sulla Ada interna e ancora zero sulla A2000 esterna.
La verifica successiva sulla GPU destinataria concorda con la CPU in entrambe
le direzioni. Il P2P resta con tre confronti falliti su quattro: non è risolto.

| Scrittura | Destinazione letta dalla CPU | Atteso | Letto CPU | Verifica D2H destinatario |
|---|---|---|---|---|
| A2000 → Ada | Ada, finestra 1, `0x4000400000` | `a5a42468` | `a5a42468` | PASS |
| Ada → A2000 | A2000, finestra 3, `0x4600600000` | `a5a42468` | `00000000` | FAIL, dato zero |

Riepilogo diagnostico: un PASS, un FAIL, zero SKIP. Prima delle operazioni peer,
entrambi i controlli CPU a due pattern erano validi; tutti i dieci controlli
locali del proprietario erano validi. Le due letture peer rimangono errate.
Il processo ha completato i confronti (`TOTAL_FAILURES 3`, `NATIVE_TEST_RC=5`,
`SCRIPT_RC=5`, `PROBE_COMPLETED`).

## Cosa è stato verificato

Il binario nell'immagine di avvio corrisponde al manifest e al sorgente
revisionato: la nuova osservazione è dopo `cudaDeviceSynchronize` della GPU
che scrive, prima del cambio al proprietario e prima della copia D2H.
Non reinizializza la parola e non esegue scritture CPU nella BAR. Il controllo
usa la stessa allocazione della scrittura peer, mantenuta viva fino al termine
completo dei confronti.

Le quattro catene nonce → GPUVA → handle → descrittore → finestra BAR1 → DMA →
RM PTE → UVM PTE → completamento sono coerenti. Le finestre sono allineate a
2 MiB; gli indirizzi fisico, DMA e decodificato coincidono. Sono stati
ricontrollati UUID/BDF, proprietà della finestra, ordine e tempi dei marker.
La diagnosi CPU non ha usato indirizzi inventati né log di una prova precedente.

| Finestra | GPU proprietaria | GPUVA | Fisico/DMA | Handle |
|---|---|---|---|---|
| 1 | Ada | `0x73e1af400000` | `0x4000400000` | `caf0013c` |
| 2 | A2000 | `0x73e1af600000` | `0x4600400000` | `caf0013d` |
| 3 | A2000 | `0x73e1af800000` | `0x4600600000` | `caf0013f` |
| 4 | Ada | `0x73e1afa00000` | `0x4000600000` | `caf00142` |

La prova è nativa su Linux 7.0.0-38, driver 595.99.02, IOMMU dichiarata disabilitata
anche dal log kernel. `RM64KBBAR1Mappings=0` è conservato. D1 CCFG `00008077` e
D7 F0/F2 `00009077` sono verificati prima del driver, dopo il driver e dopo il
collaudo. La A2000 è tornata con BAR1 alta `0x4600000000`: questa prova non esegue
il helper di ricollocazione low-MMIO.

## PCIe e tempi

Tutte le 126 fotografie PCIe, in 21 gruppi da sei dispositivi, hanno letture
complete da 4096 byte senza errori. Le uniche variazioni osservate sono:

- dopo la lettura della Ada da A2000: PCI_STATUS `0010→2010` su D7 `00:07.0`
  e A2000 `06:00.0`;
- dopo la lettura della A2000 da Ada: lo stesso cambiamento su D1 `00:01.0`
  e Ada `01:00.0`.

Il bit aggiunto è Received Master Abort. AER, header e altri campi registrati
restano invariati; nessun nuovo cambiamento coincide con le riletture CPU o
le scritture peer. Questo non significa che il percorso PCIe sia privo di
errori: RMA è presente ed è persistente fino alla cancellazione, qui non eseguita.

La lettura CPU della Ada avviene fra `13.603938720` e `13.605422218` secondi monotonic, prima della verifica D2H.

La lettura CPU della A2000 avviene fra `13.659442631` e `13.660921018` secondi monotonic, prima della verifica D2H.

I dati sono completati a `13.665924953` secondi monotonic,
prima di tutti i rilasci. I 41 marker del processo sono presenti anche nel
kernel. Il primo avviso di cleanup IOVAS è a `13.941087`
secondi kernel, 268.437 ms dopo
il marker di uscita dal contesto; seguono otto assert. Non sono registrati Xid.
Gli errori di cleanup sono reali, ma compaiono dopo tutti i confronti.

## Interpretazione e limiti

Non emerge la divergenza «CPU vede il dato nuovo, D2H del proprietario vede il
vecchio». Una spiegazione limitata alla sola verifica D2H del proprietario
non è sufficiente per questa osservazione: anche la lettura CPU della A2000
restituisce zero. Rimangono da distinguere mancata consegna, completamento,
attributi e interpretazione hardware del mapping; questa prova non localizza
il componente che impedisce la visibilità della scrittura.

La lettura CPU aggiunge tempo e una transazione PCIe. Le catene registrate sono
software: non sono un readback delle tabelle PTE hardware né una cattura TLP.
Il controllo riguarda quattro byte della finestra, non ogni byte della VRAM.
La collocazione temporale degli assert non certifica da sola che tutte le
operazioni del driver precedenti fossero corrette.

## Integrità delle evidenze

Tutti i 17 file acquisiti corrispondono ai checksum. Sono stati verificati
anche i tre file del pacchetto, sorgente e header, e sono stati ricalcolati
in streaming gli hash dei file effettivamente contenuti nell'initramfs:
moduli RM/UVM caricati, programma, libcuda e init corrispondono al manifest.
Il campo di build `hardware_boot_started=false` è metadato precedente al boot;
i log completi documentano l'esecuzione effettiva.

- `result.log`: `be2870e928878769e266f55ccba5d176daadc2e1b423ae962ce00e833514788c`
- `kernel.log`: `4d4edaa53080bfce1c64c0fe89b40b69773233d05eaf646a8a93f2d7930fc281`
- initramfs: `fd6c2c61ee59cf62e56a5212b5a64c3184f43a6d261c1bcc5ba09a4d5ff2f335`
- programma nel pacchetto: `603bea3c28a83bfa8d06dd13e358c43885ba9e4534f8bcd7e4e0250250ec1aea`
- sorgente CUDA: `c05a9ccd05dfc3488457c0bcf9c2eba8736406a0c6ff1011c020bafa09990006`

Dettagli, hash completi, righe e tempi sono in `verified-result.json`.
`analyze_cpubar_postwrite.py` riproduce la verifica locale senza accedere a
hardware o rete. Nessuna nuova prova GPU è stata eseguita da questo revisore.
