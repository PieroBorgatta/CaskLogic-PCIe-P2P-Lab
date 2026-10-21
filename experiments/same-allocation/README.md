# Peer reads and writes using the same allocations

This experiment compares peer writes and peer reads while retaining the same
allocation on each GPU. It follows the
[full-payload diagnostics](../payload-diagnostics/README.md), whose PUSH and PULL
cases used different allocations and peer windows. The
[completed native run](results/native-20261021/README.md) recorded **36 cases:
12 passed and 24 failed**. Only the A2000's `PUSH_BEFORE` and `PUSH_AFTER` cases
passed. CUPTI qualified 18 CE and 18 SM cases with no dropped records or trace
errors. **Bidirectional P2P remains unresolved.**

The existing native Linux kernel, experimental NVIDIA driver modules, `libcuda`
and GPU transfer kernel are unchanged. The probe changes allocation lifetime,
access permissions, case ordering and source seeds, while retaining synchronized
owner initialization, full destination capture and CUPTI observation.

## Protocol

The program creates **two persistent 8 MiB device allocations**, one owned by each
GPU. Each is mapped once and granted **read/write access on both GPUs**. Their
allocation handles and virtual addresses remain unchanged throughout all cases;
they are released only after the experiment. Only the active payload prefix is
initialized, transferred and captured.

| GPU index | Native PCI address | Device |
|---|---|---|
| 0 | `0000:01:00.0` | Internal RTX 2000 Ada |
| 1 | `0000:06:00.0` | External RTX A2000 through USB4 |

There are **12 brackets and 36 cases**, with 18 requested copy-engine transfers
and 18 SM-kernel transfers. Each bracket fixes the executing GPU, engine and
payload size, then performs these three operations:

| Step | Source | Destination | Peer operation issued by executor |
|---|---|---|---|
| `PUSH_BEFORE` | Executor's allocation | Other GPU's allocation | Write |
| `PULL` | Other GPU's allocation | Executor's allocation | Read |
| `PUSH_AFTER` | Executor's allocation | Other GPU's allocation | Write |

The executor order is **A2000 first, then Ada**. For each executor, payload sizes
are **4 B, 64 KiB and 1 MiB**, in that order. For each size, the CE bracket runs
before the SM bracket. This makes the first peer read occur after a write through
the same remote allocation, with another write afterward.

Before every case, the source owner writes and reads back the expected pattern,
and the destination owner writes and reads back its initial sentinel. Both GPUs
are synchronized. The probe checks allocation ownership and read/write access at
both ends of each allocation before and after every case. It also records the
executing context and stream. These checks must succeed independently of whether
the peer transfer produces correct bytes.

The CE request remains `cuMemcpyDtoDAsync`; the SM operation uses the unchanged
`peer_push_kernel`. **The requested executor must be qualified by correlated
CUPTI activity**, including its actual device/context/stream, rather than inferred
from the API call alone. A completed run requires 18 observed CE cases, 18 observed
SM cases, and no dropped or erroneous trace records.

## Fresh source patterns

Every case uses a new deterministic seed. Arithmetic below uses unsigned 32-bit
values, with multiplication reduced modulo `2^32`; `id` is the global case number
from 1 through 36, and `executor` is 0 or 1:

```text
base_seed = 0x6b8b4567 XOR bytes XOR (0x13579bdf * (executor + 1))
            XOR (0 for CE, 0x2468ace0 for SM)
seed      = base_seed XOR (id * 0x9e3779b9)
```

Each source word is the existing invertible 32-bit mix of `word_index XOR seed`.
The initial destination word is its bitwise complement. Changing the seed between
the two PUSH cases prevents the earlier expected payload from being accepted as
the later expected payload without a fresh transfer. The recorded seed and
pattern version allow offline reconstruction.

A sentinel match describes the observed value; it does not prove that no write
occurred. A sentinel can coincide with a source word at another offset. Likewise,
repeated blocks or source-pattern matches at displaced offsets do not by themselves
prove an addressing alias.

## Evidence and qualification

Each case saves `case-NNN.observed.u32le` and `case-NNN.json`. The **36 raw payloads
total 13,369,392 bytes**. Sidecars record identity, seed, active byte count, virtual
addresses, first/last mismatch positions, and counts of correct words,
initial-sentinel matches and other values. Capture refuses to reuse an existing
output directory or overwrite a file.

