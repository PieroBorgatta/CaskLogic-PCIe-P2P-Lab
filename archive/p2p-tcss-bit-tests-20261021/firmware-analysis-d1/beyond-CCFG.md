> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Analisi locale oltre CCFG: D1, D7 e destinazione BAR1

Analisi statica del 21 ottobre 2026. Nessun accesso al server e nessuna modifica hardware. Il modulo esaminato è `SiInitFsp.pe` originale SHA256 `de17fb9ae71e0cb04fa39102ed1895284640befb719b44ea45b498e29b0c928f`; il disassemblato è in `../../p2p-review-20261020/SiInitFsp-disassembly.txt`.

## Risultato circoscritto

Non è stato identificato un ulteriore interruttore P2P documentato e applicabile con certezza a D7:F0. Le scritture iniziali del controller esistono e sono localizzate, ma attribuire ai bit non pubblici un significato peer sarebbe una supposizione. In particolare, il bit 28 di CCFG resta preservato dalle routine D1 e D7 verificate: la definizione UFDM pubblica per D6 non certifica la stessa semantica D1/D7.

Le finestre prefetch pubbliche **D7** supportano indirizzi a 64 bit. Un eventuale limite alle transazioni peer sopra 4 GB dovrebbe quindi appartenere a un percorso di instradamento diverso dal normale decode della finestra. Al momento non è dimostrato.

## Scritture realmente localizzate nel FSP

Il loop D7 inizia a RVA `0x20692`, ricava il numero funzione da PCI D0:F0+7C, costruisce il BDF `(0x38 | function) << 12`, usa la tabella Port-ID `0x3BB24` e chiama le routine sottostanti. L'associazione D7:F0→REGBAR C6 è stata anche verificata mediante letture hardware eseguite dal coordinatore; non deriva soltanto dal nome del modulo.

| Registro D7 | Operazione provata | Punto nel PE |
|---|---|---|
| F0 | `(old & FFFFF8FF) | 00000700` | `202CD–202E8` |
| D4 | `old | 00001042` | `2030E–2031D` |
| D8 | `(old & FFFC7F8F) | 08220048` | `20322–20336` |
| D0 via ECAM | `(old & FEFFCF88) | 00001077` prima della patch già provata | `202F1–20305` |
| D0 via REGBAR | `old | 00008000` | `2043D–20447` |
| BA4, FPB capabilities | `(old & F8F8F8FF) | 00010207` | `2018C–201A0` |

Le prime tre operazioni non sono qui rinominate come controlli peer: manca una definizione primaria pubblica esatta per D7. La routine sideband `203F5` imposta inoltre 478, 318, E1, E2, F7, 324, 320, 64, 400/404, F5, 204 e 338; le altre due routine `20346` e `205CC` impostano 300, 304, EC, 6CC, 594, C54, E8, 420, 424, 428, 5F0, 5F4, 5BC, 5C0. La sola presenza di queste scritture non dimostra una funzione peer.

Per D1, il ramo già identificato a `F61B–F658` è controllato da `EnablePeerMemoryWrite`; non contiene un secondo selettore read. La programmazione F0 a `F5C3–F603` usa per D1 `AND FFFFF88F / OR 770`, contro `AND FFFFF8FF / OR 700` di D7. Anche qui non è stata trovata una semantica pubblica specifica che giustifichi una modifica.

### FPB

La documentazione Intel 710723-003, sezione 12.5, attribuisce a D7 il blocco FPB BA0–BC0. BA4 bit2 dichiara la capacità MEM High; BB4 bit0 abilita quel decode, BB4[7:4] ne seleziona la granularità e BB4[31:28]/BB8[31:0] formano l'indirizzo iniziale. BBC/BC0 permettono di accedere ai vettori.

Il FSP scrive l'header BA0 a `2007D–2008A` e le capacità BA4 sopra riportate. Nella scansione delle immediate del disassemblato `SiInitFsp` non compaiono BB0, BB4, BB8, BBC o BC0. Questo è un risultato di ricerca limitato: non esclude accessi indiretti, firmware premem, altro modulo o sistema operativo. **Supporto dichiarato non equivale ad abilitazione e non equivale a consenso P2P.** Non si propone di attivare FPB senza ricostruire le finestre effettive e i vettori.

## Prove già eseguite e indirizzi fisici

`native-d1-gpu-results/result.log`, righe 71–77, registra l'A2000 nativa dopo autorizzazione del tunnel:

- BAR1: `0x4600000000–0x460FFFFFFF`, 256 MiB;
- BAR3: `0x4610000000–0x4611FFFFFF`, 32 MiB;
- BAR0: `0x60000000–0x60FFFFFF`, 16 MiB.

Le stesse destinazioni sono presenti in `native-gpu-results` e nel primo `gpu-followup-20261020/baremetal-probe`. Il kernel iniziale vedeva un'apertura A2000 di 8 GiB, ma dopo ricreazione del tunnel la assegna a 256 MiB mantenendo la stessa base alta. Ridurre la dimensione non ha significato collocarla sotto 4 GB.

