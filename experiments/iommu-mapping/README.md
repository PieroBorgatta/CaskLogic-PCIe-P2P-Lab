# IOMMU status and explicitly translated MMIO/VRAM — 27 October 2026

**The bidirectional VRAM P2P problem remains unresolved.** Register reads, private-VRAM writes and address-mapping controls are scoped diagnostic evidence, not a general GPU transport.

## Read-only status with translation disabled

The [small GPL kernel module](status/dmar_status.c) checks the native AHWSA/BIOS 1.26 identity and parses the ACPI DMAR table before accessing the sole include-all DRHD at `fed91000`. It checks table bounds/checksum, segment, register version and CAP/ECAP identity. It reads only VER, CAP, ECAP, GSTS and PMEN, samples twice, unmaps and unloads. It contains no register writes.

Both actual samples returned:

| Register/decoded state | Observation |
|---|---|
| GSTS | `47000000` |
| PMEN | `00000000` |
| DMA translation | Disabled |
| Protected memory regions | Disabled |
| Interrupt remapping | Enabled |

These observations were made **after native USB4 authorization and before NVIDIA loading**, using the same `intel_iommu=off iommu=off` arguments as the prior GPU experiments. They do not establish the register state during a GPU transfer. They provide no basis for blindly clearing already inactive translation/protected-region controls. Interrupt remapping is a separate function.

The exact Ubuntu 7.0.0-38.38 source was also checked: DMAR detection registers the Intel initialization callback even when DMA translation is disabled, and the disabled branch invokes `intel_disable_iommus`. Protected-region handling is separate, which motivated the direct observation.

Published [result markers](status/results/result-markers.log), [register log](status/results/kernel-research.log) and [qualified result](status/results/qualified.json) preserve the relevant protocol. Full USB4 router register contents, boot logs and disk/device inventories are omitted. Export provenance records the original and published hashes. The public replay checks scoped protocol/register observations; presence and integrity of the complete private collection were verified separately before EFI cleanup.

## Offline verification

```sh
python3 experiments/iommu-mapping/replay.py
python3 -m unittest discover -s experiments/iommu-mapping/status -p 'test_*.py'
cc -std=c11 -O1 -g -fsanitize=address,undefined \
  experiments/iommu-mapping/status/test_dmar_decode.c -o /tmp/cask-dmar-test
/tmp/cask-dmar-test
```

The ACPI decoder has nine identity/bounds/checksum checks. Python tests include inactive and active synthetic states and twelve rejection variants. Synthetic fixtures are parser tests, separate from the actual `results/` records. These commands do not access GPU hardware.

## Address-mapping hypothesis

