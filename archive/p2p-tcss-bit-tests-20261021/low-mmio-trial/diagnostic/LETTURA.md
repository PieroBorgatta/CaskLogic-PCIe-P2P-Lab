> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Clone diagnostico del preflight

Stesso modulo `cask_low_mmio`, parametri e guardie del candidato precedente.
Usare `execute=0` per la diagnosi richiesta. Il delta aggiunge una funzione
di stampa e una chiamata prima delle guardie: rimuovendole si recupera il
sorgente originale byte per byte. Non vengono aggiunte letture o scritture
PCI, resume, cambi di stato energetico o modifiche alle risorse.

Ogni dispositivo riporta identità reale/attesa, `current_state`, stato PM,
errore PM, `disable_depth`, `usage_count`, driver e risultato delle singole
condizioni. I sette dispositivi vengono stampati prima del primo rifiuto.
`usage_count` include il riferimento `get_noresume` già acquisito dal modulo.
I campi sono osservazioni distinte, non una fotografia atomica del PM.

Il log precedente termina dopo la GPU esterna funzione 0 e restituisce
`-ENODEV`: il dispositivo successivo è l'audio `0000:06:00.1`.
La causa precisa deve essere letta dal nuovo log.

In [Linux v7.0, pm_runtime.h](https://raw.githubusercontent.com/torvalds/linux/v7.0/include/linux/pm_runtime.h),
`pm_runtime_active()` accetta anche un dispositivo con PM disabilitato.
Uno stato software suspended insieme a `disable_depth>0` non basta quindi
a spiegare il rifiuto; conta separatamente anche lo stato PCI D0.

Se il dispositivo fosse effettivamente sospeso con PM attivo, il percorso
standard da valutare è `pm_runtime_resume_and_get()`, prima dei device lock,
mantenendo poi il riferimento e verificando nuovamente tutte le guardie.
La callback PCI di resume gestisce anche dispositivi senza driver e
ripristina la configurazione standard: [pci-driver.c](https://raw.githubusercontent.com/torvalds/linux/v7.0/drivers/pci/pci-driver.c).
Questo può modificare hardware e **non è implementato nel clone**.
`pm_runtime_set_active()` non costituisce un risveglio hardware e non va
usato per far passare artificialmente il controllo. Con PM disabilitato
occorre distinguere ulteriormente lo stato reale prima di proporre un'azione.
