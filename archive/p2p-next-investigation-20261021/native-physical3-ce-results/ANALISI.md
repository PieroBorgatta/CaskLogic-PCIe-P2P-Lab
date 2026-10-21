> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# PHYS3 — CE fisico con destinazione coerente

21 ottobre 2026, rientro XCP-ng confermato alle 03:21:05 UTC. **Prova completa, P2P bidirezionale non risolto.** Il protocollo e i log kernel sono stati verificati dal coordinatore riutilizzando il revisore della prova PHYS2, con il controllo esplicito destinazione mode1. Non si dichiara una nuova revisione indipendente da un altro agente.

| Sorgente → destinazione | SM, 4 byte | CE fisico, 4 byte |
|---|---|---|
| RTX 2000 Ada → RTX A2000 | FAIL | FAIL |
| RTX A2000 → RTX 2000 Ada | PASS | PASS |

Entrambi i CE riportano ritorno ioctl 0, stato RM 0, flag `0x77`, classe `C7B5` e LAUNCH `04003186`. Gli operandi sono fisici, source LOCAL_FB=0 e destination COHERENT_SYSMEM=1; nessun fallback virtuale. Le query ReadWrite, proprietà delle allocazioni, range BAR1 e indirizzi sono coerenti con i metodi registrati. Indirizzi sorgente `0x0a000000` / `0x09c00000`, destinazione `0x4600400000` / `0x4000400000`. Le finestre erano già vive prima della copia e vengono distrutte dopo i confronti.

I quattro controlli separati H2D/D2H da 1 MiB passano, con quattro finestre qualificate e sensibilità positiva dei contatori interessati. RX A2000 durante H2D passa da media 289,96 a 3.121.173,5 kB/s nelle unità dell’API. Questo valida il controllo host; non è una misura di banda P2P né una cattura TLP.

Il programma termina con quattro confronti, due fallimenti, due copie fisiche completate e RC5. I 102 snapshot PCI non mostrano variazioni, CCFG rimane originale e non compaiono Xid. Otto assert IOVAS iniziano 372,277 ms dopo il marcatore di uscita dal contesto, dopo i confronti e la distruzione delle finestre.

Kernel, driver e programma provati sono identificati nel manifest. Il modulo UVM ha SHA-256 `06f64631e9c725eff49301ecd2a1a051c504bfa3145dbacb4247484d36d375e9`; il programma `b5f9b159f1b061e476cb1419c1dd07b2bcb56a0daa83cfd304f55e744cf2a1b5`. Rispetto a PHYS2, la sola variazione funzionale del driver è il modo fisico destinazione 2→1. Questo confronto non cambia topologia, firmware o driver RM.

Log risultati SHA-256 `6c468cfd15e2c510a7c9653583b7331070c9857b05daf2303e8c360940f5e966`; log kernel `1fbb0bb8217b066c234697aa0f490752c4536221159961b1dbc98427635bed94`. [Risultato strutturato](verified-result.json), [protocollo verificato](verified-protocol-root.json), [catena kernel e registri](verified-kernel-root.json).

Il backup integrale ESP e i 17 risultati grezzi sono verificati per hash sul Mac e sull’host. La pulizia dell’avvio temporaneo è conclusa. Nessuna nuova scrittura SPI e nessuna installazione permanente del driver. Il percorso fisico coerente conserva lo stesso fallimento del percorso noncoerente; non costituisce una soluzione da pubblicare.
