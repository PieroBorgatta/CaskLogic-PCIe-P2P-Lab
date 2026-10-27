# IOMMU status and explicitly translated MMIO — 27 October 2026

**The bidirectional VRAM P2P problem remains unresolved.** Register reads and address-mapping controls are diagnostic evidence, not a general GPU transport.

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

## Completed translated-IOVA experiment

The [UVM patch](translated/driver/iova-mmio.patch) adds a dedicated default-off diagnostic endpoint (`ioctl 317`, ABI 1). It accepts GPU identities and an executor index, with no physical addresses, user memory or RM handles as inputs. It requires the exact native CPU/GPU identities, administrative privileges, an active strict translated DMA domain, and the expected C7B5 class. Both GPUs are registered using local VMM allocations; ordinary CUDA peer access is not enabled.

For each GPU, the module maps only the remote BAR0 page with `dma_map_resource(DMA_TO_DEVICE)`, verifies that the returned IOVA differs from the BAR physical address and resolves back to exactly that resource, and checks the host control's DMA translation separately. Each SYS1/SYS2 trial is RAM read → peer register read → RAM read. A private local VRAM page is prefilled with a distinct sentinel and all 1,024 words are checked for unintended changes. Source data and the remote CPU-visible register are checked again. An uncertain completion retains all DMA mappings, buffers, GPU and module references until the independent return watchdog.

The actual native run used `intel_iommu=on iommu.passthrough=0 iommu.strict=1`:

| Executing GPU | Verified remote mapping | RAM controls | Remote SYS1/SYS2 reads |
|---|---|---:|---|
| Internal Ada | `ed5ff000 → 60000000` | 4/4 correct | Both `ffffffff`; expected `b76000a1` |
| External A2000 | `f11ff000 → 6d000000` | 4/4 correct | Both `ffffffff`; expected `197000a1` |

All guards and source controls were intact. Both DMA mappings were released after confirmed completion. Four direct DMAR samples, before and after NVIDIA, showed translation enabled (`GSTS=c7000000`) and protected regions inactive (`PMEN=0`). No Xid or DMAR fault was reported in the complete private kernel log. The [qualified result](translated/results/qualified.json) and scoped logs can be replayed offline. This is a completed negative result for the tested remote reads. **It does not test translated peer writes and does not establish a unique failing component.** This control also uses an internal CPU-to-GPU CE channel, unlike the earlier P2P-channel physical-address control; the two experiments differ in more than address translation.

The [first attempted boot](translated/attempt-01/) stopped before any GPU transfer because the read-only boot profile still blacklisted NVIDIA. It remains explicitly `incomplete_preserved`. The second attempt corrected only the temporary kernel module blacklist to `nouveau`, using the identical archive and binaries. The qualifier was then corrected to allow the initramfs's RAM-backed `rootfs / rootfs` mount; block-backed root mounts and wrong filesystem types are rejected. Both corrections are recorded rather than counted as GPU failures.

The tested UVM module SHA-256 is `61adc1d751f8f21812b96b35e57024dad3191425f91cb4edb62429a526f3ad9b`; the userspace binary is `1eebdad75991605eb59cefe34ece7ce44cfd366c98dee3cacdf4d6e445d54665`. The CPU build manifest's `gpu_binary_executed=false` describes the build phase, not the later native run. The tested archive contained 2,292 unchanged baseline members, three replacements and one added read-only status module. Original EFI entries/order and CCFG were verified after cleanup. Services and training remain held at the owner's request.

Published GPU UUIDs are placeholders; restore the correct identities before a deliberate rebuild. The patch targets the inspected 595.99.02 UVM interfaces and must be built against matching NVIDIA/kernel components. The entire private deployment image and full machine inventories are omitted. A rebuilt redacted source need not produce the private tested binary's hash.

Additional offline parser tests:

```sh
python3 -m unittest discover -s experiments/iommu-mapping/translated -p 'test_*.py'
```

These cover two synthetic complete states and 31 rejection variants (33 variants in total), including wrong translation, addresses, source/guard data, missing reads, incomplete DMA lifecycle, GPU/IOMMU faults and unexpected mounts. They do not perform hardware transfers.
