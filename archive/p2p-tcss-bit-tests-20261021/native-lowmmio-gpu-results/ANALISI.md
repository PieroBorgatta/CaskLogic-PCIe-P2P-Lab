> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Prova nativa con BAR A2000 sotto 4 GiB

La riallocazione è riuscita ed è stata conservata durante la prova: il P2P mantiene però gli stessi tre fallimenti su quattro. Questo esperimento esclude che il solo indirizzo BAR1 sopra 4 GiB fosse sufficiente a spiegare il difetto osservato; non identifica ancora il blocco finale nel percorso GPU→GPU.

Ho ricalcolato i 54 SHA256 elencati in `collected-sha256.json`: corrispondono tutti. L'analisi usa i dump config PCI binari da 4096 byte, le risorse kernel e i log raccolti; non si basa soltanto sul codice di uscita del wrapper. `state.json` e il campo `hardware_boot_started=false` del manifesto descrivono la preparazione: l'esecuzione è provata dai log successivi, non da quei campi.

## Riallocazione effettiva

Il kernel nativo è 7.0.0-38-generic, CPU 906a3 senza hypervisor, IOMMU disabilitata. La prova mantiene le due patch FSP combinate: D1 CCFG=00008077, D7:F0/F2=00009077. I moduli NVIDIA sono la baseline strumentata invariata e il parametro RM64KBBAR1Mappings=0 rimane attivo.

`kernel.log:1063`–1100 mostra il resume standard dei soli due audio, entrambi riusciti, con usage_count=1 e runtime status ACTIVE. Le sette reference del helper sono presenti. Il commit avviene a 7,604977 secondi, prima del caricamento NVIDIA a 7,732259 secondi. Risultato del helper: `relocated_verified_reboot_to_restore`, rc=0, audio_pm_prepared=1. Nessun ramo di rollback della transazione è stato eseguito.

Il confronto dell'inventario completo dei 36 dispositivi identifica esattamente cinque risorse cambiate: la finestra prefetch di D7 e dei due bridge ASMedia, BAR1 e BAR3 dell'A2000. Nessun'altra risorsa kernel cambia. Gli inventari `after-relocation`, `after-driver` e `after-test` sono identici fra loro.

| Risorsa | Prima della prova | Durante tutte e tre le verifiche |
|---|---|---|
| A2000 BAR1, 256 MiB | 4600000000–460fffffff | 80000000–8fffffff |
| A2000 BAR3, 32 MiB | 4610000000–4611ffffff | 90000000–91ffffff |
| D7 finestra prefetch | 4600000000–4801ffffff | 80000000–91ffffff |
| ASMedia 04:00.0 e 05:00.0 | 4600000000–4611ffffff | 80000000–91ffffff |

I dump binari confermano BAR1=8000000c/00000000, BAR3=9000000c/00000000 e, su tutti e tre i bridge, PMBL=91f18001, PMBU=0, PMLU=0. Il percorso `/proc/iomem` contiene correttamente i tre bus annidati e le due risorse GPU. Tutti e tre i verificatori esterni riportano `LOW_MMIO_NATIVE_PASS`: NVIDIA non ha riespanso il BAR durante questo boot.

Prima e dopo la riallocazione COMMAND è identico sui nove dispositivi fotografati, inclusi i sette gestiti dal helper. Nei primi 256 byte della config cambiano soltanto i BAR e le finestre previsti. La config completa ha anche differenze nei campi estesi dei root port Intel a 328/32c/394, alle quali non assegno una semantica non verificata; i bridge ASMedia ripetono inoltre la finestra negli intervalli specchiati ogni 400h. Non viene dichiarata l'uguaglianza integrale di tutti i 4096 byte.

## Dati e mapping

Le quattro catene software WINDOW→DMA→RM_PTE→UVM sono coerenti e sono state ricontrollate anche dall'altro revisore. Gli indirizzi risultanti sono 4000400000 e 4000600000 verso Ada, 80400000 e 80600000 verso A2000. Le pagine peer restano da 2 MiB, gli indirizzi sono allineati, RM e UVM concordano sui bit PTE e gli invii terminano con successo. Questi sono log del percorso software e dell'invio, non una lettura delle tabelle MMU hardware.

Dieci controlli locali dell'owner sono validi. La CPU legge correttamente due pattern distinti dalla stessa allocazione BAR1 di entrambe le GPU; per A2000 la lettura riguarda realmente l'indirizzo basso 80600000. Questo prova che la finestra espone l'allocazione corretta alla CPU.

| Operazione effettiva | Esito |
|---|---|
| A2000 legge VRAM Ada | Fallisce |
| A2000 scrive VRAM Ada | Passa |
| Ada legge VRAM A2000 | Fallisce |
| Ada scrive VRAM A2000 | Fallisce: owner rimane zero |

`result.log:983`–997 riporta CPU BAR 2 PASS/0 FAIL/0 SKIP, TOTAL_FAILURES=3 e NATIVE_TEST_RC=5. La prova è completa, non fermata da timeout. Le letture P2P precedono le scritture in questo specifico probe; la prova separata di sole scritture resta la misura che elimina tale dipendenza dalla sequenza.

Dopo le due letture compare RMA, PCI_STATUS 0010→2010, prima su D7+A2000, poi su D1+Ada. Le due scritture non aggiungono differenze nelle fotografie operative. AER UES/CES e header restano invariati. Gli assert io_vaspace.c:598/607 compaiono a 14,174649 secondi e oltre, dopo i confronti dati e l'avvio del cleanup; restano un difetto di teardown del driver e non precedono questi tre risultati errati.

## Rientro dopo il reboot

`after-reboot-host.json` prova che A2000 BAR1 è tornato alla base alta 4600000000 e che D7 ha ripreso la finestra alta 4600000000–4801ffffff. Il campo config BAR1 high=46 concorda con la risorsa del kernel. Le patch firmware combinate rimangono applicate: il reboot ripristina l'allocazione BAR, non il firmware precedente.

La geometria dopo il rientro in XCP differisce dalla fotografia nativa prima della prova: BAR1 misura 8 GiB (4600000000–47ffffffff) e BAR3 parte da 4800000000. Quindi è verificato il ritorno agli indirizzi alti, non un ripristino byte per byte della geometria nativa da 256 MiB. Il JSON del rientro non comprende i due bridge ASMedia e non certifica autonomamente le loro finestre dopo reboot. Non attribuisco la differenza di dimensione a una causa specifica senza altri dati.

Esito strutturato e riscontri numerici sono in `verified-result.json`. Nessuna operazione remota o hardware è stata eseguita dal revisore.
