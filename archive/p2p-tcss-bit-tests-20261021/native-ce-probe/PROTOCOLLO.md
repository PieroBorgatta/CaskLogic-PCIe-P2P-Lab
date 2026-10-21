> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Confronto CUDA SM / motore di copia osservato

Candidato separato, da eseguire soltanto nel boot RAM dedicato gestito dal coordinatore. Non modifica registri PCIe, firmware, driver, né i probe precedenti.

Quattro buffer VMM da8MiB persistono fino al termine. Le due sorgenti sono accessibili soltanto al rispettivo owner; le due destinazioni sono RW su entrambe le GPU. Proprietà dei handle, diritti all'inizio/fine mapping, BDF/UUID e contesto dello stream vengono verificati. Per ciascuna direzione: 4byte,64KiB,1MiB; SM e `cuMemcpyDtoDAsync` sul medesimo stream sorgente. Dodici confronti, sempre preceduti da inizializzazione sincronizzata e confronto integrale source/poison target. Nessuna peer-read viene richiesta dal kernel SM.

CUPTI12.6.80 (API24) registra Driver, Memcpy5, MemcpyPtoP4, Kernel9 ed ExternalCorrelation. La callback DtoD acquisisce VA/byte/stream soltanto mentre i parametri sono validi. Per CE osservato occorrono callback entry/exit e record Driver con stessa correlationId, record copia coerente con quella chiamata e con source executor/context/stream, byte totali attesi e canale ASYNC_MEMCPY. Il trace registra anche kernel e copie host; richiede zero record persi. Le attività non vengono associate soltanto in base all'ordine di arrivo.

`CE_DATA_RESULT` descrive il confronto integrale. `CUPTI_CASE_RESULT` descrive la copertura e il motore osservato. `CE_PROGRAM_END protocol_complete=1` certifica che i dodici casi e i rilasci espliciti sono stati completati; non implica dati validi o trace completa. I timestamp CUPTI sono confrontati esclusivamente con `cuptiGetTimestamp`; i marker CLOCK_MONOTONIC restano una base distinta.

Codici: 0 = dati validi, trace completa e tutti i sei CE/six SM osservati; 5 = mismatch dati con trace completa e motori osservati; 6 = trace incompleta oppure un confronto non dimostra il motore richiesto; 20+ = errore setup/API/protocollo/owner. Il wrapper conserva tutti i log anche con codice6. Ogni risultato stampa `direct_route_proven=0`: un PASS CUDA/CE non viene dichiarato P2P diretto risolto senza escludere lo staging interno del driver.

Dipendenze: header CUDA12.6, header CUPTI12.6.80 estratti nella directory include, libcupti.so.12 e dipendenze reali verificate dal builder; libcuda595.99.02 uguale alle prove precedenti. `pcie_diag.h` è la copia immutata del diagnostico a sola lettura. Le sole scritture CPU del programma sono buffer CUDA tramite API sul rispettivo owner e marker `/dev/kmsg`; non esegue MMIO write CPU o modifiche config PCIe.
