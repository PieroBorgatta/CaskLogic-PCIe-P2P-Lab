# MS-01 PCIe P2P mystery: external RTX A2000 can PUSH to internal RTX 2000 Ada, but the reverse and both PULL directions fail

I'm investigating an unresolved GPU peer-transfer issue and would appreciate input from anyone familiar with Intel PEG/TCSS routing, USB4 PCIe tunneling, or NVIDIA RM/UVM.

I've published the investigation, diagnostic sources/patches, sanitized logs and experimental BIOS artifacts here:
https://github.com/PieroBorgatta/CaskLogic-PCIe-P2P-Lab

**This is a request for help, not a working P2P fix.** The experimental BIOS files did not solve it; they are clearly labeled, with provenance and hashes. Some full-image artifacts have never been flashed.

**Hardware**

- Minisforum MS-01, i9-12900H, AHWSA BIOS 1.26.
- Internal RTX 2000 Ada Generation 16 GB on PEG.
- External RTX A2000 12 GB via an AOOSTAR 800 W USB4 dock, ASM2464-family bridges. Exact dock PCB revision is still unconfirmed.
- NVIDIA 595.99.02. Tests include VM passthrough and temporary native Linux without Xen.

Stock CUDA does not expose usable peer access for this setup. The results below come from experimental driver/libcuda paths, so a defect in those paths remains a possible explanation.

**The reproducible pattern**

In the qualified native test, every payload word is checked at 4 B, 64 KiB and 1 MiB:

| Transfer | SM passes | Copy-engine passes |
|---|---:|---:|
| PUSH internal Ada → external A2000 | 0/3 | 0/3 |
| PUSH external A2000 → internal Ada | 3/3 | 3/3 |
| PULL internal Ada → external A2000 | 0/3 | 0/3 |
| PULL external A2000 → internal Ada | 0/3 | 0/3 |

PUSH runs on the source; PULL runs on the destination. CUPTI confirms 12 CE and 12 SM operations, with no dropped records. The first PULL uses the A2000 copy engine before any peer-read SM kernel and still fails. CUPTI is not a TLP capture, so I am not claiming it proves every detail of the physical route.

**What has already been investigated**

- Correct owner synchronization and local initialization checks. An earlier synchronization limitation was found and corrected; the asymmetry remains.
- Native Linux without Xen, plus ACS, NoSnoop/ordering and mapping/page-size/BAR-placement variants. Not every historical attempt completed; the archive distinguishes these.
- Actual BIOS/FSP changes: PEG CCFG `04008077 → 00008077` and TCSS CCFG `0e009077 → 00009077`, verified by readback. They did not fix Ada→A2000, and the FSP span was restored.
- A restricted four-byte physical CE copy into the peer BAR1 window, with both NONCOHERENT and COHERENT destination modes. Commands complete, but the same directional payload failure remains.
- NVML TX/RX sampling with successful host↔GPU positive controls. Failed forward traffic raises Ada TX while A2000 RX stays near baseline. These are aggregate counters, not proof of where individual requests disappear.

**What I cannot distinguish yet**

GPU generation and placement are confounded: Ampere is external, Ada internal. I cannot swap the cards or put them behind the same PCIe switch. Host-RAM payload staging is not the target.

I'm looking for a concrete lead:

1. Is PEG↔TCSS peer Memory Read/Write forwarding supported on Alder Lake-H, and is there a documented policy/register sequence for it?
2. Does NVIDIA document an Ampere/Ada restriction that explains this asymmetry beyond the software capability check?
3. Could ASM2464/AOOSTAR firmware treat peer-origin requests differently from host-origin traffic?
4. What trace or narrowly scoped experiment would best separate requester behavior, Intel fabric routing and bridge acceptance?

I would especially appreciate a datasheet section, relevant driver path, comparable hardware result, or transaction-level diagnostic suggestion. The repository includes an English summary; most chronological reports are in Italian. Thanks for any specific leads.
