> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Rilettura CPU dopo la scrittura P2P

Questo candidato clona `native-cpubar-probe` lasciandolo invariato. Dopo ogni
`peer_write` e la sincronizzazione della GPU esecutrice, legge dalla CPU la
stessa parola della destinazione, prima di cambiare dispositivo CUDA e prima
della copia D2H originale. Non reinizializza il dato e non scrive nella BAR.

L'aggiunta è identica per entrambi i destinatari: Ada e A2000. Il valore atteso
è `0xa5a42468`, ottenuto dallo stesso seed del kernel per l'indice zero.

La nuova funzione usa il parser e il lettore originali, senza modifiche:
nonce della singola allocazione, UUID/BDF, GPUVA, handle, descrittore, finestra
BAR1, DMA e PTE devono formare una catena unica e ancora viva. La catena e
l'identità vengono ricontrollate dopo la mappatura. Un'ambiguità produce
`SKIP`; la lettura usa soltanto `O_RDONLY`, `PROT_READ` e un accesso volatile
di 32 bit. Le allocazioni rimangono vive fino al termine di tutti i confronti.

`CPUBAR_POSTWRITE` registra proprietario, esecutore, identità, indirizzo della
parola, identificatore della finestra, valore osservato e atteso, ed esito.
Le fotografie PCIe prima e dopo sono in sola lettura. Il riepilogo diagnostico
è separato e il codice di ritorno dei confronti P2P originali non cambia.

Interpretazione degli esiti:

- CPU vede il valore nuovo e D2H vede quello vecchio: divergenza concreta di
  visibilità tra i due percorsi, da localizzare ulteriormente.
- Entrambi vedono il valore vecchio: nessuna prova che la scrittura sia arrivata
  alla VRAM; instradamento, completamento e attributi restano da distinguere.
- Entrambi vedono il valore nuovo dopo questa aggiunta: la lettura CPU e il
  ritardo introdotto possono aver cambiato il comportamento; occorre un
  controllo causale prima di attribuire il risultato a una cache specifica.
- `SKIP`: nessuna conclusione dalla diagnostica CPU; il confronto P2P resta
  registrato separatamente.

La verifica locale ha ricostruito la baseline byte per byte eliminando soltanto
la nuova funzione, la chiamata e il riepilogo. Entrambi gli header sono identici
alla baseline già verificata con 425 casi del parser. La nuova funzione e gli
header superano il controllo sintattico C++17 con `-Wall -Wextra -Werror`, sia
nel ramo host sia nel ramo Linux con una dichiarazione sostitutiva di `klogctl`.
Quest'ultimo controllo non equivale a una compilazione Linux/NVCC.

`local-validation.json` contiene comandi e hash; `baseline.diff` contiene il
delta completo; `independent-review.json` contiene la revisione indipendente.
Nessuna compilazione NVCC, esecuzione GPU o operazione remota è stata effettuata
durante questa preparazione. La catena dei log software non è un readback delle
PTE hardware.
