> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Limite documentato dei contatori PCIe NVML

Non è stata trovata nelle fonti primarie consultate una specifica che dica se `nvmlDeviceGetPcieThroughput` conti o escluda le richieste Memory Write successivamente scartate, né una definizione del punto di misura rispetto alla validazione dell’indirizzo o al commit in VRAM. Non si può pertanto localizzare un rifiuto in TCSS, nel bridge ASMedia o nella GPU destinazione attraverso questa sola API.

La [documentazione NVIDIA dell’API](https://docs.nvidia.com/deploy/nvml-api/latest/api/group__nvmlDeviceQueries.html) definisce misura su 20 ms, unità KB/s e gli errori di disponibilità. Il [catalogo dei field ID](https://docs.nvidia.com/deploy/nvml-api/latest/api/group__nvmlFieldValueEnums.html) distingue byte TX/RX, replay, bad TLP e unsupported request: non attribuisce ai byte una garanzia di scrittura riuscita. Le voci che descrivono esplicitamente `XMIT_DISCARDS` appartengono a NVLink e non vanno applicate ai contatori PCIe delle due GPU in esame.

Nel sorgente NVIDIA della versione effettiva 595.99.02, `ctrl2080bus.h` righe 1004–1027 espone `NV2080_CTRL_CMD_BUS_GET_PEX_UTIL_COUNTERS` e le maschere TX/RX. Questa interfaccia non documenta l’inclusione di pacchetti scartati. La dichiarazione e tabella generata di `subdeviceCtrlCmdBusGetPexUtilCounters_IMPL` sono presenti, ma il suo corpo non compare nel tree pubblico esaminato. Non è stata inoltre provata una chiamata diretta di questa funzione da parte della libreria NVML installata. [Header NVIDIA 595.99.02](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/595.99.02/src/common/sdk/nvidia/inc/ctrl/ctrl2080/ctrl2080bus.h).

Il [changelog ufficiale NVIDIA](https://docs.nvidia.com/deploy/nvml-api/change-log.html) registra storicamente un fix e relativo revert per una scala del throughput errata di un fattore 1000. Questa nota non prova che la build 595.99.02 usata qui sia affetta: giustifica conservare unità e valori grezzi e non presentare una conversione in banda utile come già calibrata. Il confronto relativo col baseline e col verso numericamente funzionante resta più circoscritto della stima assoluta.

Esito: misura utile per rilevare attività aggregata e orientare l’indagine; non è un contatore di byte consegnati al buffer né una traccia di instradamento. Nessun registro o nuovo controllo firmware è ricavato da questa ricerca.
