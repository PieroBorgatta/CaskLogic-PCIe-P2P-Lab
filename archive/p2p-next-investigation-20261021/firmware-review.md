> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Nuova verifica firmware PEG D1 → TCSS D7

**Aggiornamento operativo:** i confronti sul FSP ripristinato, inclusi PUSH/PULL e CE fisici in entrambe le modalità, sono ora conclusi con P2P non risolto. La ricostruzione firmware seguente resta valida; i riferimenti a prove ancora da svolgere sono storici. [Esito attuale](ESITO.md).

21 ottobre 2026. Analisi locale e fonti primarie; nessun accesso al server, nuova scrittura PCI, flash o collaudo GPU da parte del revisore.

**Non è emerso un nuovo controllo firmware PEG→TCSS con destinazione, significato e applicabilità dimostrati sul 12900H/CPUID 906A3.** È stata invece ricostruita una parte ulteriore della catena della policy peer già sperimentata, ed è stato ristretto il significato delle differenze BIOS 1.26→1.27. Questi risultati non autorizzano a chiamare “abilitazione P2P” una nuova modifica di bit riservati e non dimostrano un'impossibilità assoluta.

Lo stato sperimentale di riferimento è [ESITO.md](../p2p-tcss-bit-tests-20261021/ESITO.md), dopo SYS_COH e CE. La sola direzione di scrittura finora verificata è A2000→Ada. Il FSP originale è stato ripristinato e riletto. La [revisione delle lacune](gaps-review.md) distingue un punto essenziale: le prove native con il protocollo corretto erano state eseguite sul FSP combinato, mentre quelle precedenti sul FSP originale non possedevano tutti i controlli attuali. Il nuovo confronto PUSH/PULL sul FSP ripristinato era ancora preparazione alla redazione di questa nota; qui non se ne anticipa l'esito.

## Policy peer: la catena ora è più precisa

Nel `SiliconPolicyPeiPostMem` 1.26, la lettura della variabile UTF-16 `SaSetup` avviene a RVA 65F5–6618, con dimensione 578h. Tenendo conto dei 18h byte di argomenti ancora sullo stack alla costruzione del puntatore, il buffer corrisponde a `esp+90h` dopo la pulizia. Il successivo RVA 6C8B legge `esp+edi+472h`: dunque il byte di configurazione è `SaSetup[3E2h+indice_porta]`. Il codice lo sposta nel bit 4 del DWORD `config+1Ch+indice*1F0h+10h`.

