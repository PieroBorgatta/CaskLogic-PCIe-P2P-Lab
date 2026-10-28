# MS-01 / Ampere + Ada / USB4: unresolved PCIe peer-transfer asymmetry

**Status, 28 October 2026: no bidirectional P2P fix.** A qualified host-mediated CPU-MMIO relay moves 4 KiB correctly without a host payload buffer, but it is not PCIe P2P. This repository publishes a research archive, including negative results and experimental firmware. Passing an API capability check or completing a DMA command is not evidence of correct payload delivery.

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

## Same-allocation control

A later control strengthens the operation/direction
finding: the [same-allocation native run](../experiments/same-allocation/results/native-20261021/README.md)
uses two persistent RW allocations and peer windows for 12 PUSH/PULL/PUSH brackets.
All 12 A2000 PUSH cases pass before and after unsuccessful reads; all 12 Ada PUSH
cases retain their entire sentinel, and all 12 PULL cases return only `ffffffff`.
Fresh source patterns distinguish all 36 cases. Raw CUPTI reconstruction qualifies
18 CE and 18 SM operations; software BAR1/DMA/RM/UVM mapping records stay unchanged.
The separate-allocation difference in the earlier run therefore does not explain
the observed asymmetry. The same Ada window accepts writes from A2000 and fails
reads from that same executor. Hardware routing, actual hardware PTE use and the
responsible component remain unproven. First CE PULLs (cases 2 and 20) set Received
Master Abort at the respective GPU and root port; sticky status prevents counting
subsequent errors. No firmware or driver implementation was changed for this run.

## Firmware and physical CE experiments

The reconstructed chain is `SaSetup[0x3E3] → EnablePeerMemoryWrite → SiInitFsp → D1:F0 CCFG`. FSP variants actually changed/read back D1 CCFG `04008077→00008077` and D7:F0/F2 `0e009077→00009077`. They did not fix forward delivery. The tested FSP span was later restored byte-for-byte; this does not mean every NVRAM setting returned to factory state.

A restricted diagnostic UVM path submitted a four-byte physical CE copy to the peer BAR1 window, checking allocation ownership, permissions, ranges and lifetimes. Destination physical modes NONCOHERENT_SYSMEM=2 and COHERENT_SYSMEM=1 both completed but preserved the same directional data failure. It is not a general-purpose physical-memory interface or a working production driver.

Native Linux, ACS/order/NoSnoop changes, BAR relocation below 4 GiB, mapping alignment and page-size variants did not resolve the issue. Not every attempted variant completed; see the detailed chronological record.

NVML counters respond to positive host-to-GPU controls. In the failed direction, Ada TX rises while A2000 RX remains close to baseline. These aggregate counters do not identify individual requests or localize the loss. Master Abort status changes were observed during PULL; absence of new AER events is not an error-free fabric guarantee.

## Open questions

- Is there any OEM-documented exception or platform-specific override for PEG↔TCSS peer routing beyond the public Intel datasheet's PEG-only support?
- Is this Ampere/Ada pair unsupported in a way that explains the requester asymmetry, beyond capability gating?
- Could ASM2464/AOOSTAR firmware reject peer-origin requests differently from host-origin traffic?
- What transaction-level observation can separate GPU requester attributes, Intel routing and USB4 bridge acceptance?

GPU generation and physical placement are confounded: the older GPU is always external. We cannot swap cards or move them behind one switch. Host-RAM payload relay is not the target. No universal older→newer-only rule has been established.

Start with the [qualified log](../archive/p2p-next-investigation-20261021/native-pushpull-results/result.log), [analysis](../archive/p2p-next-investigation-20261021/native-pushpull-results/ANALISI.md), [firmware notes](../firmware/README.md), and [offline replay](riproducibilita.md). Most historical documents are in Italian; code and diagnostic fields retain their original technical names.

## Native physical-route follow-up — 27 October 2026

