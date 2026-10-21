# MS-01 / Ampere + Ada / USB4: unresolved PCIe peer-transfer asymmetry

**Status, 21 October 2026: no bidirectional P2P fix.** This repository publishes a research archive, including negative results and experimental firmware. Passing an API capability check or completing a DMA command is not evidence of correct payload delivery.

## Setup

Minisforum MS-01, i9-12900H (906A3), AHWSA BIOS 1.26. Internal RTX 2000 Ada 16 GB on PEG, external RTX A2000 12 GB behind an AOOSTAR 800 W USB4 dock with ASM2464-family bridges (`1b21:2461`). Exact dock PCB revision is not yet confirmed. NVIDIA 595.99.02. Both VM passthrough and temporary native Linux were investigated; the qualified native experiments used experimental driver/libcuda components, not an unmodified supported configuration.

## Qualified native result

24 comparisons across 4 B, 64 KiB and 1 MiB, with all payload words checked and explicit owner synchronization:

| Operation / payload direction | SM passes | CE passes |
|---|---:|---:|
| PUSH internal Ada → external A2000 | 0/3 | 0/3 |
| PUSH external A2000 → internal Ada | 3/3 | 3/3 |
| PULL internal Ada → external A2000 | 0/3 | 0/3 |
| PULL external A2000 → internal Ada | 0/3 | 0/3 |

PUSH executes on the source; PULL executes on the destination. CUPTI observes 12 CE operations and 12 SM operations, with no dropped records. The first PULL uses the A2000 copy engine before any peer-read SM kernel. It fails too. CUPTI is not a TLP capture and cannot alone rule out unexposed internal staging.

The earlier word tests lacked some owner synchronization. Corrected tests include owner synchronization and local initialization checks; the failure persists. Older unqualified observations are not treated as equivalent to the corrected experiments.

The [full-payload native follow-up](../experiments/payload-diagnostics/results/native-20261021/README.md) repeats the same 24 cases with complete destination dumps. All six failed PUSH destinations match the initial sentinel at every word; all six successful PUSH destinations are fully correct; all twelve PULL destinations consist entirely of `ffffffff`. This rules out partially correct payloads in this run. Pattern-based offset matches are intrinsic source/sentinel coincidences, not evidence of aliasing. The data distinguish writes from reads with A2000 held as executor, while separate PUSH/PULL allocations and mappings remain an experimental confound. No component has been identified as the cause.

## Firmware and physical CE experiments

The reconstructed chain is `SaSetup[0x3E3] → EnablePeerMemoryWrite → SiInitFsp → D1:F0 CCFG`. FSP variants actually changed/read back D1 CCFG `04008077→00008077` and D7:F0/F2 `0e009077→00009077`. They did not fix forward delivery. The tested FSP span was later restored byte-for-byte; this does not mean every NVRAM setting returned to factory state.

A restricted diagnostic UVM path submitted a four-byte physical CE copy to the peer BAR1 window, checking allocation ownership, permissions, ranges and lifetimes. Destination physical modes NONCOHERENT_SYSMEM=2 and COHERENT_SYSMEM=1 both completed but preserved the same directional data failure. It is not a general-purpose physical-memory interface or a working production driver.

Native Linux, ACS/order/NoSnoop changes, BAR relocation below 4 GiB, mapping alignment and page-size variants did not resolve the issue. Not every attempted variant completed; see the detailed chronological record.

NVML counters respond to positive host-to-GPU controls. In the failed direction, Ada TX rises while A2000 RX remains close to baseline. These aggregate counters do not identify individual requests or localize the loss. Master Abort status changes were observed during PULL; absence of new AER events is not an error-free fabric guarantee.

## Open questions

- Does Alder Lake-H support the exact PEG↔TCSS peer path, and which documented initialization controls govern it?
- Is this Ampere/Ada pair unsupported in a way that explains the requester asymmetry, beyond capability gating?
- Could ASM2464/AOOSTAR firmware reject peer-origin requests differently from host-origin traffic?
- What transaction-level observation can separate GPU requester attributes, Intel routing and USB4 bridge acceptance?

GPU generation and physical placement are confounded: the older GPU is always external. We cannot swap cards or move them behind one switch. Host-RAM payload relay is not the target. No universal older→newer-only rule has been established.

Start with the [qualified log](../archive/p2p-next-investigation-20261021/native-pushpull-results/result.log), [analysis](../archive/p2p-next-investigation-20261021/native-pushpull-results/ANALISI.md), [firmware notes](../firmware/README.md), and [offline replay](riproducibilita.md). Most historical documents are in Italian; code and diagnostic fields retain their original technical names.