Il vecchio `p2p-driver/xen_alias.py` aggiungeva soltanto traduzioni GPA→HPA tramite Xen: GPA `0x780000000` e `0x7C0000000` (30 e 31 GiB) verso HPA `0x4000000000` e `0x4600000000`. Questi alias non erano neppure GPA sotto 4 GB e non modificavano le BAR fisiche. Non è stata trovata una prova nativa già eseguita con BAR1 A2000 fisicamente sotto 4 GB.

## Finestre e condizioni per un confronto futuro

Il log nativo `native-d1-gpu-results/kernel.log` mostra la finestra root MMIO bassa `0x50400000–0xBFFFFFFF` e alta `0x4000000000–0x7FFFFFFFFF`. Mostra anche allocazioni già presenti; non è una mappa completa degli intervalli disponibili.

Il percorso A2000 è D7:F0 → 04:00.0 → 05:00.0 → 06:00.0. Le finestre prefetch ASM dopo la ricreazione del tunnel sono `0x4600000000–0x4611FFFFFF`; D7 conserva una prenotazione più ampia `0x4600000000–0x4801FFFFFF`. Le finestre nonprefetch sono distinte e contengono BAR0, ROM/audio e margine hotplug.

Per confrontare realmente il decode alto/basso servono prima `/proc/iomem`, tutte le risorse PCI/ACPI e gli header configurazione correnti, acquisiti nello stesso avvio nativo dopo autorizzazione del tunnel e prima del driver. La BAR1 da 256 MiB richiede allineamento coerente con la sua dimensione. Occorre considerare anche BAR3 da 32 MiB: abbassare soltanto BAR1 mantenendo BAR3 alta e un'unica finestra prefetch aperta fra le due attraverserebbe intervalli di altri dispositivi, inclusa Ada, e invaliderebbe l'esperimento. Non viene scelto alcun indirizzo basso in assenza della mappa completa.

Il confronto avrebbe valore discriminante soltanto se: BAR fisiche e tutte le finestre della catena sono rilette e coerenti; Linux vede le risorse aggiornate; il driver genera PTE dirette alla nuova BAR1; gli stessi dati sono verificati prima e dopo con owner sincronizzato. Un miglioramento dimostrerebbe una dipendenza dall'indirizzo o dal routing, non da solo quale bit Intel la causi. L'esito invariato non dimostrerebbe a sua volta l'assenza di ogni limite hardware.

## Fonti primarie

- [Intel 710723-003, datasheet volume 2](https://cdrdv2-public.intel.com/710723/710723-003.pdf), D7 sezione 12.5; testo locale in `reference/next-investigation/intel-710723-003.txt`.
- [Intel D7 PMBL, offset24](https://edc.intel.com/content/www/de/de/design/publications/12th-generation-core-processors-datasheet-volume-2-of-2/prefetchable-memory-base-and-limit-pmbl-offset-24_2/): indicatori 64bit RO=1; confronto indirizzi31:20.
- [Intel D7 PMBU32, offset28](https://edc.intel.com/content/www/de/de/design/publications/12th-generation-core-processors-datasheet-volume-2-of-2/prefetchable-memory-base-upper-32-bits-pmbu32-offset-28_2/) e [PMLU32, offset2C](https://edc.intel.com/content/www/de/de/design/publications/12th-generation-core-processors-datasheet-volume-2-of-2/prefetchable-memory-limit-upper-32-bits-pmlu32-offset-2c_2/): porzioni superiori32bit RW. Copie HTML/testo conservate in `reference/d7-pmbl.*`, `d7-pmbu32.*`, `d7-pmlu32.*`.

Questi dati documentano il decode standard. Non documentano un filtro peer a32bit né autorizzano a trasferire UFDM da D6 a D7.

## Integrazione: snapshot dom0 acquisito successivamente

La raccolta del coordinatore `decode-snapshot-20261021/snapshot.json`, `iomem.txt` e `firmware_memmap` permette ora un primo controllo completo delle risorse dom0. `analyze_snapshot.py` produce `decode-analysis.json` soltanto da file locali.

- D7:F0 e F2: BA0=`00000015`, BA4=`00010207`, BA8/BAC/BB0/BB4/BB8/BBC/BC0 tutti zero. Le tre capacità FPB sono dichiarate ma i tre meccanismi RID/MEMlow/MEMhigh sono disabilitati. La lettura BC0 riguarda un solo DWORD selezionato e non certifica tutti i vettori; non sono state eseguite scritture al selettore.
- D7:F0 e i due bridge ASM: MSE=1, pref base=`4600000000`, limit=`4801FFFFFF`, coerenti con BAR1 da8GiB e BAR3 della configurazione dom0. Non è emersa una finestra errata.
- La regione bassa libera osservata più grande è `6EB01000–BFFFFFFF`. Il calcolo include tutti gli occupanti PCI, iomem e firmware_memmap. Vi entra un insieme BAR1 da256MiB+BAR3 da32MiB, ma il sizing corrente dom0 da8GiB non vi entra.

Il candidato separato `low-mmio-trial/` valida nuovamente il layout nell'avvio nativo con BAR1 da256MiB. Non trasferisce automaticamente questa conclusione da dom0 al nativo; al momento della redazione è solo codice locale, senza compilazione né esecuzione.