Per la porta D1:F0 l'indice è 1: il byte risulta proprio **SaSetup[3E3h]**, già impostato nella fase precedente. Il mapping non è una supposizione ricavata dal nome: `SiInitFsp` 6AC0–6B53 mappa l'indice 1 in device 1, function 0 e costruisce la base PCI; il ramo 6B54 restituisce il tipo 1. Il sorgente pubblico Intel `GetCpuPcieRpDevFun` coincide con questa mappatura. [Implementazione Intel in EDK II](https://github.com/tianocore/edk2-platforms/blob/master/Silicon/Intel/AlderlakeSiliconPkg/Fru/AdlCpu/CpuPcieRp/Library/PeiDxeSmmCpuPcieInfoFruLib/CpuPcieInfoFruLib.c).

Nel modulo FSP installato, SHA256 `de17fb9ae71e0cb04fa39102ed1895284640befb719b44ea45b498e29b0c928f`, F47F/F485 calcola lo stesso stride/header; F61B verifica il bit 4 a offset 10h della porta, quindi F645–F658 aggiorna PCI+D0. Il layout pubblico è coerente in modo specifico: `CPU_PCIE_ROOT_PORT_CONFIG` ha 12 byte prima del blocco comune, il cui secondo DWORD contiene `EnablePeerMemoryWrite` nel bit 4. L'identificazione della policy è quindi sostenuta sia dai byte OEM sia dal layout Intel, non dal solo testo dell'opzione. [Config CPU Intel](https://github.com/tianocore/edk2-platforms/blob/master/Silicon/Intel/AlderlakeSiliconPkg/Include/ConfigBlock/CpuPcieRp/Gen4/CpuPcieConfig.h), [blocco comune Intel](https://github.com/tianocore/edk2-platforms/blob/master/Silicon/Intel/AlderlakeSiliconPkg/Include/ConfigBlock/PcieRp/PcieConfig.h).

**Conseguenza:** questa opzione conduce al ramo CCFG già provato. Non è una nuova policy per autorizzare PEG→TCSS. Il campo pubblico UPD `CpuPcieRpPeerToPeerMode[4]` resta separatamente non tracciato nel wrapper OEM: la sua esistenza non prova che governi un ulteriore registro, né che sia applicabile a D7. Non vengono trasferiti offset UPD di un'altra build nel BIOS installato.

## BIOS 1.27: differenze effettivamente verificate

L'archivio OEM locale `MS-01-AHWSA-V1.27_4_28_V2.zip` ha SHA256 `cf6710534f1de22f0f94515a0bd91b6d95d78e002a060cbe85dfd788865e57d6`. Il `Release_Note.txt` estratto è stato confrontato byte per byte con quello interno allo ZIP. La versione 1.27, datata 3 aprile 2025, introduce impostazioni di frequenza/potenza, controllo della velocità dello slot PCIe, modifica del comportamento delle Option ROM e aggiornamento GOP; non documenta una correzione peer/TCSS. [Archivio OEM conservato con provenienza](https://pc-file.s3.us-west-1.amazonaws.com/ms-01/Bios/MS-01-AHWSA-V1.27_4_28_V2.zip).

Il confronto dei 14 moduli è stato ricalcolato, senza affidarsi al solo vecchio manifest:

| Moduli | Differenza 1.26→1.27 verificata |
|---|---|
| SiInitFsp, SiInitPreMemFsp, ITbtDxe, Usb4CmDxe, SaInitFsp, SaInitDxeFsp, SiInitDxe, SaInitDxe, SiliconPolicyDxe | Identici byte per byte. |
| Usb4PlatformPei | Un solo byte a offset file 214h: DF→E0, immediata CDFh→CE0h della dimensione del buffer `Setup`. |
| DTbtDxe | Un solo byte a E74h: stessa variazione di dimensione, usata per allocazione e `GetVariable`. |
| UsbTypeCDxe | Un solo byte a 53Bh: stessa variazione nel parametro dimensione di `GetVariable(Setup)`. |
| SiliconPolicyPeiPostMem e SiliconPolicyPeiPreMem | Differenze più estese; non è stato completato un confronto semantico di ogni funzione. Non vengono dichiarati equivalenti. |

Un controllo mirato nel modulo PostMem mostra però che la sequenza che copia la policy peer verso il bit 4 è identica: 22 byte da offset file 6AF3h nella 1.26 corrispondono a 6AFDh nella 1.27, RVA 6C8B→6C95. Anche l'FSP che la consuma è identico. Il payload interno TCSS/TBT era già risultato identico nelle copie OEM e installata nel precedente rapporto. Non è stato identificato un delta 1.27 che abiliti questo percorso; il solo numero di versione più alto non è evidenza di una soluzione.

## Altri candidati controllati

La documentazione D7 distingue controlli ACS, attributi delle richieste proprie del root e finestre di indirizzo. Non è stata trovata una regola documentata che trasformi ENS/ERO, LTR o FPB in un'autorizzazione a ricevere scritture peer da D1. ACS e gli attributi degli endpoint sono già stati controllati nelle prove; le finestre standard sono state verificate anche con BAR fisico sotto 4 GiB. UFDM/bit 28 resta descritto pubblicamente per D6, senza corrispondenza dimostrata a D1/D7. Le occorrenze letterali aggiuntive del bit 28 esaminate nel disassemblato includono PCI+E8, MSR E2 e MMIO FE0018E0; non forniscono una scrittura D7+D0 con semantica peer verificata. Questa ricerca di costanti non viene presentata come prova esaustiva dell'assenza di ogni controllo indiretto.

La revisione Intel 682436-041 del 1 ottobre 2026 è stata ricontrollata. Gli errata PCIe/Type-C pertinenti trovati descrivono atomic TLP errati, uscita da L1.2, errori correggibili di pacchetto, accessi MSI-X qword o condizioni di compliance/display. Non forniscono un workaround specifico per la perdita persistente di scritture PEG→TCSS da 4 byte con collegamento funzionante. [Errata Intel aggiornati](https://edc.intel.com/content/www/us/en/design/ipla/software-development-platforms/client/platforms/alder-lake-desktop/682436/041/errata-details/).

Intel 710723-003 §2.15 limita le scritture peer PEG alle porte PEG ed esclude PEG→DMI. D7 è però identificato separatamente come bridge Thunderbolt integrato: non è stata trovata la premessa che consenta di equipararlo a DMI. La frase è coerente con un limite di instradamento, ma non dimostra da sola dove venga scartata la richiesta. [Datasheet del processore, §§2.2, 2.15 e 12.5](https://cdrdv2-public.intel.com/710723/710723-003.pdf).

## Decisione tecnica

La nuova ipotesi verificabile più circoscritta è già nel candidato operativo: **stesso mapping corretto sul FSP originale, poi CE eseguito dal destinatario con permessi che ammettano un unico executor**, distinto dal PUSH già osservato. È un controllo del percorso e una chiusura della baseline mancante, non una patch firmware proposta come cura.

Se il confronto resta negativo, la ricerca firmware conserva due limiti espliciti: il wrapper OEM non è completamente ricostruito e manca una traccia dei pacchetti/metodi hardware che collochi il blocco. Servirebbe una catena nuova policy→registro D1/D7→semantica→fase di inizializzazione o una traccia che restringa il problema. Le fonti e i byte esaminati non la forniscono ancora. Nessun nuovo candidato SPI è stato prodotto.

Evidenze riproducibili in `reference/`: `firmware-review-evidence.json`, `firmware-peer-policy-evidence.txt`, `bios-126-127-byte-comparison.json`, `bios127-release-note.txt` e i disassemblati TE separati per versione. Gli originali storici restano intatti.
