<p align="center"><img src="docs/assets/casklogic-logo.png" width="230" alt="CaskLogic — original logo"></p>
<h1 align="center">CaskLogic PCIe P2P Lab</h1>
<p align="center"><strong>Two GPUs. Two PCIe branches. Successful writes in only one direction.</strong><br>An open investigation into the Minisforum MS-01, RTX 2000 Ada and RTX A2000 over USB4.</p>
<p align="center">
<img src="https://img.shields.io/badge/status-UNRESOLVED-d55b45?style=for-the-badge" alt="Unresolved">
<img src="https://img.shields.io/badge/NVIDIA-Ampere_%2B_Ada-76b900?style=for-the-badge&logo=nvidia&logoColor=white" alt="NVIDIA Ampere and Ada">
<img src="https://img.shields.io/badge/Intel-Alder_Lake_H-0071c5?style=for-the-badge&logo=intel&logoColor=white" alt="Intel Alder Lake H">
<img src="https://img.shields.io/badge/USB4-PCIe_tunneling-408d9d?style=for-the-badge&logo=usb&logoColor=white" alt="USB4 PCIe tunneling">
</p>
<p align="center"><a href="docs/technical-summary.en.md">Technical summary</a> · <a href="#key-results">Results</a> · <a href="firmware/README.md">Experimental BIOS</a> · <a href="docs/indice.md">Archive index</a></p>

![Topology and directional results](docs/assets/topology.svg)

## Why this repository exists

This repository collects **Piero Borgatta / CaskLogic's** investigation of 20–28 October 2026: CUDA tests, experimental NVIDIA RM/UVM modifications, BIOS/FSP analysis, measurements and negative results. It gives researchers familiar with PCIe, Intel TCSS, USB4 or NVIDIA drivers concrete evidence to review and a basis for proposing the next useful diagnostic step.

**There is no verified fix for bidirectional P2P.** A reported capability, a changed register or a completed DMA command does not prove correct payload delivery. Successful comparisons in one direction do not qualify the experimental implementation for production, atomics, NCCL or training.

## Hardware and environment

| Component | Observed configuration |
|---|---|
| Computer | Minisforum MS-01, Intel Core i9-12900H, CPUID `906A3` |
| BIOS | AHWSA 1.26; static comparison with 1.27 |
| Internal GPU | NVIDIA RTX 2000 Ada Generation, 16 GB, Ada, compute capability 8.9 |
| External GPU | NVIDIA RTX A2000, 12 GB, Ampere, compute capability 8.6 |
| Dock | AOOSTAR, 800 W power supply; AG02 is plausible, but the model label and PCB revision are unconfirmed |
| Bridge | ASM2464 family, PCI bridges `1b21:2461` |
| Route | Internal PEG ↔ Intel fabric ↔ TCSS/USB4 root ↔ bridge ↔ external GPU |
| Test driver | NVIDIA 595.99.02, with separately documented experimental variants |
| Environments | Passthrough VM on XCP-ng and temporary native Linux in RAM, without Xen |

The external connection uses **PCIe tunneling over USB4**, rather than ordinary USB transfers. In the native tests, Ada is at `01:00.0` and A2000 at `06:00.0`; CUDA indices must not be assumed to match on other machines.

## Key results

The native PUSH/PULL experiment with validated initialization and synchronization checks compares **every word** of **4 B, 64 KiB and 1 MiB** payloads.

| Payload direction and operation | Executing GPU | SM passes | CE passes |
|---|---|---:|---:|
| PUSH Ada → A2000 | Ada | 0/3 | 0/3 |
| PUSH A2000 → Ada | A2000 | **3/3** | **3/3** |
| PULL Ada → A2000 | A2000 | 0/3 | 0/3 |
| PULL A2000 → Ada | Ada | 0/3 | 0/3 |

**18 failures in 24 comparisons.** CUPTI observes 12 copy-engine (CE) operations and 12 streaming-multiprocessor (SM) operations, with no dropped records. The first PULL uses a CE and precedes every peer-read SM operation. CUPTI is not a TLP capture and cannot alone rule out unexposed internal staging.

[Full PUSH/PULL analysis — Italian](archive/p2p-next-investigation-20261021/native-pushpull-results/ANALISI.md) · [Sanitized public log](archive/p2p-next-investigation-20261021/native-pushpull-results/result.log)

### Full-buffer follow-up

A [new native rerun with complete payload capture](experiments/payload-diagnostics/results/native-20261021/README.md) confirms the same 6 passes and 18 failures. **Every failed PUSH Ada→A2000 word matches its initial sentinel; every successful PUSH A2000→Ada word is correct; every PULL word in either direction is `ffffffff`.** No partially correct payload was observed. The repository now includes all 24 raw captures (8.5 MiB), metadata, diagnostic source and offline validators.

