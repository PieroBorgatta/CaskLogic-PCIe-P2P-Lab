> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Porta interna D1:F0: analisi della policy P2P, BIOS 1.26

Il bit 26 rimasto a uno in `00:01.0:D0 = 04008077` corrisponde a una scelta esplicita del firmware per questa famiglia di porte. La voce BIOS P2P è già collegata correttamente al codice che scrive questo registro. Non è emersa una seconda voce BIOS per abilitare separatamente le letture peer.

Questa analisi è statica e locale. Nessuna scrittura hardware, nuovo firmware o test GPU è stato prodotto da questa verifica. Il risultato delle prove VM dopo la precedente modifica D7 è stato comunicato dall'operatore: D7 bits 25–27 azzerati, stesso esito numerico (una operazione valida su quattro).

## Catena completa nel firmware reale

1. `SiliconPolicyPeiPostMem.te`, routine RVA `6466`, legge la variabile UTF-16 `SaSetup`, GUID `72c5e28c-7783-43a1-8767-fad73fccafa4`. Il buffer è nello stack finale `ESP+90`: la `lea [esp+A8]` a `65F5` avviene con 24 byte di argomenti precedenti ancora sullo stack; `6618` elimina entrambi i gruppi di 24 byte.
2. Il medesimo modulo ottiene il blocco GUID `9749a5fb-9130-44f0-8f61-dbff8ef2cac7` a `652A..6536`, salvandone il puntatore in `[esp+54]`. Lo ricarica in ESI a `6B74`.
3. Nel ciclo delle porte, `6C8B` legge `[esp+edi+472]`, cioè `SaSetup[3E2+indice]`; `6C93..6C9D` copia il bit zero del valore nel bit 4 di `blocco + 2C + indice*1F0`.
4. `SiInitFsp.pe`, routine `10371`, ottiene lo stesso GUID (dati a `36EA0`) e salva il puntatore globale a `3CE80`. A `10C9F` chiama l'inizializzazione per porta `F438`.
5. `F479..F48C` ricava la configurazione della porta: `blocco + 1C + indice*1F0`. A `F61B` verifica il bit 4 di `configPorta+10`: è esattamente il campo scritto dal modulo policy.
6. Il helper `6AC0` associa senza condizioni l'indice 1 a device 1, function 0 (`6AE3..6AE6` → `6B0E`). `6B28` ne costruisce l'indirizzo PCI. Il helper `6B54` restituisce 1 per l'indice 1 (`6B73`). Per indice 0 restituisce 0 ed è associato a D6:F0; per indice 2 dipende dal tipo CPU.
7. `F64B` aggiunge `D0` all'indirizzo e `F658` chiama `168E5`, che applica la maschera AND e poi OR al DWORD. La destinazione per l'indice 1 è quindi `D1:F0:D0`.

## Maschere esatte

| Policy | AND | OR | Effetto sui bit 25–27 |
|---|---|---|---|
| P2P disabilitato | FE7FEF88 | 0E000077 | imposta tutti e tre |
| P2P abilitato, helper=0 (D6:F0) | F07FEF88 | 00000077 | azzera tutti e tre |
| P2P abilitato, helper=1 (D1:F0) | F47FEF88 | 00000077 | azzera 25 e 27, conserva 26 |

Il ramo abilitato calcola la maschera a `F623..F635`: chiama `6B54`, converte il risultato in zero oppure FFFFFFFF, applica AND `04000000`, aggiunge `F07FEF88`. Con l'ingresso storico `0E008077`, il calcolo D1 produce precisamente `04008077`. Il codice **conserva** il bit 26: non ne dimostra l'origine al reset né il punto di eventuale blocco hardware.

La verifica confronta i due moduli con gli estratti del dump SPI nativo corrente precedente al flash D7. Sono identici ai moduli analizzati. Nel candidato D7 già predisposto cambia soltanto il byte `20304`; tutta la routine D1 qui descritta rimane identica.

## Significato e limiti

Il sorgente primario Intel distribuito in Slim Bootloader per Alder Lake espone `EnablePeerMemoryWrite` nella configurazione delle porte; il commento parla espressamente di scritture peer. Non espone una proprietà corrispondente per letture peer nella struttura consultata. Questo è coerente con il ramo trovato nel binario, ma non equivale a una specifica del registro D1: [PcieConfig.h, Alder Lake](https://github.com/slimbootloader/slimbootloader/blob/master/Silicon/AlderlakePkg/Include/PcieConfig.h).

La pagina pubblica Intel CCFG del documento 767625 è collocata sotto **D6:F0**. Lì il bit 26 è chiamato UMRPD e disabilita le letture memory peer originate dal lato downstream della porta. La gerarchia D1 non espone la stessa definizione: non si può trasferire automaticamente il nome del bit a D1 o D7. La ricerca primaria parallela è archiviata in `../reference/peer-decode/`.

Anche assumendo la semantica UMRPD condivisa, il bit 26 di D1 potrebbe spiegare una lettura originata dalla Ada interna. Non spiegherebbe da solo né la scrittura Ada→A2000 né la lettura originata dalla A2000. Perciò l'azzeramento di questo singolo bit non è una soluzione completa dimostrata alle tre operazioni fallite.

## Punto d'intervento identificato, non applicato

Nel ramo attuale esiste un punto preciso per richiedere l'azzeramento anche del bit 26 prima della normale scrittura iniziale CCFG: l'immediato dell'istruzione `81 E1 00 00 00 04` a `F62F`. Modificare il solo byte `F634` da `04` a `00` farebbe produrre `F07FEF88` anche al ramo helper=1. Questa è una descrizione del comportamento del codice, **non una patch preparata o una previsione di successo**.

La modifica avrebbe effetto soltanto con la policy P2P abilitata, ma non sarebbe rigidamente limitata a D1:F0: comprende anche D1:F1 sui tipi CPU in cui l'indice 2 appartiene alla stessa famiglia. Non è dimostrato che il bit sia scrivibile in quel momento, che il silicio supporti il percorso peer o che gli altri fallimenti dipendano dallo stesso controllo. La policy standard esposta dal firmware conserva deliberatamente il bit; manca il motivo documentato di quella distinzione.

Le evidenze e le asserzioni riproducibili sono in `D1-evidence.json` e `verify_d1_chain.py` nella stessa cartella.
