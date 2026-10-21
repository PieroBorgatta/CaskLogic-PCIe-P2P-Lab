> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Controllo CPU in lettura e scrittura sulla BAR1

Verificati 17/17 SHA256 e le sei sorgenti/header/init contro il manifest del boot. Il driver RM/UVM è la baseline strumentata, senza variante4K.

Entrambe le GPU accettano due scritture CPU da4byte: ogni valore coincide sia nella rilettura CPU sia nella lettura D2H eseguita dal proprietario. I valori precedenti sono ripristinati e verificati da entrambe le viste. Nessun fault, perdita di identità o controllo saltato: `pass=2 fail=0 skip=0 halted=0`.

La A2000 accetta queste scritture all'indirizzo fisico `4600600000`, nella stessa allocazione rimasta a zero dopo la scrittura Ada→A2000. Questo esclude una BAR1 generalmente non scrivibile per tale allocazione; distingue il percorso della CPU da quello della GPU richiedente. Non identifica ancora il punto di blocco e non prova gli attributi effettivi del TLP della GPU.

I quattro confronti P2P sono terminati prima dei controlli CPU: continuano a fallire le due letture e la scrittura Ada→A2000. Passa la scrittura A2000→Ada. Il cleanup e le sue asserzioni arrivano dopo entrambe le serie di verifiche. Tutte le allocazioni restano vive durante i controlli.