This establishes the complete value distribution, extending the earlier first-mismatch logs. That rerun used separate PUSH/PULL mappings; the follow-up below controls this difference. Source-pattern/sentinel coincidences are not proof of addressing aliases. [Diagnostic method and reproducibility](experiments/payload-diagnostics/README.md).

### Same-allocation follow-up

The [full-buffer same-allocation experiment](experiments/same-allocation/results/native-20261021/README.md) retains **two persistent allocations and peer windows**, both RW on both GPUs, for 12 **PUSH → PULL → PUSH** brackets. All 12 A2000→Ada PUSH cases succeed, including the writes immediately after failed reads. All 12 Ada→A2000 PUSH cases retain their complete sentinel; all 12 PULL cases return only `ffffffff`. Fresh source patterns distinguish each case from previous contents.

**12 passes and 24 failures in 36 comparisons**, with 18 CE and 18 SM operations independently qualified by CUPTI. CUDA identities and instrumented BAR1/DMA/RM/UVM mappings remain stable. Thus the different PUSH/PULL allocations in the earlier experiment do not explain this asymmetry: the same Ada window accepts correct A2000 writes and fails A2000 reads. Software logs still do not identify the failing component or replace a hardware transaction trace. [Protocol, source and offline checks](experiments/same-allocation/README.md).

### Physical-route controls — 27 October

[Five further native runs](experiments/physical-route-controls/README.md) reproduce **3 passes and 9 failures in each 12-case peer suite**. Raw physical reads from ordinary host RAM pass on both GPUs, while four remote reads of a read-only BAR0 register return `ffffffff`. A separate private-VRAM PRAMIN/BAR0 alias preserves the write asymmetry: A2000→Ada succeeds, Ada→A2000 retains the sentinel. Enabling PCIe error reporting, with readback and restoration, captures no new AER error header. **No fix is verified.** These are four-byte raw-command/SM diagnostics without CUPTI, distinct from the earlier full-buffer captures.

### What has been tested

| Experiment family | Outcome and limitation |
|---|---|
| Stock driver | CUDA peer access unavailable in both directions; some `nvidia-smi` reports show OK without demonstrating working transfers |
| libcuda patch and dynamic BAR1 path | Enable experiments; do not eliminate corruption or missing payload delivery |
| ACS, coherency, NoSnoop, Relaxed Ordering, MPS, GPA/HPA | No fully passing matrix; incomplete attempts are explicitly identified |
| Native Linux without Xen | Asymmetry persists; Xen is not a necessary condition |
| Corrected synchronization | Addresses a limitation in early tests; asymmetry remains after correction |
| BAR below 4 GiB, PTE/alignment, UVM 4 KiB, SYS_COH | No resolution in the documented variants |
| `SaSetup[0x3E3]`, FSP and PEG/TCSS CCFG | Bits actually changed and read back; Ada→A2000 still fails; the FSP span was subsequently restored |
| Physical CE, destination NONCOHERENT=2 / COHERENT=1 | Both complete the command but retain the same Ada→A2000 payload failure |
| NVML TX/RX with positive host↔GPU controls | Consistent with failed delivery along the path; aggregate counters cannot locate individual TLPs |
| AOOSTAR firmware and GPU architectures | No applicable official update identified; no established universal older→newer-only rule |

The [complete experiment history — Italian](archive/p2p-tcss-bit-tests-20261021/STORICO-PROVE.md) distinguishes completed executions, timeouts, attempts without data comparisons and preparation only. The [final transfer report](archive/p2p-next-investigation-20261021/ESITO.md) and [AOOSTAR/architecture review](archive/p2p-aoostar-architecture-20261021/ESITO.md) take precedence over hypotheses in older documents. An [English technical summary](docs/technical-summary.en.md) covers the main findings and limitations.

### USB4 counter driver and measurements — 27 October

A new [opt-in Thunderbolt driver patch](experiments/usb4-counters/README.md) enables counters during tunnel creation, with CPU MMIO controls and restoration of the original module. Three points respond to known traffic; the dock PCIe counter remains zero even during successful transfers and cannot establish packet absence. A further **36-case native GPU run retains 12 passes / 24 failures** with complete payload capture and CUPTI observation. Ada-executed 1 MiB cases add little traffic above measured idle at the observed USB4 ingress, while A2000-executed cases add much more, including failed PULLs. This narrows the next investigation but does not uniquely locate the fault or provide a fix. [Raw measurements, source, full synthetic payloads and offline replay](experiments/usb4-counters/README.md).

