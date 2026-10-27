# ABI 5: host-mediated CPU-MMIO relay

## Qualified outcome

ABI 5 copied **4 KiB (1,024 32-bit words)** from private internal-GPU VRAM
to private external-GPU VRAM. Both allocations were exposed temporarily through
driver-managed BAR1 mappings. During the relay, each word followed this path:

```text
source BAR1 MMIO -> CPU general-purpose register -> destination BAR1 MMIO
```

The owner-GPU readback and an independent CPU readback both found zero payload
or guard mismatches. The source and its guards remained intact. There was no
host payload buffer and no RAM staging during the relay; the host validation
buffer was allocated only after the relay completed.

This is a qualified **host-mediated workaround**, not PCIe P2P. The CPU
initiates and terminates every MMIO load and store. It does not repair the
missing Ada-to-A2000 peer path, and it is not GPUDirect, ordinary CUDA peer
access, peer DMA, or a production transport.

## Hardware diagnosis

The evidence now localizes the blocked P2P direction to the Alder Lake root
complex/fabric path from the internal PEG branch toward the TCSS/Thunderbolt
branch, downstream of VT-d ingress and before the observed USB4 tunnel ingress:

1. ABI 4 produced an exact VT-d `DMA Write NO_PASID` permission fault for the
   internal GPU's test write, proving that the request reached VT-d.
2. With a writable translated mapping, the same direction remained 0/2 while
   the reverse direction was 2/2 and all 8/8 RAM controls passed.
3. A CPU write to the same live external-GPU BAR1 target passed, so that target
   allocation and host route were writable.
4. USB4 counters showed substantial traffic for the successful reverse write,
   but no corresponding tunnel-ingress traffic for the failed forward write.
5. ABI 5 independently proved that host-originated MMIO can read the internal
   BAR1 source and write the external BAR1 destination correctly.

Intel's official Alder Lake-H datasheet, section 2.15.1, states that peer
writes are supported only between PEG ports. The external GPU in this topology
is below TCSS/Thunderbolt, not a second PEG port. This documented topology limit
is consistent with the measurements and supports classifying the blocker as a
**platform hardware peer-routing limitation**, rather than an IOVA permission
or payload-buffer defect. See the [12th Generation Intel Core Processors
Datasheet, Volume 2, section 2.15.1](https://cdrdv2-public.intel.com/710723/710723-003.pdf).

The public documentation does not expose a counter or register that identifies
one internal silicon unit. Consequently, this diagnosis names the unsupported
PEG-to-TCSS route and its observed boundaries; it does not claim a transistor-
level or single-block fault. Changing the GPU placement or platform was outside
the experiment's constraints.

## Result and limits

The sanitized [qualified result](qualified-result.json) records:

- correct transfer of 4,096 bytes / 1,024 words;
- zero source, destination, or guard mismatches;
- no host payload buffer during the relay and no RAM staging;
- owner-GPU and secondary CPU validation after the relay;
- restored stock runtime and no new scoped Xid, DMAR, or AER report;
- `pcie_p2p=false`, `p2p_solution_claimed=false`, and
  `performance_claimed=false`.

One diagnostic execution reported 697,839 ns, arithmetically about 5.87 MB/s.
That single 4 KiB observation includes fixed setup, ordering, and flush costs;
it is **not a bandwidth, latency, scalability, or production-performance
benchmark**.

The public package contains only this explanation, a sanitized result, and a
small offline validator. It intentionally omits raw logs, GPU UUIDs, bus and
physical addresses, private filesystem paths, executables, NVIDIA modules, and
NVIDIA-derived source.

## Offline validation

```sh
python3 experiments/cpu-mmio-relay/validate.py
python3 -m unittest discover \
  -s experiments/cpu-mmio-relay -p 'test_*.py'
```

These commands inspect only the sanitized JSON. They do not access hardware or
reproduce the private driver run.
