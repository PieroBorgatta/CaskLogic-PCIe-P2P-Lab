# Same-allocation PUSH / PULL / PUSH — 21 October 2026

**P2P remains unresolved: 12 passing and 24 failing comparisons.** This native
run keeps two allocations and their peer windows active throughout all cases.
The A2000 can write correct data into the same Ada allocation both before and
after failing to read from it.

| Operation and payload direction | Cases | Complete observed destination |
|---|---:|---|
| PUSH A2000 → Ada, before and after PULL | 12 passed | Every word is correct. |
| PUSH Ada → A2000, before and after PULL | 12 failed | Every word matches its initial sentinel. |
| PULL Ada → A2000, executed by A2000 | 6 failed | Every word is `ffffffff`. |
| PULL A2000 → Ada, executed by Ada | 6 failed | Every word is `ffffffff`. |

Each direction includes CE and SM at 4 B, 64 KiB and 1 MiB. Every failed case
mismatches from word 0 through the final word; no partially correct payload was
observed. All **36 complete raw captures total 13,369,392 bytes**. Independent
inspection found only the known synthetic source patterns, sentinels and all-ones.

## What this controls

There are exactly two persistent 8 MiB VMM allocations, both RW on both GPUs.
Each of 12 brackets holds the executor, engine and size fixed while running
`PUSH_BEFORE → PULL → PUSH_AFTER`. Owners initialize and verify their data before
every case. A fresh seed changes the source pattern each time; the 36 active
source-value sets are pairwise disjoint, so an earlier source word cannot be
accepted as a fresh expected word at another offset.

The [previous full-buffer run](../../../payload-diagnostics/results/native-20261021/README.md)
used separate PUSH/PULL allocations. That difference does not explain the
asymmetry observed here: the **same Ada memory window receives correct peer
writes and fails peer reads from the same A2000 executor**. Successful writes
also resume immediately after each failed read. This is an operation/direction
distinction, not evidence for a universal Ampere-to-Ada-only rule.

Both CUDA allocation identities and the instrumented driver records remain
stable throughout all cases:

| Allocation owner | Shared VA | BAR1 base + window offset | DMA / first decoded peer PTE |
|---|---|---|---|
| Ada | `710c32e00000` | `4000000000 + 400000` | `4000400000` |
| A2000 | `710c33600000` | `4600000000 + 400000` | `4600400000` |

Addresses are hexadecimal observations from this run. Both peer mappings are RW,
with 2 MiB pages. Each tested payload fits within the first recorded page.
Nonce/VA/handle joins, BAR1/DMA arithmetic and RM/UVM PTE records agree. No mapping
mutation is recorded during the cases; both windows are destroyed after the
last comparison. The audit contains 34 peer-chain arithmetic checks and 102
arithmetic checks overall.

These records describe the mappings submitted by software. They do **not** read
back the GPU's hardware MMU, capture PCIe TLPs, identify the component returning
unsuccessful reads, or prove absence of hidden internal staging. Requester,
driver/hardware mapping, Intel fabric and USB4-path explanations remain open.
GPU architecture is still coupled to internal/external placement.

## Additional observations

Among 438 PCI snapshots, the only changes are Received Master Abort
(`PCI_STATUS 0010→2010`) at the first CE PULL for each executor:

- Case 2: A2000 `06:00.0` and its root port `00:07.0`.
- Case 20: Ada `01:00.0` and its root port `00:01.0`.

No AER transitions were recorded. Status is sticky, so subsequent unchanged
snapshots cannot establish that later PULLs produced no additional errors.

Sentinel equality means no visible change relative to the prefill, not proof
that no write was issued. Cross-offset source/sentinel coincidences and uniform
all-ones repeats are not evidence of addressing aliases.

The known experimental-driver teardown defect remains: four IOVAS leftovers
and eight assertions, starting about 375 ms after `context_exit_begin`, after
the completed comparisons and window destruction. No NVIDIA Xid was recorded.
The driver is not qualified for production.

## Validation and restoration

- 36 cases in 12 groups; 72 owner initialization checks, 74 GPU identity checks
  and 292 VMM access queries passed.
- Raw CUPTI correlations independently qualify 18 CE and 18 SM operations on
  the intended executors, with zero dropped records and trace errors.
- All captured bytes, counts, first/last mismatch offsets and sidecars agree.
- All 2,295 initrd members were compared with the pinned baseline. Only `init`
  and the probe executable change content. Kernel, driver modules, `libcuda`
  and CUPTI are unchanged; repackaging metadata differences are documented.
- Original PEG/TCSS CCFG values remain `04008077` / `0e009077`. This run changes
  no BIOS/FSP image or driver code and performs no PCI configuration writes.
- The VM shut down cleanly; the native probe did not mount VM data disks.
  XCP-ng and the VM returned with both GPUs under the standard 595.99.02 driver.
  All 65 container definitions remain; all 52 previously running or restarting
  containers are present in those states. `ai-comfy-auth` was restarting both
  before and after, so this is not a claim that every service is healthy.
- The temporary EFI entry and ESP directory were removed after verified backup.
  Original boot files and boot order `0000,0001` were preserved.

## Evidence and replay

- [Complete sanitized program log](result.log) and [raw captures/sidecars](payloads/)
- [Full payload analysis](payload-analysis.json) and [protocol/CUPTI validation](validated-run.json)
- [Kernel driver and marker excerpt](kernel-driver-excerpt.log) and [mapping audit](mapping-audit.json)
- [Source provenance](source-provenance.json), [build manifest](build-manifest.json)
  and [full package comparison](package-comparison.json)
- [Restoration summary](restoration-summary.json)

GPU UUIDs are consistently replaced with fictional identifiers. Payloads and
sidecars are byte-for-byte unchanged. The kernel excerpt preserves every
`P2PTRC` event plus lines with `NVRM:` or `CaskLogicCE`; unrelated inventory is excluded. Complete original logs
and recovery backups are retained privately. Build metadata describes its
preparation-time state; the completed execution is established by the run logs.

From the repository root, with a new output filename:

```sh
python3 experiments/same-allocation/validate_run.py \
  experiments/same-allocation/results/native-20261021/result.log \
  experiments/same-allocation/results/native-20261021/payloads \
  --output /tmp/casklogic-same-allocation-validation.json

python3 experiments/same-allocation/audit_mappings.py \
  experiments/same-allocation/results/native-20261021 \
  --kernel-log kernel-driver-excerpt.log \
  --arithmetic-parser archive/p2p-tcss-bit-tests-20261021/driver-instrumented/analyze_p2ptrc.py \
  --output /tmp/casklogic-same-allocation-mappings.json
```

This validates diagnostic evidence offline. It does not establish a P2P fix.
