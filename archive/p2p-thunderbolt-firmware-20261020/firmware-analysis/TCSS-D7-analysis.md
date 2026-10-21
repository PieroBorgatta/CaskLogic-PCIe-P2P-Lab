> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Analisi statica del percorso TCSS/ITBT nel BIOS installato

Data: 21 ottobre 2026. Attività svolta da questo analista: lettura di file locali e fonti pubbliche, disassemblaggio e produzione di evidenze. Nessun accesso SSH, scrittura firmware, modifica driver, avvio GPU o prova funzionale.

## Risultato

È stata identificata la routine che configura davvero le root port Thunderbolt D7:F0–3, inclusi due accessi al registro D0: uno attraverso CPU REGBAR e uno attraverso PCI ECAM. La destinazione è dimostrata dalla costruzione dell'indirizzo e dalle tabelle di mapping del binario. Non è stata identificata una policy P2P specifica per D7 né una scrittura firmware che cambi i bit 25, 26 e 27 di D0. Entrambe le scritture individuate conservano quei bit.

Il percorso REGBAR è un risultato concreto: offre un accesso diverso dall'ECAM usato dalle prove precedenti. Tuttavia l'esistenza di tale accesso non dimostra che quei bit siano modificabili attraverso di esso o che la loro modifica abiliti P2P. Il binario esaminato non contiene, in questo percorso, un tentativo sui bit 25–27, uno sblocco o una verifica successiva della loro modifica. Non è quindi giustificata una patch firmware operativa.

## Identità del firmware

- Modulo: `SiInitFsp.pe`, FFS GUID `80a845ac-210f-43b0-995b-477be41ab4e8`.
- SHA256 PE: `de17fb9ae71e0cb04fa39102ed1895284640befb719b44ea45b498e29b0c928f`.
- Il contenitore FFS compresso completo del BIOS 1.26 è presente byte per byte nel dump SPI `uefi-p2p/spi-backup-a.bin`, offset `0x1B02B60`, lunghezza 154845 byte.
- SHA256 FFS: `fcde1a912de75df1a95fdd9553d141712dd49e7bcc89dbb603839535d4a64abf`.

Questo confronto lega il codice analizzato alla copia del firmware installato. La modifica precedente a SaSetup non modifica questo FFS.

Il confronto separato del coordinatore (`modules/compare-1.27.json`) riporta identità dei moduli SiInitFsp, SiInitPreMemFsp, ITbtDxe e Usb4CmDxe tra BIOS 1.26 e 1.27. Questo non prova identità dell'intero comportamento BIOS, perché alcuni moduli di policy sono diversi.

## Catena di inizializzazione D7

Gli indirizzi seguenti sono RVA del PE. In questa copia RVA e offset dei byte interessati coincidono; non sono indirizzi assoluti della flash.

1. `0x1370 → 0x23F2`: inizializzazione TCSS, policy individuata tramite config block.
2. `0x25B3 → 0x20692`: inizializzazione delle quattro porte ITBT.
3. La routine legge il bitmap di presenza da MCHBAR+`0x7090` e il mapping delle funzioni da PCI `00:00.0+0x7C`.
4. A `0x206F0–0x20704` estrae la funzione a gruppi di tre bit e costruisce `(0x38 | function) << 12`. Poiché `0x38 = 7 << 3`, si tratta di bus 0, device 7, funzione 0–7.
5. `0x20728 → 0x203F5`: configurazione privata attraverso REGBAR, indicizzata dalla porta fisica.
6. `0x207E8 → 0x1FFDD`: configurazione PCI usando la base ECAM D7 costruita al punto 4.

