#!/usr/bin/env python3
"""Singola prova P2P da 4 byte; eseguire solo nella VM Linux dedicata.

Non modifica registri PCIe. Il coordinatore host gestisce i gate e il loro
ripristino. Le librerie e i moduli di sistema non vengono sovrascritti.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

SERVICES = ["n3rdware-gpu-fan.service", "nvidia-persistenced.service",
            "nvidia-powerd.service", "nvidia-cdi-refresh.path",
            "nvidia-cdi-refresh.service"]
MODULES = ["nvidia", "nvidia_modeset", "nvidia_drm", "nvidia_uvm"]
PROGRAM_HASHES = {
    "peer_vmm_word": "612a93dd9f912941ad9870fdd9403265ca4216f0c3ebfbf2917925f24f872dc5",
    "peer_vmm_config_gate": "2f7f01412a273b32f442be9e523e98a6f4fdc5611ae7338e99ba4031693afae7",
}
LIBCUDA_HASH = "03271500dbda9456e3ba765270bd2609bef2631672809da50b19c67fb1f609a7"
PARAMS = "ForceP2P=0x11;RMForceP2PType=1;RMPcieP2PType=1;RMForceStaticBar1=0"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n")
    temp.replace(path)


def run(command, check=True, timeout=25):
    started = time.time()
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        record = {"epoch": started, "command": command, "rc": result.returncode,
                  "out": result.stdout, "err": result.stderr}
    except subprocess.TimeoutExpired as exc:
        record = {"epoch": started, "command": command, "timeout": timeout,
                  "out": str(exc.stdout or ""), "err": str(exc.stderr or "")}
        with (out / "events.jsonl").open("a") as stream:
            stream.write(json.dumps(record) + "\n")
        raise
    with (out / "events.jsonl").open("a") as stream:
        stream.write(json.dumps(record) + "\n")
    if check and result.returncode:
        raise RuntimeError(f"Comando fallito ({result.returncode}): {command}: {result.stderr}")
    return result


def loaded():
    return {name for name in MODULES if Path("/sys/module", name).exists()}


def restore(state):
    errors = []
    def attempt(command, check=True, timeout=25):
        try:
            return run(command, check, timeout)
        except Exception as exc:
            errors.append(str(exc))
            return None
    attempt(["docker", "rm", "-f", state["container"]], False, 15)
    for service in SERVICES:
        attempt(["systemctl", "stop", service], False)
    if state.get("driver_touched"):
        for module in reversed(MODULES):
            if module in loaded():
                attempt(["modprobe", "-r", module], True, 20)
    if state.get("driver_touched") and loaded():
        errors.append("Moduli NVIDIA ancora caricati: non dichiaro stock ripristinato")
    else:
        if state.get("driver_touched"):
            for module in MODULES:
                if module in state["loaded"]:
                    attempt(["modprobe", module], True, 35)
        for module, expected in state["srcversions"].items():
            path = Path("/sys/module", module, "srcversion")
            if not path.exists() or path.read_text().strip() != expected:
                errors.append("Srcversion stock non ripristinata: " + module)
        if not state["cdi_was_masked"]:
            attempt(["systemctl", "unmask", "--runtime", "nvidia-cdi-refresh.service"])
        for service in SERVICES:
            if state["services"].get(service) == "active":
                attempt(["systemctl", "start", service])
        attempt(["nvidia-smi", "--query-gpu=uuid,name,memory.total,power.limit", "--format=csv"], True, 20)
    dmesg = attempt(["dmesg"], False)
    if dmesg:
        (out / "dmesg-after.txt").write_text(dmesg.stdout)
    result = {"epoch": time.time(), "stock_restored": not errors, "errors": errors}
    write_json(out / "restore.json", result)
    print(json.dumps(result), flush=True)
    return not errors


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--trial-root", type=Path)
parser.add_argument("--module", type=Path)
parser.add_argument("--module-sha256")
parser.add_argument("--out", required=True, type=Path)
parser.add_argument("--program", choices=PROGRAM_HASHES, default="peer_vmm_config_gate")
parser.add_argument("--restore-only", action="store_true")
args = parser.parse_args()
out = args.out.resolve()
out.mkdir(parents=True, exist_ok=True)
if os.geteuid() != 0 or not sys.platform.startswith("linux"):
    parser.error("Richiede root nella VM Linux; nessuna esecuzione sul Mac")
lock = open("/run/lock/riscrivo-tcss-word.lock", "w")
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
state_file = out / "before.json"
if args.restore_only:
    sys.exit(0 if restore(json.loads(state_file.read_text())) else 70)
if state_file.exists():
    parser.error("Directory già usata: usare una nuova directory o --restore-only")
if not args.trial_root or not args.module or not args.module_sha256:
    parser.error("Specificare --trial-root, --module e --module-sha256 verificato")
root = args.trial_root.resolve()
module = args.module.resolve()
program = root / args.program
libdir = root / "libcuda-experiment"
assert sha(module) == args.module_sha256, "Hash modulo inatteso"
assert sha(program) == PROGRAM_HASHES[args.program], "Hash programma inatteso"
assert sha(libdir / "libcuda.so.1") == LIBCUDA_HASH, "libcuda non è la copia patchata attesa"
assert run(["systemctl", "is-active", "riscrivo-training.service"], False).stdout.strip() in {"inactive", "failed"}, "Training in corso"
assert run(["modinfo", "-F", "version", str(module)]).stdout.strip() == "595.99.02"
assert run(["modinfo", "-F", "vermagic", str(module)]).stdout.split()[0] == os.uname().release
present = loaded()
assert "nvidia" in present, "Stock non caricato: richiede stato iniziale noto"
srcversions = {}
for name in present:
    current = Path("/sys/module", name, "srcversion").read_text().strip()
    assert current == run(["modinfo", "-F", "srcversion", name]).stdout.strip(), "Modulo iniziale diverso dallo stock su disco"
    srcversions[name] = current
state = {"epoch": time.time(), "kernel": os.uname().release, "loaded": sorted(present),
         "driver_touched": False,
         "srcversions": srcversions, "container": "riscrivo-tcss-word-" + str(os.getpid()),
         "services": {s: run(["systemctl", "is-active", s], False).stdout.strip() for s in SERVICES},
         "cdi_was_masked": run(["systemctl", "is-enabled", "nvidia-cdi-refresh.service"], False).stdout.strip().startswith("masked"),
         "module": str(module), "module_sha256": args.module_sha256,
         "program": args.program, "program_sha256": sha(program), "libcuda_sha256": LIBCUDA_HASH}
write_json(state_file, state)
(out / "dmesg-before.txt").write_text(run(["dmesg"]).stdout)


def interrupted(signum, frame):
    raise RuntimeError("Interruzione segnale " + str(signum))


signal.signal(signal.SIGTERM, interrupted)
signal.signal(signal.SIGINT, interrupted)
exit_code = 70
try:
    run(["systemctl", "mask", "--runtime", "nvidia-cdi-refresh.service"])
    for service in SERVICES:
        run(["systemctl", "stop", service], False)
    users = run(["fuser", "/dev/nvidia0", "/dev/nvidia1", "/dev/nvidiactl", "/dev/nvidia-uvm"], False)
    assert users.returncode == 1, "GPU occupata o fuser non utilizzabile"
    state["driver_touched"] = True
    write_json(state_file, state)
    for name in reversed(MODULES):
        if name in loaded():
            run(["modprobe", "-r", name])
    assert not loaded(), "Scaricamento stock incompleto"
    run(["insmod", str(module), "NVreg_RegistryDwords=" + PARAMS], timeout=40)
    run(["modprobe", "nvidia_uvm"])
    run(["nvidia-smi", "--query-gpu=index,uuid,name,pci.bus_id", "--format=csv"])
    command = ["docker", "run", "--rm", "--name", state["container"], "--gpus", "all",
               "--network", "none", "--cpus", "2", "--memory", "2g", "--pids-limit", "128",
               "--mount", f"type=bind,src={out},dst=/trial",
               "--mount", f"type=bind,src={program},dst=/trial/{args.program},readonly",
               "--mount", f"type=bind,src={libdir},dst=/trial/libcuda-experiment,readonly",
               "-e", "LD_LIBRARY_PATH=/trial/libcuda-experiment:/usr/local/cuda/lib64:/usr/local/nvidia/lib64",
               "--entrypoint", "/trial/" + args.program, "casklogic-riscrivo:torch2.10-cu126"]
    result = run(command, False, timeout=65 if args.program.endswith("gate") else 25)
    (out / "gpu.txt").write_text(result.stdout + result.stderr)
    rows = [line for line in result.stdout.splitlines() if line.startswith(("REMOTE_READ ", "REMOTE_WRITE "))]
    complete = len(rows) == 4 and all("bytes=4 " in line for line in rows)
    valid = complete and result.returncode == 0 and all("valid=1" in line for line in rows) and "TOTAL_FAILURES 0" in result.stdout
    write_json(out / "gpu-result.json", {"complete": complete, "valid": valid, "rc": result.returncode, "rows": rows})
    exit_code = 0 if valid else (5 if complete else 6)
except Exception as exc:
    write_json(out / "error.json", {"error": str(exc), "epoch": time.time()})
    print(str(exc), file=sys.stderr, flush=True)
finally:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if not restore(state):
        exit_code = 70
sys.exit(exit_code)
