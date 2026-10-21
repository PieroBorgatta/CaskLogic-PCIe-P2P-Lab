> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Riscontro indipendente: policy BAR1 a 64 KiB

Lettura statica locale del sorgente NVIDIA 595.99.02 validato in
`driver-instrumented/validated-complete-tree/source/NVIDIA-open-gpu-kernel-modules-19f3b34`.
Nessuna modifica al driver e nessuna operazione hardware eseguita da questo audit.

Nel log `native-instrumented2-gpu-results/kernel.log`, righe 1421–1426 e
1441–1446, la A2000 espone finestre BAR1 agli offset `0x2a0000` e `0x4a0000`.
DMA_MAP, RM_PTE e UVM_PTE concordano sugli indirizzi fisici
`0x46002a0000` e `0x46004a0000`, ma la pagina PTE richiesta è `0x200000`.
Entrambi gli indirizzi hanno resto `0xa0000` modulo 2 MiB. Le finestre Ada
`0x4000400000` e `0x4000600000` sono invece allineate a 2 MiB.
Il risultato rappresenta un'incoerenza concreta da eliminare prima di
attribuire il fallimento della scrittura al percorso PCIe.

La policy esistente spiega perché i due allocatori si comportano diversamente:

- `src/nvidia/interface/nvrm_registry.h:1178` definisce
  `RM64KBBAR1Mappings`, valore `0` disabilitato, valore `1` abilitato.
- `src/nvidia/src/kernel/gpu/bus/kern_bus.c:514` inizializza
  `bBar1Force64KBMapping=true`, lo disabilita se il parametro vale zero;
  senza parametro lo disabilita solo per BAR1 **maggiore di 256 MiB**.
  La A2000 ha esattamente 256 MiB, l'Ada 16 GiB.
- `src/nvidia/src/kernel/gpu/bus/arch/maxwell/kern_bus_gm107.c:172`
  determina questa policy durante `kbusStatePreInitLocked_GM107`.
- `src/nvidia/src/kernel/gpu/mem_mgr/arch/maxwell/virt_mem_allocator_gm107.c:701`
  riduce la pagina BAR1 alla pagina grande del VAS, normalmente 64 KiB,
  quando questa policy è attiva. A riga 919 `vaAlign` dipende dalla pagina
  scelta; a riga 1015 `vaspaceAlloc` usa tale allineamento.

La prova circoscritta usa gli stessi binari aggiungendo alla stringa
`NVreg_RegistryDwords` già esistente:

```text
;RM64KBBAR1Mappings=0
```

La sintassi è confermata in `kernel-open/nvidia/nv-reg.h:206` e nel parser
`src/nvidia/arch/nvalloc/unix/src/osapi.c:3352`: coppie separate da punto e
virgola, valori numerici, chiavi RM scritte nel registro globale.
`src/nvidia/arch/nvalloc/unix/src/registry.c:138` cerca prima il registro
per GPU e poi quello globale, quindi la lettura con `pGpu` trova il valore
globale. Un override specifico per GPU già presente avrebbe precedenza.

Nel percorso con allocazione VA e pagina DEFAULT,
`virt_mem_allocator_gm107.c:627` sceglie il minimo fra pagina compatibile
e pagina fisica; il ramo alternativo a riga 634 eredita la pagina del
memdesc. Per l'allocazione del probe, da 2 MiB e allineata a 2 MiB, rimuovere
il clamp dovrebbe consentire pagina/allineamento 2 MiB. Il riscontro operativo
richiesto è nuovo log WINDOW_CREATE/DMA_MAP/RM_PTE/UVM_PTE con indirizzi
allineati e coerenti. Il parametro da solo non costituisce prova di successo.

Il parametro cambia la granularità delle allocazioni virtuali dentro BAR1,
non base o dimensione dei BAR PCI, finestre bridge o firmware. Sul BAR1
piccolo può aumentare spreco di spazio e frammentazione; non garantisce
ammissione di ogni allocazione. L'Ada aveva già il clamp disabilitato.

**Non basta aggiungere PAGE_SIZE_2M alla chiamata dinamica.**
`kern_bus_gm107.c:2945–2965` esclude PAGE_SIZE_2M dai flag che identificano
la mappatura riusabile: il percorso normale lo perde prima della chiamata
all'allocatore. Il ramo UNMANAGED conserva quei flag, ma il successivo
clamp a 64 KiB agisce comunque. Modificare questo percorso sarebbe più
invasivo della prova del parametro già disponibile.
