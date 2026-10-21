#!/usr/bin/env python3
"""Sonda temporanea D7:F0 CCFG[27:25], solo MS-01 i9-12900H verificato.

Default: sola lettura. --execute autorizza quattro casi temporanei, ciascuno
seguito dal ripristino confermato dell'intera parola originale. Non modifica
firmware, lock, ACS, driver o la root port della GPU interna.

Lo store hardware e eseguito da C volatile uint32_t; niente pwrite/memcpy,
scritture byte-wise o operazioni atomiche LOCK su MMIO.
"""

import argparse
import contextlib
import ctypes
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import signal
import struct
import subprocess
import sys
import time


ROOT_BDF = "0000:00:07.0"
HOST_BDF = "0000:00:00.0"
REG_OFFSET = 0xD0
PORT_ID = 0xC6
PEER_MASK = 0x0E000000
CASES = [("clear_bit25", 1 << 25), ("clear_bit26", 1 << 26),
         ("clear_bit27", 1 << 27), ("clear_bits25_26_27", PEER_MASK)]


class ProbeError(RuntimeError):
    pass


class Interrupted(ProbeError):
    pass


def require(condition, message):
    if not condition:
        raise ProbeError(message)


def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def monotonic_ns():
    # Python 3.6 sull'host XCP-ng non espone time.monotonic_ns().
    return int(time.monotonic() * 1_000_000_000)


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def save_new_json(path, payload):
    with path.open("x", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    fsync_dir(path.parent)


class Journal:
    def __init__(self, folder):
        self.file = (folder / "events.jsonl").open("x", encoding="utf-8")
        fsync_dir(folder)

    def log(self, kind, **payload):
        item = {"utc": stamp(), "monotonic_ns": monotonic_ns(),
                "event": kind, **payload}
        self.file.write(json.dumps(item, sort_keys=True) + "\n")
        self.file.flush()
        os.fsync(self.file.fileno())
        print(json.dumps(item, sort_keys=True), flush=True)

    def close(self):
        self.file.close()


def pci_read(bdf, offset, size):
    fd = os.open(f"/sys/bus/pci/devices/{bdf}/config", os.O_RDONLY)
    try:
        data = os.pread(fd, size, offset)
    finally:
        os.close(fd)
    require(len(data) == size, f"Lettura PCI incompleta: {bdf}+{offset:#x}")
    return data


def pci_u32(bdf, offset):
    return struct.unpack("<I", pci_read(bdf, offset, 4))[0]


def parse_id(value):
    try:
        vendor, device = (int(x, 16) for x in value.split(":"))
        if not (0 <= vendor <= 65535 and 0 <= device <= 65535):
            raise ValueError()
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError("Formato richiesto: 8086:466e")
    return (device << 16) | vendor


def number(value):
    return int(value, 0)


def ecam_address():
    path = Path("/sys/firmware/acpi/tables/MCFG")
    data = path.read_bytes()
    require(len(data) >= 44 and data[:4] == b"MCFG", "Tabella MCFG non valida")
    length = struct.unpack_from("<I", data, 4)[0]
    require(length == len(data) and (length - 44) % 16 == 0,
            "Lunghezza MCFG non valida")
    require(sum(data) & 0xFF == 0, "Checksum MCFG non valido")
    matches = []
    for offset in range(44, length, 16):
        base, segment, first, last, reserved = struct.unpack_from("<QHBBI", data, offset)
        if segment == 0 and first == 0 and last >= first:
            require(base != 0 and base & 0xFFFFF == 0, "Base ECAM non allineata")
            matches.append(base)
    require(len(matches) == 1, "Mapping ECAM del bus 0 assente o ambiguo")
    return matches[0] + (7 << 15), hashlib.sha256(data).hexdigest()


def load_helper(folder, prebuilt):
    source = Path(__file__).with_name("regbar_mmio.c")
    if prebuilt:
        helper_path = Path(prebuilt).resolve(strict=True)
    else:
        compiler = shutil.which("cc") or shutil.which("gcc")
        require(compiler is not None, "Serve cc/gcc oppure --mmio-helper")
        helper_path = folder / "regbar_mmio.so"
        result = subprocess.run(
            [compiler, "-shared", "-fPIC", "-nostdlib", "-ffreestanding", "-fno-stack-protector",
             "-O2", "-Wall", "-Wextra", "-Werror",
             "-o", str(helper_path), str(source)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
            timeout=30, check=False)
        (folder / "helper-build.txt").write_text(result.stdout + result.stderr)
        require(result.returncode == 0, "Compilazione helper fallita; nessun MMIO modificato")
    helper = ctypes.CDLL(str(helper_path))
    helper.regbar_read32.argtypes = [ctypes.c_void_p]
    helper.regbar_read32.restype = ctypes.c_uint32
    helper.regbar_write32.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    helper.regbar_write32.restype = None
    return helper, {"path": str(helper_path),
                    "sha256": hashlib.sha256(helper_path.read_bytes()).hexdigest(),
                    "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}


class PhysicalPage:
    """Mapping di una pagina; mmap libc consente letture su map PROT_READ."""
    libc = ctypes.CDLL(None, use_errno=True)
    libc.mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int,
                          ctypes.c_int, ctypes.c_int, ctypes.c_int64]
    libc.mmap.restype = ctypes.c_void_p
    libc.munmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    libc.munmap.restype = ctypes.c_int

    def __init__(self, fd, physical, helper, writable=False):
        self.size = os.sysconf("SC_PAGE_SIZE")
        require(self.size >= 4096 and self.size & (self.size - 1) == 0,
                "Dimensione pagina non supportata")
        self.physical = physical & ~(self.size - 1)
        self.helper = helper
        self.writable = writable
        prot = 1 | (2 if writable else 0)  # PROT_READ, eventualmente PROT_WRITE
        address = self.libc.mmap(None, self.size, prot, 1, fd, self.physical)  # MAP_SHARED
        if address == ctypes.c_void_p(-1).value:
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err), f"MMIO {self.physical:#x}")
        self.address = address

    def pointer(self, physical):
        require(physical & 3 == 0, "Accesso MMIO non allineato a 32 bit")
        require(self.physical <= physical <= self.physical + self.size - 4,
                "Accesso MMIO fuori dalla pagina")
        return self.address + physical - self.physical

    def read32(self, physical):
        return int(self.helper.regbar_read32(self.pointer(physical)))

    def write32(self, physical, value):
        require(self.writable, "Scrittura su mapping di sola lettura")
        require(physical == 0xFBC600D0, "Scrittura fuori dall'unico registro autorizzato")
        self.helper.regbar_write32(self.pointer(physical), value)

    def close(self):
        if self.address is not None:
            self.libc.munmap(self.address, self.size)
            self.address = None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-id", required=True, type=parse_id,
                        help="VID:DID D7:F0 verificato, es. 8086:466e")
    parser.add_argument("--expected-value", required=True, type=number,
                        help="CCFG originale verificato, es. 0x0e009077")
    parser.add_argument("--output", type=Path, required=True,
                        help="Nuova directory del rapporto; deve essere assente")
    parser.add_argument("--execute", action="store_true",
                        help="Esegue i quattro casi temporanei con ripristino")
    parser.add_argument("--hold-seconds", type=float, default=0.05,
                        help="Attesa per caso prima della lettura stabile; default 0.05")
    parser.add_argument("--mmio-helper", help="Libreria nativa gia compilata, opzionale")
    args = parser.parse_args()
    require(platform.system() == "Linux" and platform.machine() in ("x86_64", "amd64"),
            "Richiesto Linux x86-64")
    require(os.geteuid() == 0, "Richiesti privilegi root")
    require("i9-12900H" in Path("/proc/cpuinfo").read_text(), "CPU diversa da i9-12900H")
    require(math.isfinite(args.hold_seconds) and 0 <= args.hold_seconds <= 300,
            "--hold-seconds deve essere tra 0 e 300")
    require(args.expected_id == 0x466E8086, "La sonda e limitata al controller 8086:466e")
    require(args.expected_value == 0x0E009077, "La sonda richiede baseline CCFG 0x0e009077")
    args.output = args.output.resolve()
    args.output.mkdir(mode=0o700)  # Esclusivo: non sovrascrive precedenti evidenze.
    fsync_dir(args.output.parent)
    journal = Journal(args.output)
    state = {"restoring": False, "interrupted": None, "armed": False}

    def interrupt(signum, _frame):
        state["interrupted"] = signum
        if not state["restoring"]:
            raise Interrupted(f"Ricevuto segnale {signum}; ripristino richiesto")

    old_handlers = {}
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        old_handlers[sig] = signal.signal(sig, interrupt)

    try:
        with contextlib.ExitStack() as stack:
            helper, helper_info = load_helper(args.output, args.mmio_helper)
            root_config = pci_read(ROOT_BDF, 0, 256)
            host_config = pci_read(HOST_BDF, 0, 256)
            root_id = struct.unpack_from("<I", root_config, 0)[0]
            require(root_id == args.expected_id, f"ID D7:F0 inatteso: {root_id:#010x}")
            require(root_config[0x0B] == 6 and root_config[0x0A] == 4,
                    "D7:F0 non e un bridge PCI")
            require(struct.unpack_from("<H", host_config, 0)[0] == 0x8086,
                    "Host bridge non Intel")
            mchbar_raw = struct.unpack_from("<Q", host_config, 0x48)[0]
            require(mchbar_raw == 0xFEDC0001, f"MCHBAR inatteso: {mchbar_raw:#x}")
            mchbar = mchbar_raw & 0x7FFFFF8000  # Indirizzo bits 38:15, enable bit 0.
            function_map = struct.unpack_from("<I", host_config, 0x7C)[0]
            require(function_map & 7 == 0, "Porta fisica C6 non mappata su funzione 0")
            ecam, mcfg_sha256 = ecam_address()
            memfd = os.open("/dev/mem", (os.O_RDWR if args.execute else os.O_RDONLY) | os.O_SYNC)
            stack.callback(os.close, memfd)
            mch = PhysicalPage(memfd, mchbar + 0x7110, helper)
            stack.callback(mch.close)
            regbar_lo = mch.read32(mchbar + 0x7110)
            regbar_hi = mch.read32(mchbar + 0x7114)
            regbar_raw = (regbar_hi << 32) | regbar_lo
            require(regbar_raw == 0xFB000001, f"REGBAR inatteso: {regbar_raw:#x}")
            require(mch.read32(mchbar + 0x7110) == regbar_lo and
                    mch.read32(mchbar + 0x7114) == regbar_hi, "REGBAR instabile")
            presence = mch.read32(mchbar + 0x7090)
            require(presence & 1, "Porta fisica 0 non presente secondo MCHBAR+7090")
            regbar = regbar_raw & ~0xFFFFFF
            target = regbar | (PORT_ID << 16) | REG_OFFSET
            sb = PhysicalPage(memfd, target, helper, writable=args.execute)
            stack.callback(sb.close)
            cfg = PhysicalPage(memfd, ecam, helper)
            stack.callback(cfg.close)
            require(cfg.read32(ecam) == args.expected_id, "ID ECAM non coincide con sysfs")

            def read_state():
                return {"regbar": sb.read32(target), "ecam": cfg.read32(ecam + REG_OFFSET),
                        "pci_sysfs": pci_u32(ROOT_BDF, REG_OFFSET)}

            def identity_check():
                require(cfg.read32(ecam) == args.expected_id and
                        pci_u32(ROOT_BDF, 0) == args.expected_id, "Identita PCI cambiata")

            def is_original(values):
                return all(value == args.expected_value for value in values.values())

            def check_observation(values, mask):
                for route, value in values.items():
                    require(((value ^ args.expected_value) & (~mask & 0xFFFFFFFF)) == 0,
                            f"Anomalia {route}: cambiati bit fuori dal caso {mask:#010x}")
                require(len(set(values.values())) == 1, "Readback REGBAR/ECAM/sysfs discordanti")

            original = read_state()
            require(is_original(original), f"Baseline non corrispondente: {original}")
            identity_check()
            snapshot = {"utc": stamp(), "host": platform.node(), "pid": os.getpid(),
                        "root_bdf": ROOT_BDF, "host_bdf": HOST_BDF, "root_id": root_id,
                        "root_config_hex": root_config.hex(), "host_config_hex": host_config.hex(),
                        "mchbar_raw": mchbar_raw, "regbar_raw": regbar_raw,
                        "physical_target": target, "ecam_root_base": ecam,
                        "function_mapping": function_map, "presence_bitmap": presence,
                        "original": original, "expected_value": args.expected_value,
                        "mcfg_sha256": mcfg_sha256, "helper": helper_info,
                        "execute": args.execute, "hold_seconds": args.hold_seconds,
                        "restore_value": args.expected_value, "cases": CASES,
                        "scope": "Solo C6:D0, PCI 0000:00:07.0; nessun flash, driver o carico GPU"}
            save_new_json(args.output / "snapshot.json", snapshot)
            journal.log("snapshot_durable", file=str(args.output / "snapshot.json"), original=original)
            if not args.execute:
                journal.log("finished_read_only", restored=True)
                return 0

            results = []
            for name, mask in CASES:
                require(state["interrupted"] is None, "Interruzione prima del caso")
                identity_check()
                require(is_original(read_state()), "Baseline modificata tra i casi; arresto")
                desired = args.expected_value & ~mask
                require((desired ^ args.expected_value) & ~PEER_MASK == 0,
                        "Tentativo di modificare bit fuori da 25–27")
                journal.log("case_start", case=name, clear_mask=mask, desired=desired)
                record = {"case": name, "mask": mask, "desired": desired}
                try:
                    # Armare prima dello store assicura restore anche con segnale al ritorno da C.
                    state["armed"] = True
                    started_ns = monotonic_ns()
                    sb.write32(target, desired)
                    immediate = read_state()  # Readback stesso device drena lo store MMIO.
                    immediate_ns = monotonic_ns()
                    record.update(immediate=immediate, immediate_after_ns=immediate_ns - started_ns)
                    check_observation(immediate, mask)
                    time.sleep(args.hold_seconds)
                    settled = read_state()
                    settled_ns = monotonic_ns()
                    record.update(settled=settled, settled_after_ns=settled_ns - started_ns)
                    identity_check()
                    check_observation(settled, mask)
                    record.update(immediate=immediate, settled=settled,
                                  immediate_after_ns=immediate_ns - started_ns,
                                  settled_after_ns=settled_ns - started_ns,
                                  changed_mask=args.expected_value ^ settled["regbar"],
                                  all_requested_bits_cleared=settled["regbar"] == desired)
                except BaseException as exc:
                    record["error"] = repr(exc)
                    raise
                finally:
                    # Durante il restore i segnali vengono registrati, senza interrompere lo store.
                    state["restoring"] = True
                    try:
                        if state["armed"]:
                            sb.write32(target, args.expected_value)
                            restored_immediate = read_state()
                            time.sleep(0.005)
                            restored_settled = read_state()
                            restored_ok = is_original(restored_immediate) and is_original(restored_settled)
                            # Prima del logging: una failure del filesystem non salta il restore.
                            state["armed"] = not restored_ok
                            journal.log("case_restore", case=name,
                                        immediate=restored_immediate, settled=restored_settled,
                                        restored=restored_ok)
                            journal.log("case_readback", **record)
                            require(restored_ok, "RIPRISTINO NON CONFERMATO; nessun altro caso verra eseguito")
                    finally:
                        state["restoring"] = False
                results.append(record)
                require(state["interrupted"] is None, "Interruzione registrata dopo il ripristino")
            final = read_state()
            identity_check()
            require(is_original(final), "Parola finale diversa dall'originale")
            save_new_json(args.output / "result.json", {"utc": stamp(), "cases": results,
                                                       "final": final, "restored": True})
            journal.log("finished", restored=True, cases=len(results))
            return 0
    except BaseException as exc:
        try:
            journal.log("aborted", error=repr(exc), restore_unconfirmed=state["armed"],
                        interrupted=state["interrupted"])
        except BaseException:
            print(f"ERRORE: {exc!r}; restore_unconfirmed={state['armed']}", file=sys.stderr)
        return 2
    finally:
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
        journal.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ProbeError, OSError) as exc:
        print(f"ARRESTO: {exc}", file=sys.stderr)
        sys.exit(2)
