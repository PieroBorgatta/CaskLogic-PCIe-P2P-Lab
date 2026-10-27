# ABI 4: VT-d emission discriminator

This package publishes the **scoped, sanitized evidence** for one native
experiment. It answers a narrower question than end-to-end P2P delivery:

> Did the internal Ada (`01:00.0`) issue the tested four-byte write far enough
> for VT-d to observe it?

The answer is **yes for this single operation**. The kernel reported:

```text
DMAR: [DMA Write NO_PASID] Request device [01:00.0] fault addr <BAR1_IOVA> [fault reason 0x05] PTE Write access is not set
```

`<BAR1_IOVA>` replaces the run-specific DMA address everywhere in this public
export. BAR/physical addresses, timestamps, process identifiers and storage
paths are likewise omitted or symbolized. The requester, access type, PASID
state, reason code and kernel explanation are preserved exactly.

## Protocol and controls

The default-off UVM diagnostic fixed the requester to the internal Ada and
used a private A2000 VIDMEM target kept live through an RM-managed CPU/BAR1
mapping. It mapped one 4 KiB target page into the Ada's strict translated DMA
domain with `DMA_TO_DEVICE`, which creates a read-only IOMMU mapping for a
device-originated write discriminator. It then issued exactly one four-byte
raw C7B5 SYS1 write and performed no later push.

Before arming the trap, all of these controls passed:

- private Ada source and guards intact, twice;
- A2000 owner-GPU/CPU BAR1 alias handshake: mask `f`;
- CPU write to the same private A2000 BAR1 page, with owner-GPU readback:
  mask `f` (a host control, not P2P);
- Ada write through a writable translated RAM mapping: mask `f`;
- translated first/last-page checks for the read-only target mapping.

The exact fault followed the `fault_arm` marker. The mapping and all backing
objects were retained until reboot, so no cleanup operation raced the fault.
The adaptive RAM read-only fallback was deliberately **not launched** after
the exact BAR1 fault.

## What the result proves

The exact `DMA Write`, `NO_PASID`, requester `01:00.0`, matching IOVA and
reason `0x05` record proves that the tested Ada-originated write reached VT-d
and was rejected because write permission was absent. It therefore rules out
the broad claim that this Ada path never emits a write request at all.

It does **not** prove remote delivery. The intentional read-only translation
terminates the request at VT-d, before the normal writable peer route can be
observed. It does not locate the later failure among VT-d egress/peer decode,
the Intel PEG-to-TCSS path, the USB4 tunnel/dock, transaction attributes or
the A2000 endpoint.

Taken together with the earlier writable result—A2000→Ada 2/2, Ada→A2000
0/2 with the sentinel unchanged, and 8/8 RAM controls—the most defensible
classification is:

**an asymmetric cross-hierarchy peer-forwarding failure for PEG→TCSS/TBT
posted writes, after VT-d ingress; most likely a platform/root-complex routing
policy or limitation, with the exact downstream drop point still unproven.**

This is a root-cause class, not a component-level diagnosis and not a P2P fix.
Linux documents that peer routing between different PCI host bridges is not
generally guaranteed. Intel VT-d also permits platform restrictions on
translated peer forwarding after a host physical address is available. Those
facts are compatible with the observation, but neither identifies this
machine's exact drop point.

References:

- [Linux PCI P2PDMA documentation](https://docs.kernel.org/next/driver-api/pci/p2pdma.html)
- [Intel VT-d Architecture Specification, section 3.17](https://cdrdv2-public.intel.com/831418/vt-directed-io-spec.pdf)

## Offline replay

```sh
python3 experiments/iommu-mapping/replay.py
python3 -m unittest discover \
  -s experiments/iommu-mapping/vtd-emission -p 'test_*.py'
```

The validator is fail-closed: requester, direction, PASID state, symbolic IOVA,
reason text, control sequence, retention and the absence of the RAM fallback
must all match. The tests mutate those fields and never access hardware.

The public package intentionally omits complete boot/kernel logs, GPU UUIDs,
full inventories, private filesystem paths, binaries, kernel modules, initrd
and deployment scripts. Consequently it reproduces qualification of the
published scientific record, not the private boot image or binary build.
