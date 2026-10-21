#!/usr/bin/env python3
"""Verifica e conserva integralmente gli artefatti prima della pulizia finale.

Compatibile Python3.6. Senza --execute legge soltanto; non ripristina il firmware.
Il ripristino deve essere già eseguito, riletto in UEFI e raccolto dall'operatore.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import time
import uuid

R = Path('/root/riscrivo-p2p-tcss-bit-tests-20261021')
ESP = Path('/boot/efi')
PARTUUID = '3c6ae711-bbc9-4653-bf09-0baac6b3b380'
ORIGINAL = 'b81e705a87c89a668c4bbddd3538a82ccd5ebea4b156ce2d79762147310deba9'
REGION_BYTES = 0x1e000
DIRECTORIES = {
    'CaskLogicTcssSyncTest': ('CaskLogic TCSS sync prova', 'Shell.efi'),
    'CaskLogicTcssNative': ('CaskLogic TCSS GPU sync', 'probe-kernel.efi'),
}
CCFG = {'0000:00:01.0': (0x460d8086, 0x04008077),
        '0000:00:07.0': (0x466e8086, 0x0e009077),
        '0000:00:07.2': (0x462f8086, 0x0e009077)}


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def run(args):
    return subprocess.check_output(args, universal_newlines=True)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for part in iter(lambda: f.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def read_text(path):
    raw = Path(path).read_bytes()
    return raw.decode('utf-16' if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-8').strip()


def tree_manifest(root):
    """Rifiuta link, file speciali e sottovolumi; include anche directory vuote."""
    require(root.is_dir() and not root.is_symlink(), 'Directory non regolare: ' + str(root))
    device = root.stat().st_dev
    result = {'directories': [], 'files': {}}
    for parent, dirs, files in os.walk(str(root), followlinks=False):
        current = Path(parent)
        require(current.stat().st_dev == device, 'Sottovolume inatteso')
        for name in sorted(dirs):
            item = current / name
            require(not item.is_symlink() and item.stat().st_dev == device, 'Link/sottovolume: ' + str(item))
            result['directories'].append(str(item.relative_to(root)))
        for name in sorted(files):
            item = current / name
            info = item.lstat()
            require(stat.S_ISREG(info.st_mode) and info.st_dev == device, 'File non regolare: ' + str(item))
            result['files'][str(item.relative_to(root))] = {'size': info.st_size, 'sha256': sha(item)}
    result['directories'].sort()
    return result


def sync_tree(root):
    for parent, dirs, files in os.walk(str(root), topdown=False):
        for name in files:
            fd = os.open(str(Path(parent) / name), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def save_json(path, value):
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('x') as f:
        json.dump(value, f, indent=2)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(str(temporary), str(path))
    fd = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def parse_boot(text):
    require(not re.search(r'^BootNext:', text, re.M), 'BootNext ancora presente')
    require(re.search(r'^BootCurrent: 0000$', text, re.M), 'Avvio corrente inatteso')
    require(re.search(r'^BootOrder: 0000,0001$', text, re.M), 'BootOrder inatteso')
    entries = {}
    for line in text.splitlines():
        match = re.match(r'^Boot([0-9A-Fa-f]{4})(\*?) (.*)$', line)
        if match:
            key = match.group(1).upper()
            require(key not in entries, 'Voce EFI duplicata')
            entries[key] = line
    require('0000' in entries and '0001' in entries, 'Avvii originali assenti')
    return entries


def target_entries(entries):
    found = {}
    for directory, (label, loader) in DIRECTORIES.items():
        matches = []
        for entry, line in entries.items():
            suffix = line.split(' ', 1)[1]
            if suffix.startswith(label + '\t') or suffix.startswith(label + ' '):
                require(PARTUUID in line.lower(), 'PARTUUID della voce EFI inatteso')
                require('File(\\EFI\\' + directory + '\\' + loader + ')' in line,
                        'Loader EFI inatteso')
                matches.append(entry)
        require(len(matches) == 1 and matches[0] not in ('0000', '0001'),
                'Voce temporanea assente/ambigua: ' + directory)
        found[directory] = matches[0]
    require(len(set(found.values())) == 2, 'Voce EFI condivisa')
    require(set(entries) == set(found.values()) | {'0000', '0001'}, 'Altre voci EFI: interrompere senza eliminarle')
    return found


def read_ccfg():
    result = {}
    for bdf, (identity, expected) in CCFG.items():
        fd = os.open('/sys/bus/pci/devices/' + bdf + '/config', os.O_RDONLY)
        try:
            raw_id = os.pread(fd, 4, 0)
            raw_value = os.pread(fd, 4, 0xd0)
        finally:
            os.close(fd)
        require(len(raw_id) == len(raw_value) == 4, 'Lettura PCI incompleta')
        require(struct.unpack('<I', raw_id)[0] == identity, 'Identità PCI diversa: ' + bdf)
        result[bdf] = struct.unpack('<I', raw_value)[0]
        require(result[bdf] == expected, 'CCFG non ripristinato: ' + bdf)
    return result


def verify_original_files(baseline):
    require(baseline.get('original_files'), 'Manifest originale vuoto')
    for name, item in baseline['original_files'].items():
        path = Path(name)
        require(path.is_absolute() and str(path).startswith(str(ESP) + '/'), 'Path originale inatteso')
        require(not any(str(path).startswith(str(ESP / 'EFI' / d) + '/') for d in DIRECTORIES), 'Originale dentro directory temporanea')
        require(sha(path) == item['sha256'], 'File avvio originale cambiato: ' + name)


def verify_restore():
    source = R / 'native-sync-flash-package'
    installed = ESP / 'EFI/CaskLogicTcssSyncTest'
    state = json.loads((R / 'native-sync-firmware-state.json').read_text())
    require(state.get('stage') == 'restore_armed', 'Ripristino non risulta avviato')
    files = json.loads((source / 'files.json').read_text())
    require(files == state['files'] and files['ORIGINAL.bin'] == ORIGINAL, 'Manifest firmware inatteso')
    for name, digest in files.items():
        require(Path(name).name == name, 'Path pacchetto invalido')
        require(sha(source / name) == digest, 'Pacchetto sorgente cambiato: ' + name)
        wanted = files['startup-restore.nsh'] if name == 'startup.nsh' else digest
        require(sha(installed / name) == wanted, 'Pacchetto ESP cambiato: ' + name)
    original = source / 'ORIGINAL.bin'
    observed = installed / 'region-restored.bin'
    collected = R / 'native-sync-restore-results/region-restored.bin'
    for path in (original, observed, collected):
        require(path.stat().st_size == REGION_BYTES and sha(path) == ORIGINAL, 'Span originale non confermato: ' + str(path))
    require(read_text(installed / 'restore-status.txt') == 'ORIGINAL_RESTORED_AND_READBACK_VERIFIED', 'Stato UEFI restore non valido')
    flag = read_text(installed / 'RESTORED.flag')
    require('TcssRegionGate Sync v4 RESTORE_CHECK PASS' in flag and 'SPI 01B0B000 length 0001E000' in flag,
            'Flag restore errato')
    log = read_text(installed / 'region-restore-gate.txt')
    require('readback_byte_mismatches=0x0000000000000000' in log and
            'phase=all_checks_passed_before_flag' in log and 'result=FAIL' not in log,
            'Confronto UEFI completo non confermato')
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Backup verificato e rimozione dei soli due avvii temporanei')
    args = parser.parse_args()
    require(os.geteuid() == 0 and run(['hostname']).strip() == 'hypervisor-host', 'Host/root inatteso')
    require(Path('/sys/class/dmi/id/board_name').read_text().strip() == 'AHWSA', 'Scheda inattesa')
    require(Path('/sys/class/dmi/id/bios_version').read_text().strip() == '1.26', 'BIOS inatteso')
    require(run(['findmnt', '-n', '-o', 'PARTUUID', str(ESP)]).strip() == PARTUUID, 'ESP inattesa')
    boot = run(['efibootmgr', '-v'])
    entries = parse_boot(boot)
    targets = target_entries(entries)
    baseline = json.loads((R / 'native-read-state.json').read_text())
    verify_original_files(baseline)
    state = verify_restore()
    require(targets['CaskLogicTcssSyncTest'] == state['entry'], 'Voce firmware diversa dallo stato')
    values = read_ccfg()
    trees = {name: tree_manifest(ESP / 'EFI' / name) for name in DIRECTORIES}
    evidence = {'status': 'verified_not_removed', 'epoch': time.time(), 'boot_before': boot,
                'entries': targets, 'ccfg': values, 'original_region_sha256': ORIGINAL,
                'region_start': 0x1b0b000, 'region_bytes': REGION_BYTES,
                'tree_manifests': trees, 'all_files_including_images_preserved': False,
                'script_sha256': sha(Path(__file__)), 'mutations': []}
    if not args.execute:
        print(json.dumps(evidence, indent=2))
        return
    backup = R / ('final-sync-esp-artifacts-verified-' + time.strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8])
    backup.mkdir()
    evidence['backup'] = str(backup)
    journal = backup / 'cleanup-journal.json'
    try:
        for name in DIRECTORIES:
            shutil.copytree(str(ESP / 'EFI' / name), str(backup / name))
        sync_tree(backup)
        for name in DIRECTORIES:
            require(tree_manifest(backup / name) == trees[name], 'Backup hash diverso: ' + name)
            require(tree_manifest(ESP / 'EFI' / name) == trees[name], 'ESP modificata durante backup: ' + name)
        evidence['all_files_including_images_preserved'] = True
        evidence['status'] = 'backup_verified_before_any_removal'
        save_json(journal, evidence)
        os.sync()
        require(parse_boot(run(['efibootmgr', '-v'])) == entries, 'Voci EFI cambiate durante backup')
        verify_original_files(baseline)
        verify_restore()
        require(read_ccfg() == values, 'CCFG cambiati durante backup')
        expected = dict(entries)
        for name, entry in targets.items():
            run(['efibootmgr', '--bootnum', entry, '--delete-bootnum'])
            expected.pop(entry)
            require(parse_boot(run(['efibootmgr', '-v'])) == expected, 'Modifica EFI inattesa')
            evidence['mutations'].append({'entry_removed': entry})
            save_json(journal, evidence)
        for name in DIRECTORIES:
            require(tree_manifest(ESP / 'EFI' / name) == trees[name], 'ESP cambiata prima rimozione: ' + name)
            require(tree_manifest(backup / name) == trees[name], 'Backup cambiato prima rimozione: ' + name)
            shutil.rmtree(str(ESP / 'EFI' / name))
            require(not (ESP / 'EFI' / name).exists(), 'Directory non rimossa')
            evidence['mutations'].append({'directory_removed': name})
            save_json(journal, evidence)
        after = run(['efibootmgr', '-v'])
        require(parse_boot(after) == {k: entries[k] for k in ('0000', '0001')}, 'Voci originali cambiate')
        verify_original_files(baseline)
        evidence.update(status='cleanup_verified', boot_after=after,
                        original_boot_files_unchanged=True, ccfg_final=read_ccfg(),
                        temporary_entries_and_directories_removed=True,
                        preserved_prior_SaSetup_P2P_setting=True)
        save_json(journal, evidence)
        save_json(R / 'cleanup-sync-verified.json', evidence)
        os.sync()
        print(json.dumps(evidence, indent=2))
    except Exception as error:
        evidence.update(status='incomplete_preserve_backup', error=str(error))
        save_json(journal, evidence)
        raise


if __name__ == '__main__':
    main()
