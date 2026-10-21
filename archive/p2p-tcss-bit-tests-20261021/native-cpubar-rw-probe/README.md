> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# Controllo CPU di scrivibilità delle due finestre BAR1

Candidato locale derivato dalla fonte postwrite congelata con SHA-256
`c05a9ccd05dfc3488457c0bcf9c2eba8736406a0c6ff1011c020bafa09990006`.
Non è stato compilato con NVCC, installato o eseguito sulle GPU durante questa preparazione.

I quattro confronti P2P, le letture CPU precedenti e successive ai peer write,
i kernel CUDA e il parser della catena dei mapping restano invariati. Dopo
`TOTAL_FAILURES` e `data_done`, prima di qualsiasi rilascio delle allocazioni,
il candidato prova dalla CPU la singola parola `src` ancora viva di ciascun
proprietario. Queste sono le stesse destinazioni dei peer write appena misurati.

Per ogni parola:

1. Risolve nuovamente la catena nonce → allocazione → descrittore → finestra
   BAR1 → DMA → PTE, richiedendo un mapping unico e ancora vivo.
2. Verifica UUID/BDF, identità NVIDIA, dimensioni e base BAR1. Apre esclusivamente
   `resource1`, con `O_RDWR|O_NOFOLLOW`; ricontrolla identità dopo `mmap` e
   catena completa prima di ogni scrittura.
3. Legge il valore precedente dalla CPU e dal proprietario CUDA sincronizzato.
   Se differiscono, non scrive e registra `SKIP`.
4. Scrive due pattern distinti dal precedente e dal valore atteso P2P. Dopo
   ciascun singolo store volatile di 32 bit esegue una barriera, una lettura
   CPU della stessa parola e un D2H del proprietario. Confronta entrambi.
5. Dopo qualsiasi tentativo di store prova a ripristinare il valore salvato,
   anche se un accesso ha generato SIGBUS/SIGSEGV, **soltanto se la stessa
   identità e catena sono ancora valide e non risultavano già perse**.
   Verifica il ripristino sia dalla CPU sia dal proprietario. Una perdita
   della catena impedisce ogni ulteriore store. Non esiste fallback H2D.

La granularità di `mmap` impone di mappare una pagina; la classe non espone il
puntatore e accede soltanto ai quattro byte validati e allineati. Non cambia
registri PCI, BAR, mapping NVIDIA o parametri del driver. La CPU inizializza e
confronta il dato diagnostico; non inoltra trasferimenti tra GPU.

I log `CPUBAR_RW_SAVED`, `MATCH`, `PATTERN`, `RESTORE`, `RESULT` e `SUMMARY` sono
separati dall'esito P2P e non modificano il suo codice di ritorno. `PASS` richiede
entrambi i pattern corretti nelle due viste e il ripristino confermato. `SKIP`
indica che nessuno store è stato tentato. Un errore dopo il primo tentativo di
scrittura, o un ripristino non verificato, non viene nascosto. Fault di accesso,
perdita d'identità o ripristino fallito fermano i successivi controlli RW.
Un fault nella lettura iniziale del precedente produce `SKIP` del solo target:
in quel ramo nessuno store è ancora avvenuto.

Il readback CPU può contribuire al completamento delle scritture PCIe postate.
Questo è un controllo del percorso **CPU → BAR1 → VRAM**, non una correzione
P2P e non una prova che le GPU possano scrivere attraverso lo stesso percorso.
Le PTE osservate restano tracce software; non vengono lette dalla memoria
hardware delle page table.

`local-validation.json` certifica la ricostruzione byte per byte della baseline
rimuovendo soltanto le aggiunte; gli header originali sono immutati. Sono passati
4143 controlli locali di limiti, store isolato e gestione dei fault, usando
esclusivamente RAM anonima privata del processo, più la verifica sintattica C++17
del ramo Linux con una dichiarazione sostitutiva di `klogctl`. Non equivalgono
alla compilazione NVCC o all'esecuzione target. La revisione indipendente è in
`independent-review-nvidia.json`.

Per la compilazione CPU nella VM, mantenere il toolchain CUDA già impiegato:

```sh
cd /mnt/llm/riscrivo/runtime/reports/p2p-tcss-bit-tests-20261021/native-cpubar-rw-probe
nvcc -O2 -std=c++17 -gencode arch=compute_86,code=sm_86 -gencode arch=compute_89,code=sm_89 peer_vmm_word_cpubar_rw.cu -lcuda -o peer_vmm_word_cpubar_rw_native
python3 build_native_repeat.py
```

L'ambiente del compilatore deve rendere disponibili gli stessi header e la
libreria CUDA Driver usati per i collaudi precedenti. Il builder verifica hash
di sorgente, tre header/include diagnostici, moduli, kernel e libcuda; produce
soltanto `native-cpubar-rw-probe-package` e rifiuta di sovrascrivere un pacchetto
precedente. Usa gli stessi moduli RM/UVM strumentati della baseline postwrite,
con `RM64KBBAR1Mappings=0`; non include la variante UVM a pagine 4 KiB né il
modulo VT-d in preparazione parallela. Non installa sulla ESP e non imposta un
avvio. L'eventuale wrapper conserva timeout GPU 25 s e rientro automatico 180 s.