Linux's [DMA API](https://docs.kernel.org/core-api/dma-api.html) permits `dma_map_resource()` for device MMIO. A returned DMA address can differ from the CPU physical address. NVIDIA's [standard GPUDirect RDMA documentation](https://docs.nvidia.com/cuda/gpudirect-rdma/) requires identity addressing; it does not establish support for a custom translated-IOVA CE experiment. The 595.99.02 [NVIDIA OS interface](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/595.99.02/kernel-open/nvidia/nv-dma.c) already contains MMIO DMA-map helpers; using a Linux API is not itself a new routing capability.

The isolated control explicitly maps only the remote `NV_PMC_BOOT_0` MMIO page into the requesting GPU's translated DMA domain, verifies IOVA-to-physical resolution, and issues four-byte raw C7B5 SYS1/SYS2 reads. RAM controls bracket each peer read. No ordinary CUDA peer mapping, remote register write or VRAM transport is implied. A successful BOOT_0 read would still need separate private VRAM validation.

## Completed translated-IOVA BAR0-read experiment

The [UVM patch](translated/driver/iova-mmio.patch) adds a dedicated default-off diagnostic endpoint (`ioctl 317`, ABI 1). It accepts GPU identities and an executor index, with no physical addresses, user memory or RM handles as inputs. It requires the exact native CPU/GPU identities, administrative privileges, an active strict translated DMA domain, and the expected C7B5 class. Both GPUs are registered using local VMM allocations; ordinary CUDA peer access is not enabled.

For each GPU, the module maps only the remote BAR0 page with `dma_map_resource(DMA_TO_DEVICE)`, verifies that the returned IOVA differs from the BAR physical address and resolves back to exactly that resource, and checks the host control's DMA translation separately. Each SYS1/SYS2 trial is RAM read → peer register read → RAM read. A private local VRAM page is prefilled with a distinct sentinel and all 1,024 words are checked for unintended changes. Source data and the remote CPU-visible register are checked again. An uncertain completion retains all DMA mappings, buffers, GPU and module references until the independent return watchdog.

The actual native run used `intel_iommu=on iommu.passthrough=0 iommu.strict=1`:

| Executing GPU | Verified remote mapping | RAM controls | Remote SYS1/SYS2 reads |
|---|---|---:|---|
| Internal Ada | `ed5ff000 → 60000000` | 4/4 correct | Both `ffffffff`; expected `b76000a1` |
| External A2000 | `f11ff000 → 6d000000` | 4/4 correct | Both `ffffffff`; expected `197000a1` |

All guards and source controls were intact. Both DMA mappings were released after confirmed completion. Four direct DMAR samples, before and after NVIDIA, showed translation enabled (`GSTS=c7000000`) and protected regions inactive (`PMEN=0`). No Xid or DMAR fault was reported in the complete private kernel log. The [qualified result](translated/results/qualified.json) and scoped logs can be replayed offline. This is a completed negative result for the tested remote reads. **This read run alone does not test translated peer writes and does not establish a unique failing component.** This control also uses an internal CPU-to-GPU CE channel, unlike the earlier P2P-channel physical-address control; the two experiments differ in more than address translation.

The [first attempted boot](translated/attempt-01/) stopped before any GPU transfer because the read-only boot profile still blacklisted NVIDIA. It remains explicitly `incomplete_preserved`. The second attempt corrected only the temporary kernel module blacklist to `nouveau`, using the identical archive and binaries. The qualifier was then corrected to allow the initramfs's RAM-backed `rootfs / rootfs` mount; block-backed root mounts and wrong filesystem types are rejected. Both corrections are recorded rather than counted as GPU failures.

The tested UVM module SHA-256 is `61adc1d751f8f21812b96b35e57024dad3191425f91cb4edb62429a526f3ad9b`; the userspace binary is `1eebdad75991605eb59cefe34ece7ce44cfd366c98dee3cacdf4d6e445d54665`. The CPU build manifest's `gpu_binary_executed=false` describes the build phase, not the later native run. The tested archive contained 2,292 unchanged baseline members, three replacements and one added read-only status module. Original EFI entries/order and CCFG were verified after cleanup. Services and training remain held at the owner's request.

Published GPU UUIDs are placeholders; restore the correct identities before a deliberate rebuild. The patch targets the inspected 595.99.02 UVM interfaces and must be built against matching NVIDIA/kernel components. The entire private deployment image and full machine inventories are omitted. A rebuilt redacted source need not produce the private tested binary's hash.

Read-experiment parser tests:

```sh
python3 -m unittest discover -s experiments/iommu-mapping/translated -p 'test_*.py'
```

These cover two synthetic complete states and 31 rejection variants (33 variants in total), including wrong translation, addresses, source/guard data, missing reads, incomplete DMA lifecycle, GPU/IOMMU faults and unexpected mounts. They do not perform hardware transfers.

## Translated private-BAR1 cross-GPU writes

The later [translated-write family](translated-write/README.md) uses a private requester-local VIDMEM source and a private owner-local VIDMEM target. RM keeps a live CPU/BAR1 mapping to the target; the diagnostic resolves the present 4 KiB PTE, maps that BAR1 page with `dma_map_resource(DMA_FROM_DEVICE)` into the requester's strict translated DMA domain, and verifies the first and last IOVA translations. No physical address, RM handle or user buffer is accepted from userspace. There is no ordinary CUDA peer mapping and no host-RAM relay of the peer payload.

ABI 1 performs RAM → peer BAR1 → RAM in SYS1 and again in SYS2 for each requester. The owner GPU performs the primary full-page readback; a CPU BAR1 observation is secondary and cannot redefine that result.

| Requester | Owner | RAM controls | SYS1/SYS2 private-BAR1 writes |
|---|---|---:|---|
| External A2000 | Internal Ada | 4/4 correct | **2/2 correct** |
| Internal Ada | External A2000 | 4/4 correct | **0/2; sentinel unchanged** |

All source and guard checks passed, the BAR1 alias handshake passed, both IOVA mappings stayed stable and both DMA mappings were released after confirmed completion. Translation was active before and after NVIDIA; no Xid, DMAR fault, `NO_PASID`, watchdog or retained-resource state was reported. The result establishes two correct words in the A2000→Ada direction for this exact allocation, engine and mapping. An unchanged Ada→A2000 sentinel does not prove that no write TLP was emitted.

The first ABI 1 boot is preserved as `incomplete_preserved`: an inherited NVIDIA blacklist stopped it before driver loading and before any peer write. The completed run changed only that temporary blacklist to `nouveau`.

## Post-peer CPU BAR1 controls

ABI 2 repeats the same cross-GPU sequence and obtains the same 2/4 peer matrix and 8/8 RAM controls. Only after all peer results have been recorded, it issues one CPU `iowrite32()` to each same live private BAR1 page, followed by `ioread32()` to drain the posted write. The primary result remains the owner GPU's full-page readback; the CPU observation and the complete owner reset are additional checks.

| Originator and target | Qualified result |
|---|---:|
| A2000 → private Ada BAR1 | 2/2 peer words correct |
| Ada → private A2000 BAR1 | 0/2; sentinel unchanged |
| CPU → same private Ada BAR1 | 1/1 control correct |
| CPU → same private A2000 BAR1 | 1/1 control correct |

The two CPU controls are explicitly **not P2P transfers** and are not counted among peer successes. They qualify the tested target pages, RM/BAR1 openings, host-originated write path and owner visibility. In particular, the A2000 target that does not change under the Ada-originated write changes correctly under the later CPU write. This rules out the simple hypothesis that the current A2000 BAR1 opening is intrinsically unwritable, but it does not distinguish Ada requester behavior from PEG→TCSS forwarding, the USB4 tunnel or transaction attributes.

## Same-GPU self-BAR1 control

ABI 3 uses two separate client processes. Each process allocates source and target on one GPU and writes through that same GPU's translated IOVA to its own RM-managed BAR1 page. The index-1 process is allowed to start only after the index-0 process exits and a three-second fail-closed gate observes no asynchronous GPU/IOMMU fault. This ordering and both kernel gate markers are part of qualification.

| Control | Result |
|---|---:|
| RAM writes | 8/8 correct |
| Self-BAR1 writes | **0/4; sentinel unchanged** |
| Post-self CPU BAR1 controls | 2/2 correct, not P2P |
| Cross-GPU transfers | 0 |
| Inter-process fault gate | Passed cleanly |

The self run is not a cross-branch test: requester and owner are the same GPU in every operation. A self-BAR1 hairpin can differ from both local VIDMEM access and a real peer request, so its 0/4 result is **not diagnostic of the PEG↔TCSS/USB4 cross-GPU failure**. It neither contradicts the two correct A2000→Ada cross writes nor identifies a failing component.

All three write ABIs issue only four-byte raw C7B5 SYS1/SYS2 operations. They have no CUPTI or physical TLP trace and do not qualify larger transfers, ordering, atomics, NCCL or production use. Private tested module/client/validator hashes are recorded separately from the redacted public-source hashes in each experiment's metadata; a rebuild of the placeholder-UUID source is not expected to reproduce the private module hash.

Write-experiment parser tests:

```sh
python3 -m unittest discover -s experiments/iommu-mapping/translated-write/write-only -p 'test_*.py'
python3 -m unittest discover -s experiments/iommu-mapping/translated-write/cpu-control -p 'test_*.py'
python3 -m unittest discover -s experiments/iommu-mapping/translated-write/self-loop -p 'test_*.py'
```

These are synthetic parser and invariant tests. They do not access GPU hardware.
