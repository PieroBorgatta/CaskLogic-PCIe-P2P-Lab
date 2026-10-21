> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Audit indipendente Traffic2

Ricalcolati da `result.log` tutti i 624 campioni e le 48 statistiche: quattro finestre qualificate su quattro, tutti i return code NVML validi. Il baseline contiene 23–24 campioni per ciascun canale, l’attivo 10–14. I due trasferimenti Ada→A2000 falliscono su tutte le 262.144 parole confrontate; i due trasferimenti A2000→Ada sono corretti. Gli otto controlli iniziali sul proprietario sono validi.

Nel verso che fallisce, il TX Ada passa da circa 400 a 1.144.963–1.567.417 KB/s dichiarati; RX A2000 resta circa 292–297, compatibile col proprio baseline 294–298. Nel verso funzionante si osservano circa 4,07–4,60 milioni sul TX A2000 e 4,10–4,13 milioni sul RX Ada. Sono valori aggregati dell’API, non banda utile del buffer certificata.

Il controllo inverso dimostra sensibilità sul TX A2000 e RX Ada: **non calibra RX A2000 per un payload in ingresso**. La prova non consente quindi di dichiarare con certezza che nessun payload arrivi all’A2000, né di individuare TCSS o ASMedia come punto di blocco. Un controllo H2D dedicato potrà verificare quel canale. Anche tale controllo non trasformerà automaticamente il contatore in una traccia TLP o in una prova di commit in VRAM.

Le due catene peer sono coerenti, allineate a 2 MiB e identiche per fisico/DMA/PTE alle prove precedenti: Ada `4000400000`, A2000 `4600400000`. Il nonce, il VA e i BDF collegano correttamente proprietario e richiedente; 98 controlli del parser sono positivi. Gli ordinali RM possono cambiare tra avvii e non vanno assimilati agli ordinali CUDA: qui sono coincidenti, mentre nella prima Traffic erano invertiti, con identità fisiche comunque corrette. Le PTE osservate restano log software, senza rilettura hardware della MMU.

Nessuna variazione nei 54 snapshot PCIe/AER. Il firmware resta al profilo originale D1 `04008077`, D7:F0/F2 `0e009077` in tutte e tre le letture. Tutti i confronti precedono `data_done` a 26,317821 s; i quattro free e i due `WINDOW_DESTROY_DONE` precedono `context_exit_begin` a 26,318403 s. I quattro mapping IOVAS residui compaiono a 26,675196 s, 356,793 ms dopo, seguiti dagli otto assert noti. Non spiegano i fallimenti precedentemente confrontati.

Verificati localmente i 17 raw, la copia dello stato e tutti i 19 file del backup integrale contro gli SHA256 raccolti. Lo stato osservato del collector è `collected_verified`: questo audit non afferma che la successiva pulizia sia già eseguita. Evidenze nel file `independent-mapping-pci-nvml-review-firmware.json`; ricalcolo riproducibile con `../audit_traffic_mapping.py native-traffic2-results`.
