# Full-payload diagnostics for the PUSH/PULL experiment

This probe records the complete destination payload so that a failed transfer can
be described more precisely than pass/fail. It does not change firmware or attempt
a new P2P fix. The [completed native rerun](results/native-20261021/README.md)
still has 18 failures in 24 cases: failed PUSH buffers match their entire initial
sentinel, successful PUSH buffers are entirely correct, and every PULL word is
`ffffffff`. The original results remain in the
[historical archive](../../archive/p2p-next-investigation-20261021/native-pushpull-results/).

Local validation passed 170 C++ checks and 33 Python tests. These are
CPU-only synthetic checks of capture and analysis, not evidence of successful GPU
transfers. Native results are reported separately with their logs and payload files.

## What stays comparable

`peer_payload_capture.cu` derives from the archived
[`peer_pushpull_cupti.cu`](../../archive/p2p-next-investigation-20261021/native-pushpull-probe/peer_pushpull_cupti.cu).
It preserves the 24 cases: PUSH/PULL, both source directions, SM/CE, and payloads
of 4 B, 64 KiB and 1 MiB. The GPU kernel, allocations, seeds, initialization,
transfer calls, synchronization and case order are retained. The original trace
and comparison output remains available.

Capture happens after the existing synchronized destination readback. Only the
active payload is saved, never the unused tail of an allocation. File writes and
`fsync` add time between cases, so this version is not a timing-identical replay
or a performance benchmark.

PUSH and PULL still use separate allocations and peer mappings. In the archived
run, the Ada peer window was BAR1 + `0x400000` for PUSH receive and BAR1 +
`0xc00000` for PULL send. This version does not remove that experimental
confound. A future comparison using the same physical allocation and mapping
for peer reads and writes needs its own explicitly documented protocol.

## Captured evidence

Each case produces two files:

- `case-NNN.observed.u32le`: the complete observed destination payload, encoded
  explicitly as little-endian 32-bit words.
- `case-NNN.json`: schema, case ID, engine, mode, executor, source/destination,
  byte count, seed, pattern identifier, GPU virtual addresses and comparison
  counts, with first and last mismatch word offsets.

The 24 raw files total 8,912,928 bytes, approximately 8.5 MiB, plus small JSON
metadata files. The source pattern and initial destination values can be
reconstructed from the recorded seed and pattern version.

The primary classes are mutually exclusive:

| Class | Meaning |
|---|---|
| Correct | Observed word equals the expected source word at this offset. |
| Initial-sentinel match | Observed word equals the initial destination value at this offset. |
| Other | Neither of those comparisons matches. |

The sentinel is the bitwise complement of the expected word. It is always
different from that expected word at the same offset, but can equal a source
word at another offset. With the archived 1 MiB seeds there are **8 such
cross-offset coincidences for source 0 and 14 for source 1**; the archived 4 B
and 64 KiB cases have none. An initial-sentinel match therefore describes the
observed value, rather than proving that no write occurred.

The existing source pattern is an invertible 32-bit mix of index XOR seed. The
offline analyzer reconstructs source indices, counts matching words at other
offsets independently of the primary classes, and reports displacement patterns,
contiguous runs of those primary classes, and repeated 64-byte and 4-KiB blocks.
It also records constant-value statistics and file hashes.

Every 32-bit value has an inverse under this pattern, so only indices inside the
active source range count as source-word matches. Even an in-range match can
occur accidentally. A repeated block, especially an all-zero or all-ones block,
does not prove an addressing alias. These observations help describe a failure;
they do not identify its cause in the requester, mapping, bridge or host fabric.
`direct_route_proven` remains false.

## Files and offline checks

| File | Purpose |
|---|---|
| `peer_payload_capture.cu` | Derived native CUDA/CUPTI probe. |
| `payload_capture.h` | CPU-side classification and exclusive raw/JSON capture. |
| `analyze_payloads.py` | Validate metadata and payloads, then produce detailed per-case analysis. |
| `validate_run.py` | Cross-check the native result log and captured payload directory. |
| `test_payload_capture.cpp` | CPU fixtures for classification, bytes, metadata and output preservation. |
| `test_analyze_payloads.py` | CPU fixtures for pattern inversion, payload interpretation and malformed input. |
| `test_validate_run.py` | Protocol fixtures rejecting missing, reordered or inconsistent case evidence. |

