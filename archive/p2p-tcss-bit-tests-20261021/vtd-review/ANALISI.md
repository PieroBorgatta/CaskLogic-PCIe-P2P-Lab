> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Verifica VT-d prima della lettura hardware

Nei risultati locali esaminati non compare una lettura registrata di `GSTS.TES`, `RTADDR`, `IRTA`, `PMEN` o dei BAR VT-d dedicati a TCSS. Il kernel legge internamente alcuni di questi registri, ma i log conservano solo versione e capacità. Non è corretto trasformare questa assenza in una prova che la traduzione sia attiva. È corretto aggiungere uno snapshot nativo di sola lettura.

## Evidenze già disponibili

Dieci log dei collaudi nativi riportano un solo DRHD, base `0xfed91000`, flag `1` (include-all), versione `5:0`, CAP `0xd2008c40660462`, ECAP `0xf050da`. La tabella ACPI DMAR annunciata misura `0x50` byte. Il log CPU BAR contiene `IOMMU disabled` a 0,052629 s e `Enabled IRQ remapping in x2apic mode` a 0,106560 s. L'interrupt remapping è distinto dalla traduzione degli accessi DMA: IRES e QIES attivi non dimostrano TES attivo. Log originale *(artefatto locale non pubblicato)*

Lo snapshot PCI già conservato mostra host `8086:4641` e `MCHBAR=0x00000000fedc0001` a offset PCI `0x48`. Questo consente un controllo stretto del profilo hardware prima di leggere i registri aggiuntivi. Configurazione originale *(artefatto locale non pubblicato)*

La ricerca ha coperto log, JSON, TXT e script dei report GPU precedenti e correnti, più i nomi degli artefatti DMAR/VT-d/ACPI/MMIO. Nessun dump binario ACPI DMAR identificato. Il dettaglio dei dieci log, con righe e SHA-256, è in [evidence.json](evidence.json). La conclusione riguarda il materiale conservato, non eventuali letture mai salvate.

## Cosa fa realmente Linux con `intel_iommu=off iommu=off`

Nel sorgente upstream Linux **v7.0**, `intel_iommu_setup()` imposta `dmar_disabled=1` e `no_platform_optin=1`; `iommu=off` imposta anche `no_iommu=1`. `pci_iommu_alloc()` invoca comunque il rilevamento Intel nel percorso nativo. Se DMAR è valida, `detect_intel_iommu()` registra `intel_iommu_init()`; l'initcall PCI la invoca. Nel ramo disattivato, questa funzione chiama **`intel_disable_iommus()`**, che percorre ogni unità DRHD conosciuta e chiama `iommu_disable_translation()`. Quest'ultima azzera GCMD.TE e attende che **GSTS.TES sia zero**. Esiste una specifica eccezione per unità dedicate alla grafica integrata con quirk, non il caso ordinario del DRHD include-all in esame. [Linux iommu.c](https://github.com/torvalds/linux/blob/v7.0/drivers/iommu/intel/iommu.c), [rilevamento DMAR](https://github.com/torvalds/linux/blob/v7.0/drivers/iommu/intel/dmar.c), [initcall PCI](https://github.com/torvalds/linux/blob/v7.0/arch/x86/kernel/pci-dma.c)

Quindi il parametro non è soltanto una scelta software: il percorso upstream prevede lo spegnimento hardware delle unità enumerate. Rimangono tre limiti: non abbiamo verificato l'identità completa tra questi sorgenti e il binario Ubuntu `7.0.0-38-generic`; non abbiamo il valore GSTS finale nei log; una unità omessa da DMAR non sarebbe percorsa da questa lista. Le fonti scaricate e i rispettivi hash sono in sources.json *(artefatto locale non pubblicato)*.

## Unità dedicate Thunderbolt e protezioni separate

L'implementazione **Alder Lake** di coreboot definisce quattro BAR VT-d TCSS a `MCHBAR+0x7888`, `+0x7890`, `+0x7898`, `+0x78a0`, formato 64 bit, enable bit 0, maschera base `0x7ffffff000`. Il generatore DMAR legge questi BAR e crea un DRHD per ciascuna porta Thunderbolt abilitata. Questo giustifica la lettura dei BAR anche se il firmware corrente annuncia solo il DRHD generale; non dimostra che sulla macchina siano abilitati. Fonte fissata al commit `0efe0567e794af09037e6c3841f5ea1885cd4112`. [Definizioni Alder Lake](https://github.com/coreboot/coreboot/blob/0efe0567e794af09037e6c3841f5ea1885cd4112/src/soc/intel/alderlake/include/soc/systemagent.h), [costruzione DMAR](https://github.com/coreboot/coreboot/blob/0efe0567e794af09037e6c3841f5ea1885cd4112/src/soc/intel/alderlake/acpi.c)

CAP del DRHD osservato dichiara supporto PLMR e PHMR (bit 5 e 6). Una protezione PMR può restare distinta da TES: Intel documenta che PMEN.PRS attivo può bloccare richieste DMA verso l'intervallo protetto anche con traduzione disabilitata, senza registrarle come fault di remapping. Nel ramo Linux disattivato il reset esplicito delle PMR è condizionato a `tboot_noforce`. Occorre quindi leggere anche PMEN e gli estremi degli intervalli, poi confrontarli con gli indirizzi BAR1 effettivi. Non abbiamo evidenza che una PMR sia attualmente attiva. [Intel 710723-003, §3.8.15–19, pp.278–281](https://cdrdv2-public.intel.com/710723/710723-003.pdf)

## Snapshot minimo proposto

Il modulo in preparazione separata dall'agente audit deve limitarsi a:

1. Verificare avvio nativo, CPUID `906a3`, host PCI e MCHBAR attesi; acquisire la tabella DMAR completa da ACPI, verificandone lunghezza, checksum e struttura.
2. Leggere VER/CAP/ECAP, GSTS prima e dopo, RTADDR, FSTS del DRHD dichiarato `fed91000`; registrare separatamente TES31, QIES26, IRES25. IRTA e IQA/IQH/IQT servono al contesto, non sono indicatori sostitutivi di TES.
3. Se supportati da CAP, leggere PMEN, PLMBASE/PLMLIMIT e PHMBASE/PHMLIMIT. Le letture non devono azzerare fault o bit di stato.
4. Leggere i quattro BAR TCSS; per un BAR disabilitato salvare solo il valore. Per uno abilitato e con base validata, acquisire lo stesso snapshot distinguendolo dal DRHD dichiarato. Evitare indirizzi fisici indovinati, scritture GCMD, modifiche delle tabelle o abilitazioni di unità.
5. Conservare snapshot prima e dopo il solo collaudo GPU già previsto. Se TES/PMR sono disattivati in tutte le unità effettivamente campionate, questa ipotesi viene esclusa per quelle unità e quegli istanti, senza attribuire automaticamente il guasto al fabric.

L'helper è un artefatto di preparazione; questa nota non certifica una sua esecuzione. Nessuna operazione remota, scrittura hardware o nuovo collaudo GPU è stata effettuata da questo agente.
