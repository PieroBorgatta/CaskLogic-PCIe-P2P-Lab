# Riproducibilità: archivio, analizzatori, hardware

## 1. Integrità dell'archivio pubblico

Da root del repository: `python3 tools/verify_publication.py`. Il controllo confronta file, dimensioni e SHA-256 con `provenance/SHA256SUMS.json`. Non certifica il contenuto scientifico né l'autenticità di un download se anche il manifest è stato sostituito.

`provenance/export-manifest.json` distingue hash originali e pubblicati. GPU UUID e percorsi personali sono anonimizzati coerentemente; gli hash presenti nei vecchi rapporti indicano gli originali, non le copie pubbliche. Alcuni collegamenti a dump/binari esclusi sono trasformati in riferimenti testuali espliciti.

## 2. Rianalisi offline del confronto qualificato

`python3 tools/replay_evidence.py` esegue solo l'analizzatore storico sul log pubblicato e ne confronta i risultati attesi: 24 confronti, 18 errori dati, 12 CE, 12 SM, traccia completa. Superare il controllo significa ricostruire correttamente **un risultato hardware negativo**.

I fixture test dell'analizzatore si eseguono con:

```bash
python3 archive/p2p-next-investigation-20261021/native-pushpull-probe/test_analyze_ce.py
```

Gli altri test storici sono conservati come provenienza. Alcuni richiedono fixture, intestazioni SDK o percorsi locali non distribuiti; non si dichiara che l'intero archivio sia una suite portabile. I test di pubblicazione e replay sono quelli verificati in questa versione.

## 3. Firmware offline

Vedere [firmware](../firmware/README.md). La ricostruzione viene confrontata byte per byte con il candidato incluso. Non viene scritto alcun dispositivo.

## 4. Sorgenti driver e riproduttori

La baseline comprende NVIDIA open GPU kernel modules 595.99.02, patch RM/BAR1, strumentazione PTE e varianti UVM. Le patch, i contratti e i manifest sono conservati nei percorsi originali sotto `archive/`. I sorgenti di partenza NVIDIA sono disponibili upstream; non è incluso l'intero SDK CUDA né la libreria proprietaria libcuda modificata.

I programmi CUDA richiedono SDK/header compatibili e in alcuni casi CUPTI/NVML. Le guardie identificano CPU, BDF, GPU e specifiche allocazioni: dopo l'anonimizzazione i due UUID sono fittizi. Non disabilitare le guardie per forzare l'esecuzione. Il codice è materiale sperimentale da adattare e revisionare, non una promessa di build immediata o sicurezza universale.

I moduli kernel sperimentali possono lasciare riferimenti trattenuti quando il completamento è incerto; il protocollo originale usa un ambiente temporaneo e riavvio controllato. Non eseguire test hardware mentre le GPU servono un training o un carico produttivo. Nessuna nuova prova GPU è stata svolta per preparare questo repository.

## Esclusioni

Non vengono distribuiti corpus/checkpoint, storage VM, dump SPI/NVRAM personali, chiavi, credenziali, pacchetti di boot, tool FPT e duplicati integrali di SDK/sorgenti vendor. Alcune copie storiche di script dipendono dall'orchestrazione locale: sono conservate per lettura e provenienza, non come istruzioni operative da eseguire alla cieca.
