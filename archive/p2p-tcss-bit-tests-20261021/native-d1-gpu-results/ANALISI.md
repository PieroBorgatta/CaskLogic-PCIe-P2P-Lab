> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# CaskLogic — verifica prova nativa D7 + D1

La prova è completa e fallisce 3 confronti su 4: lettura Ada→A2000 fallita, scrittura A2000→Ada riuscita, lettura A2000→Ada fallita, scrittura Ada→A2000 fallita. La direzione della lettura indica dove risiede il dato e dove viene letto. Entrambe le letture restituiscono `EDCBA987` anziché `12346641`; lo XOR eseguito dal kernel è compatibile con un dato remoto `FFFFFFFF`. La scrittura fallita lascia `00000000` anziché `A5A42468`. È una prova da 4 byte, non una misura di banda.

Le GPU sono quelle attese: RTX 2000 Ada UUID `00000000-0000-0000-0000-000000000001` a 01:00.0, RTX A2000 UUID `00000000-0000-0000-0000-000000000002` a 06:00.0. Gli hash dei tre file del pacchetto coincidono con lo stato che ha armato il boot. Verificati anche i contenuti effettivi dell'initrd: init, programma ritardato, modulo dinamico e libcuda corrispondono al manifest. Il nuovo programma ha SHA256 `7dc0ce74bb8b33d6a9aa8c68fa2f15f3501ae51f934ee3728dbba8483a0ec8a2`.

D1=`00008077` e D7F0/F2=`00009077` sono confermati prima del driver, dopo il caricamento e dopo i confronti. Il kernel conferma `DMAR: IOMMU disabled`; il remapping degli interrupt resta esplicitamente attivo. Il controllo del sistema nativo passa e il tunnel della GPU esterna è presente.

Tutti i confronti terminano a 13.263499950 s (`data_done`, CLOCK_MONOTONIC). Tutti e quattro i rilasci espliciti terminano dopo questo punto. `context_exit_begin` è 13.263878116 s. La IOVAS viene distrutta con 4 mapping residui a 13.535957 s del log kernel; il primo assert è a 13.560577 s.

**Limite di registrazione:** il kernel conserva 10 marcatori e dichiara 15 righe soppresse dal rate limit; stdout conserva tutti e 25. I 10 marcatori comuni misurano uno scarto kernel−CLOCK_MONOTONIC fra 6.365206 e 6.395467 ms. Con lo scarto mediano la distruzione IOVAS avviene 265.713 ms dopo `context_exit_begin`, e il primo assert 290.333 ms dopo. L'ordine è quindi ricostruito dai tempi allineati dei due log; non si dichiara che i marcatori finali siano visibili direttamente nel log kernel.

**Conclusione:** i tre errori sui dati persistono con i controlli D7/D1 azzerati, senza Xen e senza liberazioni intermedie. Gli errori IOVAS registrati appartengono alla chiusura successiva ai confronti e ai quattro rilasci espliciti; non spiegano retroattivamente la corruzione già osservata. Resta possibile un difetto diverso nel mapping del driver. La prova non autorizza a concludere che il percorso hardware o il resto del driver siano corretti.

Verifica esclusivamente locale. Non modificati ESITO, firmware, ESP o server. Dettagli, tempi e hash sono in `verified-result.json`.
