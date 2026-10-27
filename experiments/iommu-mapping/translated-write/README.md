# Translated private-BAR1 write controls

These three default-off NVIDIA UVM diagnostics test four-byte raw C7B5 writes through explicitly translated DMA IOVAs. They are research controls for one RTX A2000 / RTX 2000 Ada system. They are not a supported peer-memory implementation and do not fix bidirectional P2P.

## Shared safety and qualification rules

Each ABI verifies the expected CPU, GPU PCI identities, placeholder-redacted GPU UUID slots, strict translated IOMMU domain and C7B5 class. It creates requester-local private VIDMEM for the source and owner-local private VIDMEM for the target. RM keeps a live CPU/BAR1 target mapping; the diagnostic resolves the present 4 KiB PTE and maps exactly that BAR1 page into the requester domain with `dma_map_resource(..., DMA_FROM_DEVICE)`.

The Linux [DMA API](https://docs.kernel.org/core-api/dma-api.html) defines `dma_map_resource()` for device MMIO resources. NVIDIA's [GPUDirect RDMA documentation](https://docs.nvidia.com/cuda/gpudirect-rdma/) discusses peer BAR mappings and DMA-address APIs, while its current product support guidance requires 1:1/pass-through IOMMU addressing. This translated-IOMMU raw lab is therefore an experimental diagnostic, not a claim that this path is supported GPUDirect product behavior.

The first and last IOVA bytes must resolve to the expected BAR1 page. Each SYS1/SYS2 write is bracketed by RAM writes. The owner GPU performs the primary full-page target readback; CPU BAR1 observations are secondary. Source pages, whole-page sentinels and guards are checked. A completed request must confirm stable mappings and release its DMA mapping. Uncertain completion retains backing objects until the independent watchdog returns the temporary native environment.

Userspace supplies GPU identities and an executor index, not physical addresses, RM handles or arbitrary user buffers. Ordinary CUDA peer mappings are disabled and host RAM is not used to relay peer or self payloads.

## ABI 1: cross-GPU write only

[ABI 1](write-only/) performs two cross-GPU private-BAR1 word writes per direction, one through SYS1 and one through SYS2.

| Requester | Owner | RAM | Private-BAR1 words |
|---|---|---:|---:|
| External A2000 | Internal Ada | 4/4 | **2/2** |
| Internal Ada | External A2000 | 4/4 | **0/2** |

The failed Ada→A2000 owner-GPU readbacks and secondary CPU observations retained the exact sentinels. That proves that the qualified destination did not contain the requested data; it does not prove that the requester emitted no write TLP. The pre-GPU first attempt is preserved separately as incomplete and is not counted as a transfer failure.

## ABI 2: post-peer CPU controls

[ABI 2](cpu-control/) repeats the ABI 1 peer sequence and obtains the same 2/4 result. Only after all peer outcomes are fixed, one CPU write is issued to each same BAR1 page, followed by a same-opening read to drain the posted write and a primary owner-GPU full-page readback.

Both CPU controls pass, including complete owner reset and secondary CPU observation. They are explicitly not P2P. They show that the tested A2000 page and RM/BAR1 opening accept host-originated writes even though the earlier Ada-originated peer word did not become visible.

## ABI 3: isolated self-BAR1 control

[ABI 3](self-loop/) executes one GPU per client process. Requester and owner are the same GPU; there are no cross-GPU operations. After index 0 exits, a three-second fail-closed gate checks kernel evidence for asynchronous faults before index 1 can start.

| Observation | Result |
|---|---:|
| RAM writes | 8/8 |
| Self-BAR1 writes | **0/4** |
| CPU BAR1 controls after self results | 2/2, not P2P |
| Cross-GPU transfers | 0 |
| Inter-process asynchronous-fault gate | Passed |

A self-BAR1 hairpin can have rules or engine behavior unlike either ordinary local VIDMEM or a real peer request. Consequently, the 0/4 self result is not evidence that the cross-branch route failed and cannot localize the Ada→A2000 problem.

## Scope and provenance

All write trials are four bytes and use raw SYS1/SYS2 commands. There is no CUPTI or physical TLP capture. Results do not qualify larger payloads, atomics, ordering, NCCL, training or production use.

Published driver sources retain the BDF/device guards but replace the two private GPU UUIDs with the same fictional `00…01` and `00…02` identities used elsewhere in the repository. Per-ABI metadata records separately:

- the private source/header hashes;
- the exact private module and client binary hashes executed natively;
- the private validator hash;
- the redacted public-source hashes.

The private binaries, initrd, installer, full logs, machine inventories, storage paths, host/VM identities and boot identifiers are not distributed. Because identity bytes were redacted, rebuilding the public source is not expected to reproduce the private module hash.

## Offline verification

From the repository root:

```sh
python3 experiments/iommu-mapping/replay.py
python3 -m unittest discover -s experiments/iommu-mapping/translated-write/write-only -p 'test_*.py'
python3 -m unittest discover -s experiments/iommu-mapping/translated-write/cpu-control -p 'test_*.py'
python3 -m unittest discover -s experiments/iommu-mapping/translated-write/self-loop -p 'test_*.py'
```

These commands parse scoped published evidence and synthetic fixtures. They do not load a driver, access a GPU, change firmware or contact another host.