[`validate_run.py`](validate_run.py) reconstructs the required ordering and seeds,
checks two persistent allocation identities, 292 access-query records, 72 owner
initialization checks, the complete captured bytes, and raw CUPTI correlations.
It uses the sibling
[`analyze_payloads.py`](../payload-diagnostics/analyze_payloads.py) for byte-level
classification, source-index inversion, displacement and repetition statistics.
A transfer failure can be valid diagnostic evidence when all protocol checks
pass; protocol validity is separate from numerical success.

Virtual addresses, allocation handles and CUDA access queries establish software
mapping continuity. A separate audit of `kernel.log` is needed to compare the
driver's physical-address, BAR1 and PTE mapping records; the included
[`audit_mappings.py`](audit_mappings.py) checks the completed run's two chains
and their lifetimes using the archived arithmetic parser. The
[result report](results/native-20261021/README.md#evidence-and-replay) includes
the exact replay command. **Neither software audit
proves that hardware used those mappings**, captures PCIe TLPs, or establishes
where an unsuccessful read or write was stopped. CUPTI also does not prove the
absence of an unobserved internal staging path. `direct_route_proven` remains
false.

The experiment can narrow the different-allocation explanation. It cannot by
itself distinguish a requester issue from a bridge, host fabric, hardware mapping
or driver issue. Architecture remains coupled to internal/external placement in
this machine. The additional initialization and file synchronization also make
this unsuitable as a performance benchmark.

## Offline validation

Run these commands from this directory with a C++17 compiler and Python 3.10 or
newer. Generated outputs belong in the ignored `verification-output/` directory.
These CPU fixtures validate the instrumentation; they are not GPU-transfer tests.

```sh
mkdir -p ../../verification-output/same-allocation
c++ -std=c++17 -Wall -Wextra -Werror -pedantic \
  test_capture_limit.cpp \
  -o ../../verification-output/same-allocation/test_capture_limit
../../verification-output/same-allocation/test_capture_limit
python3 -m unittest discover -s . -p 'test_*.py' -v
```

The C++ fixture retains its private temporary directory for inspection. For a
collected hardware run, supply the actual captured directory and a new report
filename:

```sh
python3 validate_run.py /path/to/run/result.log /path/to/run/payloads \
  --output ../../verification-output/same-allocation/run-validation.json
```

Keep `kernel.log`, the pre-driver PCI snapshots, package provenance and recovery
records with the run. A successful offline validation does not replace the
separate driver mapping audit or turn failed transfers into a solution.

## Native build and prerequisites

This probe depends on the experimental driver environment documented in the
archive. It is not a stock-driver P2P enabler or an automatic firmware installer.
Compilation alone does not establish compatibility.

The example below targets CUDA 12.6 on Linux, uses the local CUPTI trace header,
and obtains `pcie_diag.h` from the archived probe. It emits device code for both
SM 8.6 and SM 8.9:

```sh
P2P_CUDA_ROOT=/usr/local/cuda-12.6
mkdir -p ../../verification-output/same-allocation
"$P2P_CUDA_ROOT/bin/nvcc" -O2 -std=c++17 --cudart=static \
  -gencode arch=compute_86,code=sm_86 \
  -gencode arch=compute_89,code=sm_89 \
  -I ../../archive/p2p-next-investigation-20261021/native-pushpull-probe \
  -I "$P2P_CUDA_ROOT/include" \
  peer_same_allocation.cu \
  -L "$P2P_CUDA_ROOT/lib64" \
  -L "$P2P_CUDA_ROOT/lib64/stubs" \
  -lcuda -lcupti -ldl -Xcompiler -pthread \
  -o ../../verification-output/same-allocation/peer_same_allocation
```

The CUDA stub library is for linking only. Runtime loading must select the
intended experimental `libcuda` and compatible CUPTI library; do not put the stub
directory on the runtime library path.

Execution requires exactly the two GPUs at the PCI addresses above, access to
`/dev/kmsg`, and `CASKLOGIC_GPU0_UUID` / `CASKLOGIC_GPU1_UUID` set to their expected
UUIDs as 32 lowercase hexadecimal characters without hyphens or the `GPU-` prefix.
No real UUIDs are published here. Run only in an already prepared, idle laboratory
environment with the native boot and recovery procedure verified separately.

The executable takes a single argument: a new, nonexistent output directory.
Preserve standard output as `result.log`. Exit status 0 requires a complete trace
and all payloads correct; status 5 denotes a completed, qualified protocol with
one or more numerical failures. An interrupted run or another error must not be
reported as a completed 36-case experiment.