[Five qualified runs](../experiments/physical-route-controls/README.md) retain the 3-pass/9-fail peer matrix. Ordinary host-RAM raw-source controls pass; peer reads also fail against a read-only remote BAR0 register. Direct posted writes through a private VRAM page’s BAR0 PRAMIN alias succeed A2000→Ada and fail Ada→A2000 with intact guards. Standard error reporting was enabled and restored, but no new AER UES or TLP header was captured. These four-byte tests do not use CUPTI or identify the failing component. The tested BIOS profile remains restored; production services are intentionally held stopped at the owner’s request.

## Native USB4 counter follow-up — 27 October 2026

The [USB4 counter experiment](../experiments/usb4-counters/README.md) adds a default-off, topology-guarded Thunderbolt patch that configures counters at path creation. The first calibration stopped on an unresponsive dock PCIe counter. A subsequent CPU MMIO control completed 16,448 correct measured reads with Bus Master Enable off and PCI Command restored. Three counters respond distinctly above measured idle; the dock PCIe counter remains uncalibrated, including for correct transfers.

The GPU measurement repeats the unchanged 36-case same-allocation protocol: 12 passes, 24 failures, 18 CE and 18 SM observations, 288 counter rows and complete payload captures. Ada-executed 1 MiB operations show little excess at host USB4 PCIe ingress and dock lane compared with A2000-executed operations, including failed PULLs. This is compatible with failure before the observed ingress for Ada operations, without distinguishing GPU, driver and host fabric. Aggregate counters and idle estimates are not a physical TLP trace. No dropped-packet increment was observed. NVIDIA was unloaded normally before tunnel teardown, and the original Thunderbolt module and four paths were verified after restoration.

## Direct IOMMU and explicitly translated MMIO/VRAM — 27 October 2026

The [IOMMU mapping follow-up](../experiments/iommu-mapping/README.md) first read the actual DRHD status before NVIDIA: GSTS `47000000`, PMEN `0`, DMA translation disabled, protected regions disabled, interrupt remapping enabled. This does not measure those registers during the prior GPU transfers and does not justify changing already inactive controls.

A dedicated default-off UVM endpoint subsequently mapped the remote BOOT_0 page with `dma_map_resource(DMA_TO_DEVICE)` into strict translated requester DMA domains. IOVA-to-physical resolution was verified. Four-byte raw C7B5 SYS1/SYS2 remote reads were each bracketed by RAM controls, using private local VRAM and full-page sentinel/guard checks. Eight RAM controls passed, while four peer register reads returned `ffffffff` instead of the stable CPU references. Both DMA mappings were released after confirmed completion; four direct status samples before/after NVIDIA showed translation active and PMEN zero. No Xid or DMAR fault was reported. An initial attempt that blacklisted NVIDIA stopped before GPU work and is preserved separately as incomplete.

The translated read control uses an internal CPU-to-GPU CE channel and no ordinary CUDA peer mapping. Its differences from the prior physical-address/P2P-channel control preclude attributing outcomes to IOMMU alone.

Two subsequent controls used a private requester-local VIDMEM source and a private owner-local VIDMEM page kept live through an RM-managed CPU/BAR1 mapping. The BAR1 page was mapped with `DMA_FROM_DEVICE` into the requester's strict translated domain, with endpoint translation, alias handshake, source/guard integrity, mapping stability and unmap verified. Both independent runs produced the same cross-GPU matrix: 8/8 RAM controls passed, A2000→Ada passed 2/2 four-byte writes, and Ada→A2000 passed 0/2 with the sentinel unchanged. This qualifies two delivered words in one direction; it does not prove that the failed direction emitted no write TLP.

The second run added one CPU write to each same live BAR1 page only after all peer results. Both owner-GPU readbacks passed. These 2/2 controls are not P2P, but show that the tested A2000 target and BAR1 opening accept host-originated writes. The remaining failure is therefore scoped to the Ada-originated GPU path or its properties, without distinguishing the requester, PEG→TCSS fabric, USB4 tunnel or transaction attributes.

A third ABI issued same-GPU self-BAR1 writes in two isolated processes, separated by a clean fail-closed asynchronous-fault gate. It passed 8/8 RAM controls and 2/2 post-self CPU controls, but 0/4 self writes. It contained zero cross-GPU operations. A self-BAR1 hairpin is not equivalent to a real peer route, so this negative result is not diagnostic of the PEG↔TCSS/USB4 problem. All three write runs are limited to four-byte raw C7B5 SYS1/SYS2 operations without CUPTI or physical TLP capture. There is still no VRAM transport fix.

