# USB4 counters around GPU transfers — 27 October 2026

**The bidirectional P2P problem remains unresolved.** This adds a working diagnostic driver and measured evidence, not a transport fix.

The normal Ubuntu kernel exposes read-only Thunderbolt path configuration (`CONFIG_USB4_DEBUGFS_WRITE` is disabled). The USB4 specification also restricts changes after a path becomes valid. Rather than changing live path registers, the opt-in [kernel patch](kernel/thunderbolt-counters.patch) assigns counters during normal PCIe path creation. The existing connection manager clears the selected sets and programs CounterID/CE when activating the path. Arbitrary debugfs register writes remain disabled.

The module was built from the exact Ubuntu `linux-source-7.0.0=7.0.0-38.38` package, SHA-256 `997a13a0c7fd0172a93b0c1ae9a4ffc7d3cbbf91d2fdd91d85334193580687de`, against `7.0.0-38-generic`. Source hashes are in [kernel-source-provenance.json](kernel/kernel-source-provenance.json). The include and patch are GPL-2.0-only, as part of the Linux Thunderbolt driver. No compiled deployment image is published here.

## Scope of the driver

The `cask_pcie_counters` parameter defaults to false and is read-only after module load. It selects only AHWSA/BIOS 1.26 and the observed two-router Intel `8087:463e` / ASMedia `00b8:2463` topology. Existing active paths are skipped. Counter ownership and supported bounds are checked before assigning anything.

| Measurement point | Router/adapter | Counter set | Observed response |
|---|---|---:|---|
| Host PCIe ingress | `0-0/port8` | 0 | Responds to CPU MMIO control |
| Host lane ingress | `0-0/port1` | 1 | Responds to CPU MMIO control |
| Dock lane ingress | `0-1/port1` | 1 | Responds to CPU MMIO control |
| Dock PCIe ingress | `0-1/port3` | 0 | Remains zero, including successful traffic |

The lane set is separate from control Hop0/counter0. Routing, credits and flow-control policy are not changed by the patch. The standard connection-manager lifecycle handles activation and teardown. All experiments used a temporary native Linux environment in RAM, mounted only the results ESP, and had an independent approximately 182-second return watchdog. Production services and training remain stopped at the owner's request.

## Three runs, with separate qualification

1. **[CPU configuration reads](cpu-config/results/qualified.json): negative calibration.** Counter setup and restoration succeeded, but the dock PCIe counter stayed zero during 64 PCI configuration reads. The strict observer stopped before the 1,024-read group. This run is deliberately classified `incomplete_preserved`; it must not be presented as successful calibration.
2. **[CPU BAR0 MMIO](cpu-mmio/results/qualified.json): completed measurement.** All 64 + 16,384 measured reads of A2000 `NV_PMC_BOOT_0` returned `b76000a1`, plus two reference reads outside measurement windows. Only PCI Command Memory Space Enable was leased (`0000→0002→0000`); Bus Master Enable remained off. The mapping was read-only, and two idle intervals were recorded. Three counters rose clearly above measured idle. The dock PCIe counter still stayed zero. The original command, module and four paths were verified after restoration.
3. **[GPU transfers](gpu/results/qualified.json): completed measurement, 12 passes / 24 failures.** The earlier 36-case same-allocation CE/SM protocol was reused. Removing the observer calls restores the original GPU source byte-for-byte. NVIDIA RM/UVM, payload capture, CUPTI and PCI diagnostics are unchanged. There are 18 observed CE and 18 observed SM operations, 288 GPU counter sample rows, and complete raw captures of all 36 payloads.

For each GPU case, owner initialization, sentinel verification, context checks, the pre-transfer PCI snapshot and CUPTI setup occur before the counter windows. A 20 ms idle interval precedes the operation. Transfer counters bracket the GPU operation and stream synchronization, before the CUPTI flush, post-transfer PCI snapshot and owner readback. Paths are checked before and after. After confirmed completion, NVIDIA modules were unloaded normally before tunnel teardown; the original Thunderbolt module was reloaded and all four original paths verified. No forced module removal was used.

## Observed contrast

These are **approximate excess counter increments over the per-case idle estimate**, rounded, for 1 MiB SM cases. They are not decoded PCIe TLP counts or a bandwidth measurement.

| Executing GPU / operation | Data | Host PCIe ingress | Dock lane ingress |
|---|---|---:|---:|
| A2000 PUSH before | Correct | 7,974 | 7,968 |
| A2000 PULL | Incorrect | 13,179 | 13,366 |
| A2000 PUSH after | Correct | 7,981 | 8,085 |
| Ada PUSH before | Sentinel retained | 42 | 130 |
| Ada PULL | `ffffffff` | 18 | 13 |
| Ada PUSH after | Sentinel retained | 18 | 35 |

