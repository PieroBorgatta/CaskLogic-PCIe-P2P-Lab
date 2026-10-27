# Physical-route controls — 27 October 2026

**Bidirectional P2P remains unresolved.** Five native runs reproduce the same
operation/direction distinction. Two new controls also show that the failing
path is not explained solely by peer-VRAM BAR1 translations.

These are four-byte diagnostics on the original MS-01 topology, with the restored
BIOS/FSP profile, IOMMU disabled, and no VM data disks mounted. The programs retain
two persistent 8 MiB VMM allocations, RW on both GPUs, and use fresh source words
and complement sentinels for each ordinary comparison. The external A2000 executes
first; the internal Ada executes second.

## Results

Each run has the same **12 ordinary peer comparisons: 3 pass, 9 fail**:

| Executing GPU | Operation | Observed destination |
|---|---|---|
| External A2000 | PUSH to Ada: SM before, physical CE, SM after | Correct in all three cases |
| External A2000 | PULL from Ada: physical SYS modes 1 and 2, then SM | `ffffffff` in all three cases |
| Internal Ada | PUSH to A2000: SM before, physical CE, SM after | Initial sentinel in all three cases |
| Internal Ada | PULL from A2000: physical SYS modes 1 and 2, then SM | `ffffffff` in all three cases |

Sources remain correct. All six raw CE submissions report confirmed completion;
completion alone is not counted as payload success. Source patterns, sentinels,
GPU contexts, persistent allocation identities and RM/UVM mapping joins are
qualified separately from numerical results.

| Run | Additional observation |
|---|---|
| [physical-pull](physical-pull/results/qualified.json) | Explicit physical SYS-source PULL also fails in both directions. |
| [host-source](host-source/results/qualified.json) | Four controls using ordinary host RAM as the physical source pass, with the same raw C7B5 emitter and local VRAM destination. |
| [bar0-read](bar0-read/results/qualified.json) | Four remote reads of documented read-only `NV_PMC_BOOT_0`, BAR0 offset zero, return `ffffffff`. CPU reference reads remain stable. |
| [pramin-push](pramin-push/results/qualified.json) | Two A2000→Ada writes through a private VRAM page's BAR0/PRAMIN alias pass; both Ada→A2000 writes retain the sentinel. |
| [aer-report](aer-report/results/qualified.json) | Reporting enabled and restored as specified; 144 pre/post transfer snapshots confirm the active controls. No new AER UES, TLP header, Root Status or Root Source ID appears. |

The last three runs retain all four host controls and four BAR0-read controls.
The PRAMIN run adds four further comparisons. These counts are reported separately
in each qualification file; repeated controls are not independent hardware trials.

## What the controls establish

The raw SYS-source sequence can read ordinary host RAM correctly on both GPUs.
Failed peer reads also occur against non-prefetchable BAR0 registers at low
32-bit addresses, outside the peer BAR1 VRAM mapping. The reverse-direction PUSH
failure also reproduces through a non-prefetchable BAR0 alias of a newly allocated
VRAM page. This narrows the observations beyond a BAR1-only explanation.

It does **not** locate the fault in a requester, GPU, host fabric, USB4 bridge,
firmware policy or mapping mechanism. Architecture remains confounded with physical
placement. Master Abort (`PCI_STATUS` `0010` → `2010`) appears around failed reads,
but an all-ones result does not itself prove which component generated a refusal.
No AER header was captured, including after enabling NFERE/URRE on the six devices
and unmasking Unexpected Completion on the internal PEG root port. Interrupts and DPC were not enabled; status registers were not cleared.

## Experimental implementation

The UVM diagnostic uses a privileged P2P CE channel, class C7B5 and documented
LOCAL_FB/SYS physical modes. Stock UVM's rejection of a peer-classified read source
is unchanged. This is isolated research, **not vendor-supported P2P enablement**.
Unlike the earlier full-buffer experiment, these runs do not use CUPTI. Driver
logs attest the raw submission; they are not a hardware transaction trace or a
hardware MMU readback.

Host controls use private UVM allocations and check 1,024 source/destination
words. BAR0 reads check a four-byte read-only register and 1,023 untouched guards.
The PRAMIN experiment initializes private source and target pages through their
own GPUs. It verifies the alias against 16 CPU-read words before the peer write,
then checks all 1,024 source words and 1,023 destination guards. The actual transfer
is GPU→GPU; CPU initialization/readback is not a host-RAM data relay.

PRAMIN temporarily changes only the documented BASE/TARGET fields of GPU register
`NV_PBUS_BAR0_WINDOW` (`0x1700`), then restores its exact value before further RM
allocation/mapping calls. The
[NVIDIA RM implementation](https://raw.githubusercontent.com/NVIDIA/open-gpu-kernel-modules/595.71.05/src/nvidia/src/kernel/gpu/bus/arch/maxwell/kern_bus_gm107.c)
shows this alias mechanism and the window's shared ownership. This diagnostic
lacks global RM/GSP/VBIOS exclusion and is **not suitable as a production
transport**. A four-byte success would not qualify concurrent use, large transfers,
CUDA peer reads, atomics or NCCL.

The error-reporting experiment changes only standard Device Control bits `0x000a`
and the internal PEG UEM bit `0x00010000`. It checks identities and disabled
system-error/interrupt/DPC controls before writing, reads every change back, and
restores owned bits before releasing allocations. Definitions follow
[Linux PCI register headers](https://raw.githubusercontent.com/torvalds/linux/master/include/uapi/linux/pci_regs.h).

Every run retains the existing experimental RM teardown warning about four IOVAS
mappings and eight IOVAS assertions after the comparisons. No NVIDIA Xid is
recorded. These warnings are preserved in the selected kernel evidence; they
prevent treating this as a clean production driver.

## Replay and provenance

```sh
python3 experiments/physical-route-controls/replay.py
python3 -m unittest discover -s experiments/physical-route-controls/pramin-push -p 'test_*validation.py'
python3 -m unittest discover -s experiments/physical-route-controls/aer-report -p 'test_*validation.py'
```

The replay requalifies all five published logs and requires equality with the
saved qualification results. Complete private originals were verified by SHA-256
before publication. Published files redact stable GPU/partition IDs, host names
and private paths. Kernel files contain selected research lines, including driver
warnings; full boot logs and binary PCI inventories remain private because they
contain unrelated device identifiers. Original and published digests are listed
in [export-records.json](export-records.json).

Source identity guards contain consistent placeholder UUIDs. These are research
sources and evidence, **not a ready-to-install firmware/driver bundle**. The
original compiled-module digests describe the tested private builds; changing an
identity guard changes a rebuilt module's digest. Existing experimental BIOS
artifacts elsewhere in this repository are unchanged.

The server's normal boot entries were restored after each run. Its containers,
training service and maintenance timers remain deliberately stopped at the
owner's request; this report does not claim that production workloads were
restarted.
