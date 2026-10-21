# Native rerun with complete payload capture — 21 October 2026

**Bidirectional P2P remains unresolved: 6 passing and 18 failing cases.** This
native rerun captures every destination word, addressing the community's request
to distinguish unchanged data, partial delivery and addressing patterns.

| Operation and data direction | Cases | Complete observed destination |
|---|---:|---|
| PUSH internal Ada → external A2000 | 6 failed | Every word equals its initial sentinel value. |
| PUSH external A2000 → internal Ada | 6 passed | Every word equals the expected source value. |
| PULL internal Ada → external A2000 | 6 failed | Every word is `ffffffff`. |
| PULL external A2000 → internal Ada | 6 failed | Every word is `ffffffff`. |

Each row includes SM and CE at 4 B, 64 KiB and 1 MiB. For every failed case,
the first mismatch is word 0 and the last is the final payload word. No case
contains a mixture of correct and incorrect words. The 24 raw captures total
**8,912,928 bytes**, with a JSON sidecar for each case.

The earlier log reported all mismatch counts but printed only the first bad
word. This rerun establishes the complete value distribution. It does not
retroactively reconstruct the unsaved words from the earlier execution.

## Interpretation

Keeping A2000 as executor, its PUSH into Ada succeeds while its PULL from Ada
fails. Ada memory is therefore not broadly unreachable in this experiment.
The observations distinguish remote writes from remote reads, while the cause
remains unresolved between requester behavior, mappings, Intel routing and the
USB4 path. GPU architecture remains confounded with physical placement.

An initial-sentinel match means equality to the prefill value, not proof that
no write was issued. The complete failed PUSH destination has **no visible
change** relative to that prefill. Its two 1 MiB captures contain eight values
that also equal source words at other offsets; these are the known intrinsic
source/sentinel coincidences, not new evidence of shifted writes. Successful
1 MiB PUSH captures likewise have fourteen cross-offset sentinel coincidences.
No nonuniform repeated 64-byte or 4-KiB blocks were found. Uniform repeats in
the all-ones PULL captures do not establish address aliasing.

The first CE PULL in each direction coincides with PCI status changing from
`0010` to `2010` (Received Master Abort) at its requester and upstream root:
case 13 on A2000 / D7, case 19 on Ada / D1. No new AER value transition was
recorded. Status is sticky, and these observations do not identify the component
that caused the unsuccessful reads.

PUSH and PULL still use **separate allocations and mappings**. A same-allocation
read/write comparison remains a distinct follow-up; this rerun does not provide
that control. CUPTI records are not a hardware transaction trace and do not
prove the absence of every possible hidden staging path.

## Validation and environment

- The complete log and dumps agree on all 24 cases and all word counts.
- 48 owner initialization checks passed; all 50 GPU identity checks and
  208 VMM access checks passed.
- The historical independent CUPTI auditor reconstructed 12 CE operations and
  12 SM kernels, with zero dropped records or trace errors.
- Native kernel, driver modules and CUDA libraries retain the previous pinned
  hashes. All 2,295 initrd members were compared; only `init` and the probe
  executable differ. The GPU kernel, allocations, transfer calls and case order
  are retained. Capture adds filesystem work between cases, so this is not a
  performance comparison.
- PEG/TCSS CCFG stayed at `04008077` / `0e009077` before and after the test.
  No BIOS image, FSP region, driver code or PCI configuration was changed.
- The experiment completed with `rc=5`, meaning numerical failures. The known
  IOVAS cleanup warnings remain present after the completed comparisons; this
  experimental driver is not qualified for production.
- The VM was shut down cleanly for the RAM-only boot; its data disks were not
  mounted by the probe. XCP-ng and the VM returned, both GPUs were visible under
  the standard driver, and all 52 previously listed containers were present.
  The temporary boot entry and ESP directory were removed after verified backup;
  original boot files and order were preserved.

## Evidence

- [Complete sanitized program log](result.log)
- [All raw payloads and metadata](payloads/)
- [Detailed word classifications](payload-analysis.json)
- [Protocol/payload validation](validated-run.json)
- [Independent CUPTI reconstruction](cupti-independent-log-audit.json)
- [Kernel driver and probe-marker excerpt](kernel-driver-excerpt.log)
- [Build manifest](build-manifest.json), [complete initrd comparison](package-comparison.json)
- [Restoration summary](restoration-summary.json)

GPU UUIDs in the public log use the same fictional identifiers as the archive.
Payload bytes and sidecars are unchanged. The kernel excerpt selects lines
containing `NVRM:` or `CaskLogicCE`; it excludes unrelated device inventory.
The full original logs and system backups are retained privately. Public file
hashes are in the repository's publication manifest.
Build metadata records its preparation-time state; execution is established by
`result.log` and `validated-run.json`.

Replay from the repository root, writing to a new report filename:

```sh
python3 experiments/payload-diagnostics/validate_run.py \
  experiments/payload-diagnostics/results/native-20261021/result.log \
  experiments/payload-diagnostics/results/native-20261021/payloads \
  --output /tmp/casklogic-payload-run-validation.json
```

This offline command checks diagnostic evidence; it does not access GPUs or
establish a P2P fix.