Full values, elapsed times and the estimation method are in [counter-analysis.json](gpu/counter-analysis.json). CE cases show the same broad contrast. No dropped-packet increments were observed in the exposed counters. Successful captures contain the synthetic expected pattern; failed writes retain the synthetic sentinel; failed reads contain only `ffffffff`. The full [payload analysis](gpu/payload-analysis.json) includes first/last mismatch, class runs, repeated blocks and addressing-alias checks.

**Inference:** Ada-executed operations add little observed traffic at host USB4 PCIe ingress and dock lane, while A2000-executed operations add substantial traffic, including failed PULLs. This is compatible with failure before the observed USB4 ingress for Ada operations. It does not distinguish the requesting GPU, its configuration/driver and the Intel host fabric. The A2000 PULL result also demonstrates why traffic presence is insufficient to establish correct delivery.

## Limits

- The dock PCIe counter is uncalibrated for these operations. Its zero cannot establish absence of packets or identify the P2P fault.
- Counters aggregate USB4 transport traffic. They do not expose PCIe opcode, requester ID, tag, completion status or a physical packet trace. CPU/driver traffic and sequential counter-read overhead are included.
- Idle subtraction assumes comparable background over adjacent intervals. It is an empirical comparison with timing uncertainty, not proof of a unique failing component.
- The native experimental NVIDIA teardown still reports its bookkeeping warnings; selected research kernel lines are preserved. No production, atomics, NCCL or training qualification is claimed.
- The [Linux P2PDMA documentation](https://docs.kernel.org/driver-api/pci/p2pdma.html) explains that forwarding between PCIe hierarchy domains is not generally defined. Its generic allowlist is not a hardware routing fix, and these NVIDIA experiments do not establish that adding an allowlist entry would solve this machine.
- Full boot logs, PCI configuration dumps, disk/service inventories and deployment images remain private. GPU/device identifiers in published text are consistent placeholders. Original binary hashes describe private tested artifacts; redacted sources and build paths can change rebuilt hashes.

## Reproduce the offline checks

```sh
python3 experiments/usb4-counters/replay.py
python3 -m unittest discover -s experiments/usb4-counters/cpu-config -p 'test_*.py'
python3 -m unittest discover -s experiments/usb4-counters/cpu-mmio -p 'test_*.py'
python3 -m unittest discover -s experiments/usb4-counters/gpu -p 'test_*.py'
c++ -std=c++17 -O1 -g -fsanitize=address,undefined experiments/usb4-counters/cpu-config/test_tb_counter.cpp -o /tmp/cask-counter-test
/tmp/cask-counter-test
c++ -std=c++17 -O1 -g -fsanitize=address,undefined experiments/usb4-counters/cpu-mmio/test_mmio.cpp -o /tmp/cask-mmio-test
/tmp/cask-mmio-test
```

These checks do not access the GPUs. The GPU validator's fixture is explicitly synthetic, assembled for parser testing; it is separate from the actual `results/` run. There are 38 C++ counter parser/ownership/saturation checks, seven command-lease lifecycle/failure scenarios, and valid/negative Python fixtures. `replay.py` requalifies all three actual runs and independently rechecks every word of the published GPU payloads.

To rebuild the diagnostic kernel module, obtain the pinned Ubuntu source and matching headers, extract its `drivers/thunderbolt/` subtree, copy `kernel/cask_pcie_counters.inc` beside `tunnel.c`, apply `kernel/thunderbolt-counters.patch`, then build that subtree with the matching kernel's external-module build interface. No automatic installation or flash command is provided. The default-off identity and topology guards are part of the experimental scope.

## Firmware-policy follow-up

Static analysis of the actual historical BIOS identifies an RPL client FSP image with an `ADLUPD_S` signature and UPD size `0x1068`. The matching RaptorLakeP client header places `CpuPcieRpPeerToPeerMode[4]` at `0xFAB`. Binary references trace it through the CPU PCIe policy GUID to bit4 at the same per-port policy offset already tested through `SaSetup[0x3E3]` / `EnablePeerMemoryWrite`. It is not a newly demonstrated independent control. Template defaults do not establish runtime policy values.

[Binary assertions and module hashes](firmware-policy-trace.json), [Intel FSP header](https://github.com/intel/FSP/blob/master/RaptorLakeFspBinPkg/Client/RaptorLakeP/Include/FspsUpd.h), [policy GUID reference](https://github.com/tianocore/edk2-platforms/blob/master/Silicon/Intel/AlderlakeSiliconPkg/SiPkg.dec).

The router reports ASMedia `0xb8:0x2463`, generation4, and no `nvm_version` attribute. This does not identify an AOOSTAR PCB or a qualified firmware update. No SPI/NVM update was performed in these experiments.

The counter layout and lifecycle were checked against the official [USB4 specification and connection-manager guide bundle](https://www.usb.org/sites/default/files/USB4%20Specification%20November%202025.zip), including the restriction on edits to valid paths and the saturating 64-bit received / 32-bit dropped counter fields.