ABI 4 deliberately mapped one private A2000 BAR1 page read-only (`DMA_TO_DEVICE`) in the internal Ada's strict translated domain and issued one four-byte SYS1 write. Private-source, BAR1-alias, same-page CPU-write and writable translated-RAM controls all passed first. VT-d then reported one exact `DMA Write NO_PASID` record from requester `01:00.0` at the matching IOVA, reason `0x05`, `PTE Write access is not set`. This proves that the tested Ada-originated write reached VT-d; the intentional permission fault prevents any claim of downstream delivery. The adaptive RAM trap was not launched after that exact BAR1 result.

Together with the earlier writable 0/2 Ada→A2000 outcome, this supports a prudent root-cause class: an **asymmetric cross-hierarchy peer-forwarding failure for PEG→TCSS/TBT posted writes, after VT-d ingress**, most likely a platform/root-complex routing policy or limitation. ABI 4 alone does not identify a single failing block or prove downstream delivery. The later ABI 5 and counter synthesis below narrows the functional block to the root-complex/fabric path before observed USB4 ingress, while still not exposing one internal silicon unit. The [sanitized ABI 4 record](../experiments/iommu-mapping/vtd-emission/README.md) uses symbolic addresses and a fail-closed offline replay.

## Host-mediated CPU-MMIO relay — 28 October 2026

[ABI 5](../experiments/cpu-mmio-relay/README.md) used private VRAM on both GPUs, exposed temporarily by driver-managed BAR1 mappings. A CPU loop relayed 1,024 32-bit words from the internal Ada mapping to the external A2000 mapping through a general-purpose register. Owner-GPU and secondary CPU validation found zero source, destination or guard mismatches. There was no host payload buffer and no RAM staging during the relay; the validation buffer was allocated afterward.

The result is a correct **host-mediated workaround**, not a GPU requester-to-peer transaction and not a P2P solution. Its one 4 KiB timing sample is retained only as diagnostic metadata and supports no bandwidth, latency or production claim.

## Directional bypass and performance — 28 October 2026

The [directional policy and ABI](../experiments/directional-transport/README.md) use the already-qualified A2000→Ada CUDA D2D PUSH for bulk data and reserve CPU-MMIO for a 64-byte reverse control record. Reverse bulk is rejected unless the caller explicitly opts into RAM staging. At 1 MiB, two fully correct CUPTI-observed forward PUSH samples have a median 3.959 GB/s. A separate qualified run measured 0.655 GB/s for serial RAM staging and 0.0309 GB/s for the best one-worker AVX2 CPU-MMIO relay. The cross-run ratios are 6.05× and 128.23×. The relay is 21.20× slower than RAM and is therefore control-only, not a bulk optimization.

This is a useful asymmetric pipeline, not a bidirectional P2P repair. CUPTI identifies CUDA D2D activity but is not a physical TLP trace; `direct_route_proven` remains false.

The combined ABI 4, writable-mapping and USB4-counter evidence places the functional block in the Alder Lake root-complex/fabric path from PEG toward TCSS/Thunderbolt, after VT-d ingress and before observed USB4 tunnel ingress. Intel's official [12th Generation Core datasheet, Volume 2, section 2.15.1](https://cdrdv2-public.intel.com/710723/710723-003.pdf) documents peer writes as supported only between PEG ports; this external branch is TCSS, not another PEG port. That documentation and the measurements support a **platform hardware peer-routing limitation** as the root-cause class. They do not expose which internal silicon unit drops the request, and they do not turn the CPU relay into P2P.

Original EFI/CCFG state and the user's maintenance hold were verified after return. Public sources retain topology checks but replace private GPU UUIDs; metadata records the private executed module, client and validator hashes separately from the redacted-source hashes.

Static BIOS analysis links RPL client UPD `CpuPcieRpPeerToPeerMode[4]` at `0xFAB` through the CPU policy GUID to the same EnablePeerMemoryWrite bit already tested. It is not a newly demonstrated independent control. There is still no verified bidirectional P2P fix.