Run the following from this directory, using Python 3.10 or newer. Keep generated binaries and reports in
the ignored `verification-output/` directory; do not add them to Git.

```sh
mkdir -p ../../verification-output/payload-diagnostics
c++ -std=c++17 -Wall -Wextra -Werror -pedantic \
  test_payload_capture.cpp \
  -o ../../verification-output/payload-diagnostics/test_payload_capture
../../verification-output/payload-diagnostics/test_payload_capture
python3 -m unittest discover -s . -p 'test_*.py' -v
```

The C++ test creates a new private temporary directory and prints its location.
An optional argument specifies a new output parent instead. It deliberately
retains negative-test fixtures, including an orphan symlink, so that whole
directory is not a valid native run. Its valid case files can be inspected
individually through the analyzer's Python API.

For a collected native run:

```sh
python3 analyze_payloads.py /path/to/run/payloads \
  --output ../../verification-output/payload-diagnostics/payload-report.json
python3 validate_run.py /path/to/run/result.log /path/to/run/payloads \
  --output ../../verification-output/payload-diagnostics/run-validation.json
```

Choose new report filenames for each invocation: existing reports are not
overwritten. The analyzer checks the actual payload against the recorded
counts; metadata alone is not sufficient evidence of a completed transfer.

## Native build and laboratory prerequisites

This is a laboratory probe, not a portable stock-driver P2P enabler. Reproduction
depends on the same experimental driver and `libcuda` environment documented in
the archive. Successful compilation does not establish driver compatibility or
make unsupported P2P work.

The following example targets the CUDA 12.6 Linux toolkit, statically links the
CUDA runtime and emits SM 8.6 and SM 8.9 device code. The archived include
directory supplies `pcie_diag.h` and `cupti_trace.h`.

```sh
P2P_CUDA_ROOT=/usr/local/cuda-12.6
mkdir -p ../../verification-output/payload-diagnostics
"$P2P_CUDA_ROOT/bin/nvcc" -O2 -std=c++17 --cudart=static \
  -gencode arch=compute_86,code=sm_86 \
  -gencode arch=compute_89,code=sm_89 \
  -I ../../archive/p2p-next-investigation-20261021/native-pushpull-probe \
  -I "$P2P_CUDA_ROOT/include" \
  peer_payload_capture.cu \
  -L "$P2P_CUDA_ROOT/lib64" \
  -L "$P2P_CUDA_ROOT/lib64/stubs" \
  -lcuda -lcupti -ldl -Xcompiler -pthread \
  -o ../../verification-output/payload-diagnostics/peer_payload_capture
```

The CUDA stub library is for linking only. Runtime loading must resolve the
intended experimental `libcuda` and compatible CUPTI library; the stub directory
must not be used as a runtime library path.

The source deliberately pins the native laboratory topology:

| Device index | Expected PCI address | Role |
|---|---|---|
| 0 | `0000:01:00.0` | Internal RTX 2000 Ada |
| 1 | `0000:06:00.0` | External RTX A2000 |

Before execution, `CASKLOGIC_GPU0_UUID` and `CASKLOGIC_GPU1_UUID` must contain the
expected device UUIDs as exactly **32 lowercase hexadecimal characters**, without
the `GPU-` prefix or hyphens. No real UUIDs are distributed here. The probe checks
both those identities and the pinned PCI addresses, requires exactly two GPUs,
and requires access to `/dev/kmsg` for its existing trace markers.

The executable takes one argument: a **new, nonexistent output directory**.
For example, in an already prepared and verified laboratory environment:

```sh
../../verification-output/payload-diagnostics/peer_payload_capture \
  /path/to/new-run/payloads
```

Capture creates private files with exclusive creation and refuses to reuse an
existing output directory. Its errors abort the protocol; a missing, partial or
invalid metadata file must not be treated as a completed case. Preserve the
standard output as `result.log` together with the full run evidence. A completed
probe may still report transfer failures: successful capture and correct GPU
data are separate results.