### Direct IOMMU observations and translated-IOVA controls — 27 October

[Read-only register observations](experiments/iommu-mapping/README.md) confirmed that DMA translation and protected memory regions were inactive in the prior IOMMU-off boot profile, before NVIDIA loaded. A separate default-off UVM diagnostic then explicitly mapped peer BAR0 through each requesting GPU's active translated DMA domain. **All eight RAM controls passed; all four remote register reads returned `ffffffff`**, with source/guard checks intact and DMA mappings released. Translation was directly observed active before and after this run.

Two later private-VRAM controls mapped a live RM-managed BAR1 page into the requester's strict translated DMA domain. Both retained the established write asymmetry: **A2000→Ada passed 2/2 four-byte writes, Ada→A2000 passed 0/2 and retained its sentinel, and all 8/8 RAM controls passed**. In the second run, one post-peer CPU write to each same BAR1 allocation passed 2/2 with owner-GPU readback. Those CPU controls are not P2P; they show that the tested A2000 target and BAR1 opening accept host-originated writes, without locating the remaining GPU-originated failure.

A third ABI issued only same-GPU self-BAR1 writes in isolated processes, separated by a clean asynchronous-fault gate. It passed 8/8 RAM and 2/2 CPU controls but 0/4 self writes. It contains **zero cross-GPU transfers**, so this self-hairpin result is not a diagnosis of the PEG↔TCSS/USB4 peer route. The problem remains unresolved. Sources, scoped logs, private executed-artifact hashes and offline replay are [published here](experiments/iommu-mapping/README.md).

ABI 4 then armed an intentionally read-only `DMA_TO_DEVICE` translation for one private A2000 BAR1 page and issued one Ada-originated four-byte write. After the private-source, alias, same-page CPU and writable-RAM controls all passed, VT-d emitted the exact record `DMA Write NO_PASID`, requester `01:00.0`, matching `<BAR1_IOVA>`, reason `0x05`, `PTE Write access is not set`. This proves that the tested Ada write reached VT-d; it **does not prove remote delivery**, because the deliberate permission fault terminates the request there. Combined with the writable 0/2 Ada→A2000 result, the prudent root-cause class is an **asymmetric cross-hierarchy peer-forwarding failure for PEG→TCSS/TBT posted writes, after VT-d ingress**, most likely a platform/root-complex routing policy or limitation. ABI 4 alone does not prove the exact downstream drop point; the [sanitized ABI 4 record and fail-closed replay](experiments/iommu-mapping/vtd-emission/README.md) make no single-block attribution and no P2P-solution claim.

### Host-mediated CPU-MMIO relay — 28 October

[ABI 5](experiments/cpu-mmio-relay/README.md) correctly relayed **4 KiB / 1,024 words** from private Ada VRAM to private A2000 VRAM using CPU MMIO loads and stores through driver-managed BAR1 mappings. Owner-GPU and secondary CPU validation found zero payload or guard mismatches. No host payload buffer or RAM staging was used during the relay; validation memory was allocated afterward. This is a host-initiated workaround, **not PCIe P2P**, and the single diagnostic timing is not a performance result.

Together with ABI 4, the writable translated controls and the USB4 counters, the result localizes the blocked peer direction to the Alder Lake root-complex/fabric route from PEG toward TCSS/Thunderbolt, after VT-d ingress and before observed USB4 tunnel ingress. Intel's [12th Generation Core datasheet, Volume 2, section 2.15.1](https://cdrdv2-public.intel.com/710723/710723-003.pdf) documents peer writes as supported only between PEG ports; the external GPU here is below TCSS, not another PEG port. This supports a platform hardware routing-limit diagnosis, while the exact internal silicon block remains unexposed. The bidirectional P2P requirement is still unresolved.

### Directional bypass and benchmark — 28 October

The [directional transport policy](experiments/directional-transport/README.md) uses the qualified A2000→Ada CUDA D2D PUSH for bulk and limits the reverse CPU-MMIO path to a 64-byte control ACK. Reverse bulk fails closed unless host RAM is explicitly allowed. At 1 MiB, the two qualified forward PUSH samples have a 3.959 GB/s median, versus 0.655 GB/s for serial RAM staging and 0.0309 GB/s for the best CPU-MMIO relay: about 6.05× and 128.23× respectively. These are cross-run logical-throughput comparisons, not a TLP trace; bidirectional P2P remains unresolved.

The newly traced FSP `CpuPcieRpPeerToPeerMode` field feeds the same policy bit already tested, rather than demonstrating another independent firmware control. No SPI/NVM update was performed.

