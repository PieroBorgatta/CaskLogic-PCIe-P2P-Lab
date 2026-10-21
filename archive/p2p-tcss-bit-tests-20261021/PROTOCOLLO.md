> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Sonda temporanea CCFG D7:F0

Lo script è destinato esclusivamente al controller `8086:466e`, con baseline `0x0e009077`, CPU i9-12900H, MCHBAR `0xfedc0001` e REGBAR `0xfb000001`. La porta fisica C6 deve essere mappata alla funzione 0. Non modifica altre porte, firmware, driver, ACS o registri di lock.

L'operatore verifica prima che le GPU non eseguano lavori. La sonda non avvia carichi GPU. Senza `--execute` esegue soltanto letture e salva il rapporto.

Compilare sulla VM Ubuntu x86-64 il solo helper, senza dipendenze libc:

```sh
gcc -shared -fPIC -nostdlib -ffreestanding -fno-stack-protector -O2 -Wall -Wextra -Werror -o regbar_mmio.so regbar_mmio.c
```

Copiare sull'host lo script, il sorgente C e la libreria. Usare una directory nuova per ogni esecuzione; lo script rifiuta di sovrascrivere risultati:

```sh
python3 regbar_probe.py --expected-id 8086:466e --expected-value 0x0e009077 --mmio-helper ./regbar_mmio.so --output /percorso/nuovo-rapporto --execute
```

Il protocollo applicato è:

1. Ricava MCHBAR dal PCI host bridge e REGBAR da MCHBAR+0x7110. Controlla indirizzi, identità PCI, presenza della porta e mapping della funzione. Ricava l'ECAM dalla tabella ACPI MCFG e ne verifica identità e baseline.
2. Salva `snapshot.json` con `fsync` del file e della directory prima della prima scrittura. Include gli spazi PCI iniziali, indirizzi, valori e hash del programma nativo. Eventuali letture dei registri di lock restano separate dalla sonda.
3. Per ciascun caso azzera temporaneamente un solo bit fra 25, 26 e 27; quarto caso azzera tutti e tre. Una singola istruzione C di accesso `volatile uint32_t` effettua ogni scrittura allineata. Nessun `pwrite`, `memcpy`, operazione atomica o prefisso LOCK.
4. Legge subito REGBAR, ECAM e PCI sysfs; ripete dopo 50 ms. `--hold-seconds` consente di cambiare l'attesa da 0 a 300 secondi.
5. Qualunque variazione fuori dalla mask del singolo caso o discordanza fra i tre percorsi interrompe la sequenza. Il blocco `finally` ripristina prima la parola originale, quindi salva le osservazioni. Il ripristino è controllato subito e dopo 5 ms.
6. SIGINT, SIGTERM e SIGHUP attivano il ripristino. Durante il ripristino altri segnali vengono registrati senza interromperlo. Un ripristino non confermato termina con codice 2 e nessun caso successivo.

`events.jsonl` viene sincronizzato dopo ogni evento. `result.json` è prodotto soltanto se tutti i casi sono conclusi e il registro finale coincide con l'originale. I dati distinguono bit modificabili, scritture ignorate e anomalie; una modifica riuscita dei bit non dimostra ancora il funzionamento P2P delle GPU.

Compatibilità: Python 3.6.8 e Linux x86-64. L'helper precompilato evita la necessità di un compilatore sull'host XCP-ng. La sonda non può garantire ripristino dopo interruzioni hardware, kernel panic o SIGKILL; per i segnali gestibili il ripristino è parte obbligatoria del programma.
