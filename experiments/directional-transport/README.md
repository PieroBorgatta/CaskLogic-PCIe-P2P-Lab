# Trasporto direzionale sperimentale

Questo esperimento trasforma l'asimmetria osservata in una policy fail-closed:

- il payload bulk nasce sulla A2000 esterna e viene inviato alla Ada interna con il `PUSH` CUDA D2D già qualificato;
- la Ada non restituisce payload bulk: pubblica soltanto un ACK di controllo da 64 byte, inoltrato dalla CPU tramite le due aperture BAR1/MMIO;
- un trasferimento bulk Ada→A2000 viene rifiutato, salvo opt-in esplicito allo staging RAM.

`policy.py` seleziona la rotta e `protocol.h` definisce l'ABI. Sono una policy e un ABI di riferimento, non un backend concorrente production-ready. Il backend MMIO deve verificare l'allineamento reale dell'indirizzo a 64 byte. La copia dell'ACK non è atomica: `magic` deve essere pubblicato per ultimo, dopo fence, flush e verifica della sequenza. Il relay è control-only perché il benchmark mostra che non può competere con la RAM sul bulk.

## Benchmark qualificati

Le misure sotto provengono da due campagne diverse e confrontano throughput logico alla stessa dimensione di 1 MiB; non sono un unico benchmark simultaneo.

| Percorso | Direzione | Mediana | Correttezza |
|---|---|---:|---|
| CUDA D2D, 2 PUSH osservati da CUPTI | A2000→Ada | 3,959 GB/s | 2/2 payload completi corretti |
| staging RAM seriale | Ada→A2000 | 0,655 GB/s | 7/7 campioni corretti |
| relay CPU-MMIO AVX2, 1 worker | Ada→A2000 | 0,0309 GB/s | 7/7 campioni corretti |

Il PUSH D2D è circa **6,05×** lo staging RAM seriale e **128,23×** il relay MMIO alla stessa dimensione. Il relay è invece **21,20× più lento** dello staging: ottimizzarlo come canale bulk non è realistico. A 16 MiB il plateau resta circa 0,0312 GB/s e più worker peggiorano il risultato.

Il dato D2D è una richiesta CUDA D2D con attività CUPTI e confronto completo; non è una cattura TLP (`direct_route_proven=0`). Il risultato completo sanificato è in [`qualified-result.json`](qualified-result.json).

## Uso della policy

```python
from policy import GpuRole, TransferRequest, select_route

decision = select_route(TransferRequest(
    source=GpuRole.A2000,
    destination=GpuRole.ADA,
    bytes=16 * 1024 * 1024,
))
assert decision.route.name == "P2P_FORWARD"
```

Il verso inverso non viene mascherato con un fallback implicito. Questo bypass rende utile il verso funzionante, ma non risolve il requisito P2P bidirezionale e non qualifica NCCL, atomiche o training distribuito.