## Included BIOS and driver artifacts

The repository includes **two experimental full BIOS images** and **two candidate FSP regions**, with hashes, provenance and test status. The menu-modified BIOS was never flashed. The full PEG/TCSS image was reconstructed offline from the OEM BIOS; its FSP region was tested on the original machine, but the complete distributed image was not flashed.

**None of these BIOS variants fixes the problem.** These are not universal images: an incompatible flash can prevent booting. Hardware use requires exact board identification, your own backup and an available hardware recovery method. The repository does not automatically flash firmware or modify a server.

- [BIOS contents, limitations and reconstruction — Italian](firmware/README.md)
- [Download experimental firmware release — English notes](https://github.com/PieroBorgatta/CaskLogic-PCIe-P2P-Lab/releases/tag/research-2026-10-21)
- [Instrumented RM/BAR1 driver](archive/p2p-tcss-bit-tests-20261021/driver-instrumented/)
- [Physical CE UVM driver and contract — Italian](archive/p2p-next-investigation-20261021/driver-physical-ce/README.md)
- [CUDA reproducers, analyzers and offline checks — Italian](docs/riproducibilita.md)

The historical sources form a **research archive**, not a portable installer. Machine identifiers have been consistently replaced with fictional values; identity checks remain in place. Building for another system requires explicit review of those checks and dependencies, rather than indiscriminately removing them.

## Help we are looking for

1. Intel/OEM clarification of any platform-specific exception to the public datasheet's PEG-only peer-write support, including exact **PEG↔TCSS** behavior, controls and initialization stages.
2. NVIDIA confirmation of support for the Ampere A2000 / RTX 2000 Ada pair, and review of the methods actually submitted.
3. AOOSTAR/ASMedia information about hardware revisions, firmware and acceptance of peer traffic originating from another PCIe branch.
4. A trace or targeted experiment that distinguishes **GPU requester behavior, Intel fabric routing and USB4 bridge acceptance**.

Swapping the cards or placing them behind the same PCIe switch is not possible in this setup. Relaying payloads through host RAM does not meet the objective. These constraints also limit the conclusions: GPU architecture and position in the topology remain correlated.

[Open a technical issue](https://github.com/PieroBorgatta/CaskLogic-PCIe-P2P-Lab/issues/new) with hardware details, topology, versions and payload comparison results. Please distinguish hypotheses from observed results.

## Repository layout and integrity

| Path | Contents |
|---|---|
| `archive/` | Sanitized historical reports, sources, patches, results and checks |
| `experiments/` | New diagnostic sources, offline tests and complete captured payloads |
| `firmware/` | Modified OEM images, FSP regions and variant manifest |
| `docs/` | Technical summaries, archive index and reproducibility notes |
| `provenance/` | Original and published file hashes, exclusions and validation records |
| `tools/` | Local integrity checks and offline BIOS reconstruction |

```bash
python3 tools/verify_publication.py
python3 tools/replay_evidence.py
```

These commands read local files: they do not run GPU workloads, connect through SSH or write firmware. Confirming that an analyzer reconstructs 18 failures **does not** mean P2P works.

Personal SPI/NVRAM dumps, keys, credentials, VM disks, training corpora and checkpoints are excluded. Sanitized logs have different hashes from their originals; the manifest distinguishes both. Old internal manifests remain historical records, not checksums for the sanitized copies.

Most historical reports remain in their original Italian. Start with the [English technical summary](docs/technical-summary.en.md) for an overview.

## Sources and attribution

- [Linux PCI P2PDMA](https://www.kernel.org/doc/html/latest/driver-api/pci/p2pdma.html)
- [Linux Thunderbolt/USB4](https://www.kernel.org/doc/html/latest/admin-guide/thunderbolt.html)
- [Intel VT-d Architecture Specification](https://cdrdv2-public.intel.com/831418/vt-directed-io-spec.pdf)
- [NVIDIA open GPU kernel modules 595.99.02](https://github.com/NVIDIA/open-gpu-kernel-modules/tree/595.99.02)
- [CUDA Peer Device Memory Access](https://docs.nvidia.com/cuda/cuda-runtime-api/cuda_runtime_api/group__CUDART__PEER.html)
- [Intel datasheet 710723-003](https://cdrdv2-public.intel.com/710723/710723-003.pdf)

This project is not affiliated with or endorsed by NVIDIA, Intel, Minisforum or AOOSTAR. The CaskLogic name and original logo belong to the author's project. See [LICENSE.md](LICENSE.md) for the distinction between original contributions and third-party components.