La tabella a `0x3A6C0` contiene quattro record da cinque byte `segment, bus, device, function, enabled`, con device sempre 7. Il mapper `0x1B063` usa la tabella e/o il TCSS HOB GUID `455702CE-4ADB-45D9-8B27-F7B0D9798AE0`; il HOB può rimappare le funzioni. La struttura corrisponde alla definizione Intel pubblicata in [SaRegsItbtPcie.h](https://github.com/slimbootloader/slimbootloader/blob/master/Silicon/TigerlakePkg/Include/Register/SaRegsItbtPcie.h). La fonte Tiger Lake corrobora formato e nomenclatura; la prova D7 su questa macchina viene dal codice Alder Lake installato.

## Le due scritture D0

| Percorso | Punto nel PE | Operazione | Effetto sui bit 25–27 |
|---|---|---|---|
| CPU REGBAR | `0x2043D–0x20447` | `old OR 0x00008000` | Preservati |
| PCI ECAM D7 | `0x202F1–0x20305` | `(old AND 0xFEFFCF88) OR 0x00001077` | Preservati |

La prima modifica il bit 15. La seconda configura bit inferiori e cancella il bit 24. Non leggono alcuna policy peer per determinare il valore dei bit 25–27.

La tabella a `0x3BB24` contiene i Port ID `C6 C7 CE CF`. La formula del codice è:

`0xFB000000 | ((UINT8)PortId << 16) | (UINT16)Offset`

Per D0 produce `0xFBC600D0`, `0xFBC700D0`, `0xFBCE00D0`, `0xFBCF00D0`. La formula coincide con `CPU_REGBAR_ADDRESS` nel sorgente Intel Alder Lake [CpuPcieHsPhyInitLib.c](https://github.com/slimbootloader/slimbootloader/blob/master/Silicon/AlderlakePkg/Library/CpuPcieHsPhyInitLib/CpuPcieHsPhyInitLib.c).

I helper sono completamente ricostruiti:

- `0x67BC`: lettura MMIO 32 bit dell'indirizzo REGBAR.
- `0x68A7`: scrittura MMIO 32 bit; nessuna lettura successiva, nessun codice di stato hardware.
- `0x690D`: lettura, OR, scrittura.
- `0x6983`: lettura, AND, OR, scrittura.
- `0xD3EF`: lettura, AND, OR, scrittura di un byte, con il medesimo mapping Port ID.
- `0x168E5`: equivalente AND/OR attraverso PCI configuration access.

Questi helper non inviano un opcode SBI, non chiedono uno sblocco e non verificano se la scrittura sia stata accettata. Il codice effettua normali accessi MMIO alla finestra CPU REGBAR. Non si può dedurre da esso che REGBAR aggiri automaticamente una protezione del registro.

Il coordinatore ha riferito separatamente letture dal sistema: MCHBAR `0xFEDC0001`, MCHBAR+`0x7110 = 0xFB000001`, D0 su Port ID C6 e CE uguale `0x0E009077`, C7 e CF `0xFFFFFFFF`. Questi dati sono coerenti con la finestra REGBAR e con due porte presenti; la provenienza operativa è nel rapporto del coordinatore, non in una lettura eseguita da questo analista.

Nel seguito la routine imposta anche D8 bit 23 (`0x2081B–0x2082D`) e scrive REGBAR+`0x3E24 = 1`. La funzione di tali campi su D7 non è stata dimostrata da una specifica applicabile: non vengono etichettati arbitrariamente come lock P2P.

## Policy ITBT effettivamente presenti

La tabella nominata a `0x3AB20` lega i nomi a routine reali:

| Nome incorporato | Funzione |
|---|---|
| ITbtSetForcePower | `0x20907` |
| ITbtPcieTunnelingForUsb4 | `0x20EBD` |
| ITbtDmaUuidUpdate | `0x20BDB` |
| ITbtDmaSsidSvidUpdate | `0x20D75` |
| ITbtClearVgaRegisters | `0x20AF3` |
| ITbtSetDmaLtr | `0x20B65` |
| ITbtSetCmMode | `0x20A42` |
| ITbtUnsetForcePower | `0x20F58` |
| Pass_ITbt_Policy_To_Hob | `0x20DE7` |

`ITbtSetCmMode` legge policy+`0x22` e sceglie i comandi mailbox `0x44`/`0x46`; è la selezione del connection manager. `ITbtPcieTunnelingForUsb4` legge policy+`0x21` e opera su D13:F2/F3+`0xE8`, modificando l'abilitazione del tunnel. Nessuna delle due è un controllo peer D7 individuato.

## Limiti tecnici e intervento firmware

Le scritture runtime ignorate su ECAM non distinguono da sole tre possibilità: campo fisso/non implementato, campo protetto o accesso richiesto attraverso un'altra interfaccia. La lettura della stessa parola via REGBAR dimostra l'accessibilità di lettura di quella finestra; non distingue le tre possibilità di scrittura. L'inizializzazione firmware individuata conserva proprio i bit in discussione: non è una prova che siano immutabili, ma nemmeno una prova che esista un interruttore software disabilitato.

È stato disassemblato anche SiInitPreMemFsp (TE, 651504 byte), inclusi riferimenti a D0, maschere e tabella D7. I primi accessi a D0 intorno a RVA `0x1FFB` e `0x21BB` operano su DMIBAR; non possono essere trasferiti a D7. La tabella D7 premem, file offset `0x99040`, viene aggiornata dal HOB durante l'inizializzazione del modulo, ma non è emersa una sequenza di configurazione dei bit 25–27 di D7. La ricerca è statica, senza simboli completi: non esclude valori di reset del silicio, firmware del controller o ulteriori percorsi indiretti. Non è stato identificato chi porta quei tre bit a 1.

Prima di un intervento preciso occorre la semantica **D7 TCSS su Alder Lake-P/H** dei bit 25–27, inclusi tipo d'accesso, eventuale lock e fase di inizializzazione ammessa. Le definizioni CCFG per DMI/PEG o altre generazioni non bastano. Una modifica delle mask in `0x203F5` o `0x1FFDD` senza tale corrispondenza sarebbe un nuovo tentativo, non l'abilitazione dimostrata di una funzione presente. In rispetto del vincolo dell'utente non è stata creata né installata alcuna patch di questo tipo.

Evidenze locali: `tcss-d7-static.json` raccoglie hash, mapping e punti del codice; `TCSS-D7-evidence-disassembly.txt` conserva i blocchi disassemblati pertinenti. Il vecchio callsite PCH `0x2A4AC → 0x26ECD` rimane escluso dal percorso ITBT.
