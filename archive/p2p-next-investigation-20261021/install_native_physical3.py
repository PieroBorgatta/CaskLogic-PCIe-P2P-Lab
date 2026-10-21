#!/usr/bin/env python3
"""Installa solo la prova RAM dedicata; default sola lettura, nessun reboot.

Python 3.6. --stage crea cartella EFI e voce create-only; --arm imposta BootNext
solo a VM ferme. Non scrive configurazione PCI o firmware FSP. Ogni errore
conserva stato e artefatti per l'operatore, senza cancellazioni automatiche.
"""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import time

R = Path('/root/riscrivo-p2p-next-investigation-20261021')
OLD = Path('/root/riscrivo-p2p-tcss-bit-tests-20261021')
SRC = R / 'native-physical3-ce-probe-package'
ESP = Path('/boot/efi')
DST = ESP / 'EFI/CaskLogicTcssPhysical3'
STATE = R / 'physical3-state.json'
BACKUP = R / 'physical3-stage-metadata'
VM = 'd6338ea9-6820-b365-bd0f-7d3790ba2ea7'
PARTUUID = '3c6ae711-bbc9-4653-bf09-0baac6b3b380'
IDENTITY = b'CaskLogic-TCSS-physical3-20261021\n'
LABEL = 'CaskLogic TCSS physical3 probe'
LOADER = '\\EFI\\CaskLogicTcssPhysical3\\probe-kernel.efi'
ARGS = ('initrd=\\EFI\\CaskLogicTcssPhysical3\\probe-initrd.img rdinit=/init '
        'intel_iommu=off iommu=off module_blacklist=nouveau,nvidia_drm,nvidia_modeset '
        'panic=10 loglevel=4 console=tty0')
KERNEL_SHA = '9f55ef7253055a9cf68f8a04323c93dead2fca617386d842fbde9ca7b178b27e'
PINNED = {
    'opt/probe/nvidia-dynamic.ko': 'ab41b0a38e7ab92c0d1468b33c456c5c5c57501c67dfe5a666f49aed9fb6b1b5',
    'opt/probe/nvidia-instrumented-uvm.ko': '06f64631e9c725eff49301ecd2a1a051c504bfa3145dbacb4247484d36d375e9',
    'usr/lib/x86_64-linux-gnu/libcuda.so.1': '03271500dbda9456e3ba765270bd2609bef2631672809da50b19c67fb1f609a7',
    'usr/lib/x86_64-linux-gnu/libcupti.so.12': '76dcad94420820ea9aee9094c346cc34c6cb1ff630cef9b14e04db298a86305d',
    'usr/lib/x86_64-linux-gnu/libnvidia-ml.so.1': '770e9de75c14b07cce9718b214700b10e6d6866f7383101d6fe530352543b1de',
}
CCFG = {'0000:00:01.0': (0x460d8086, 0x04008077),
        '0000:00:07.0': (0x466e8086, 0x0e009077),
        '0000:00:07.2': (0x462f8086, 0x0e009077)}
PACKAGE_NAMES = {'probe-kernel.efi', 'probe-initrd.img', 'IDENTITY.txt',
                 'files.json', 'build-manifest.json'}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def run(args):
    return subprocess.check_output(args, universal_newlines=True)


def regular(path):
    require(path.exists() and not path.is_symlink() and stat.S_ISREG(path.lstat().st_mode),
            'File non regolare: ' + str(path))


def sha(path):
    regular(path)
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def read_json(path):
    regular(path)
    return json.loads(path.read_text())


def digest_valid(value):
    return isinstance(value, str) and re.match(r'^[0-9a-f]{64}$', value) is not None


def atomic_json(path, value):
    """Un file temporaneo preesistente ferma il flusso; non viene cancellato."""
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


def copy_verified(source, destination, expected):
    regular(source)
    require(not destination.exists(), 'Destinazione gia presente: ' + str(destination))
    with source.open('rb') as src, destination.open('xb') as dst:
        shutil.copyfileobj(src, dst, 1024 * 1024)
        dst.flush()
        os.fsync(dst.fileno())
    require(sha(destination) == expected, 'Copia diversa: ' + str(destination))


def parse_boot(text, allow_next=None):
    current = re.findall(r'^BootCurrent: ([0-9A-Fa-f]{4})$', text, re.M)
    order = re.findall(r'^BootOrder: (.+)$', text, re.M)
    nxt = re.findall(r'^BootNext: ([0-9A-Fa-f]{4})$', text, re.M)
    require(current == ['0000'] and order == ['0000,0001'], 'BootCurrent/Order inatteso')
    require(nxt == ([] if allow_next is None else [allow_next]), 'BootNext inatteso')
    entries = {}
    for line in text.splitlines():
        match = re.match(r'^Boot([0-9A-Fa-f]{4})\*? (.*)$', line)
        if match:
            key = match.group(1).upper()
            require(key not in entries, 'Voce EFI duplicata')
            entries[key] = line
    require('0000' in entries and '0001' in entries, 'Avvii originali assenti')
    return entries


def first_free(entries):
    for value in range(65536):
        key = '%04X' % value
        if key not in entries:
            return key
    raise RuntimeError('Nessuna voce EFI libera')


def verify_new_entry(entries, original, entry):
    require(re.match(r'^[0-9A-F]{4}$', entry) and entry not in original, 'Numero voce EFI inatteso')
    require(set(original) == {'0000','0001'}, 'Baseline voci EFI inattesa')
    require(set(entries) == set(original) | {entry}, 'Voci EFI diverse dall\'aggiunta prevista')
    require(all(entries[k] == v for k, v in original.items()), 'Voce originale cambiata')
    line = entries[entry]
    require(re.match(r'^Boot' + entry + r'\*? ' + re.escape(LABEL) + r'(?:\t| )', line), 'Label EFI inattesa')
    require(PARTUUID in line.lower() and 'File(' + LOADER + ')' in line, 'Partizione/loader EFI inatteso')
    # efibootmgr visualizza gli argomenti UCS-2 usando punti per i byte NUL.
    suffix = line.split('File(' + LOADER + ')', 1)[1]
    require(suffix.strip() in (ARGS, ''.join(c + '.' for c in ARGS)),
            'Argomenti EFI non corrispondenti al kernel previsto')


def stream_payloads(path, expected):
    found = {}; init = None; members = 0
    with gzip.open(str(path), 'rb') as f:
        while True:
            header = f.read(110)
            require(len(header) == 110 and header[:6] == b'070701', 'CPIO newc non valido')
            a = [int(header[6 + i*8:14 + i*8], 16) for i in range(13)]
            mode, size, namesize = a[1], a[6], a[11]
            require(0 < namesize < 4096, 'Nome CPIO invalido')
            name = f.read(namesize)
            require(len(name) == namesize and name.endswith(b'\0'), 'Nome CPIO troncato')
            name = name[:-1].decode('utf-8')
            pad = (-110 - namesize) % 4
            require(len(f.read(pad)) == pad, 'Padding CPIO troncato')
            if name == 'TRAILER!!!':
                require(size == 0, 'Trailer CPIO inatteso')
                break
            if name.startswith('./'):
                name = name[2:]
            members += 1; h = hashlib.sha256(); left = size; content = []
            if name == 'init':
                require(size < 65536, 'Init troppo grande')
            while left:
                part = f.read(min(left, 1024 * 1024))
                require(part, 'Payload CPIO troncato')
                h.update(part); left -= len(part)
                if name == 'init': content.append(part)
            pad = (-size) % 4
            require(len(f.read(pad)) == pad, 'Padding dati CPIO troncato')
            if name in expected:
                require(name not in found and stat.S_ISREG(mode), 'Payload duplicato/non regolare')
                found[name] = h.hexdigest()
                require(found[name] == expected[name], 'Hash payload diverso: ' + name)
            if name == 'init': init = b''.join(content).decode('utf-8')
        # Valida anche CRC gzip e rifiuta un secondo archivio dopo il trailer.
        while True:
            trailing = f.read(1024 * 1024)
            if not trailing: break
            require(not trailing.strip(b'\0'), 'Contenuto inatteso dopo trailer CPIO')
    require(found == expected and init is not None, 'Payload mancanti')
    for token in ['CaskLogic-TCSS-physical3-20261021', 'EFI/CaskLogicTcssPhysical3',
                  'timeout 60 /opt/probe/peer_word', 'sleep 180', 'RM64KBBAR1Mappings=0',
                  'uvm_cask_physical_ce=1', 'uvm_enable_builtin_tests=1', 'WATCHDOG_REBOOT']:
        require(token in init, 'Contratto init mancante: ' + token)
    for token in ['RMCaskPeerCoherent=1', 'uvm_cask_peer_small_pages=1', 'cask_low_mmio']:
        require(token not in init, 'Variante init non autorizzata: ' + token)
    return {'members': members, 'payload_files': found}


def verify_package():
    require(SRC.is_dir() and not SRC.is_symlink(), 'Pacchetto assente/non regolare')
    require({p.name for p in SRC.iterdir()} == PACKAGE_NAMES, 'Contenuto pacchetto inatteso')
    files = read_json(SRC/'files.json'); manifest = read_json(SRC/'build-manifest.json')
    require(set(files) == {'probe-kernel.efi', 'probe-initrd.img', 'IDENTITY.txt'}, 'Manifest file inatteso')
    require(files == manifest['files'] and all(digest_valid(v) for v in files.values()), 'Manifest hash incoerente')
    for name, digest in files.items(): require(sha(SRC/name) == digest, 'File pacchetto cambiato: ' + name)
    require(files['probe-kernel.efi'] == KERNEL_SHA and (SRC/'IDENTITY.txt').read_bytes() == IDENTITY, 'Kernel/identita inattesi')
    require((SRC/'probe-initrd.img').stat().st_size == manifest['initrd_bytes'], 'Dimensione initrd diversa')
    require(all(digest_valid(x) for x in PINNED.values()), 'Hash payload non ancora congelati')
    expected = dict(PINNED)
    for key in ['native_program_sha256', 'init_sha256', 'build_inputs_sha256']:
        require(digest_valid(manifest[key]), 'Digest mancante/invalido: ' + key)
    expected.update({'opt/probe/peer_word': manifest['native_program_sha256'], 'init': manifest['init_sha256']})
    require(manifest['payload_files'] == expected, 'Payload non conformi alla baseline')
    require(manifest['module_sha256'] == PINNED['opt/probe/nvidia-dynamic.ko'] and
            manifest['uvm_module_sha256'] == PINNED['opt/probe/nvidia-instrumented-uvm.ko'] and
            manifest['libcuda_sha256'] == PINNED['usr/lib/x86_64-linux-gnu/libcuda.so.1'], 'Moduli/libcuda diversi')
    require(manifest['automatic_return_seconds'] == 182 and manifest['program_timeout_seconds'] == 60 and
            manifest['comparisons'] == 4 and manifest['sizes'] == [4] and
            manifest['modes'] == ['PUSH'] and manifest['engines'] == ['SM', 'PHYSICAL_CE'] and
            manifest['physical_ce_ioctl'] == 315 and manifest['physical_ce_abi'] == 1 and
            manifest['physical_ce_bytes'] == 4 and manifest['calibrations'] == 4 and
            manifest['calibration_sizes'] == [1048576] and
            manifest['calibration_modes'] == ['HOST_TO_DEVICE', 'DEVICE_TO_HOST'] and
            manifest['direct_route_proven'] is False,
            'Contratto prova diverso')
    require(all(manifest[k] is False for k in ['vm_disks_mounted', 'pci_config_writes', 'firmware_writes']), 'Scope mutazioni inatteso')
    require(manifest['expected_CCFG'] == {k[5:]: '%08x' % v[1] for k,v in CCFG.items()}, 'Firmware atteso non originale')
    require(manifest.get('input_files') and all(digest_valid(v) for v in manifest['input_files'].values()), 'Provenienza input assente')
    return {'files': files, 'metadata_sha256': {n: sha(SRC/n) for n in ['files.json','build-manifest.json']},
            'manifest': manifest, 'stream': stream_payloads(SRC/'probe-initrd.img', expected)}


def verify_baseline():
    baseline_path = OLD/'native-read-state.json'
    before = read_json(baseline_path)
    require(before.get('original_files'), 'Baseline EFI originale vuota')
    for name, item in before['original_files'].items():
        path = Path(name)
        require(path.is_absolute() and str(path).startswith('/boot/efi/') and
                not str(path).startswith(str(DST) + '/'), 'Path originale inatteso')
        require(sha(path) == item['sha256'], 'File EFI originale cambiato: ' + name)
    return {'source': str(baseline_path), 'sha256': sha(baseline_path), 'baseline': before}


def read_ccfg():
    values = {}
    for bdf, (ident, expected) in CCFG.items():
        fd = os.open('/sys/bus/pci/devices/' + bdf + '/config', os.O_RDONLY)
        try: raw_id, raw_ccfg = os.pread(fd, 4, 0), os.pread(fd, 4, 0xd0)
        finally: os.close(fd)
        require(len(raw_id) == len(raw_ccfg) == 4, 'Lettura PCI incompleta')
        require(struct.unpack('<I', raw_id)[0] == ident, 'Identita PCI inattesa')
        values[bdf] = struct.unpack('<I', raw_ccfg)[0]
        require(values[bdf] == expected, 'CCFG non originale: ' + bdf)
    return values


def partition_location():
    source = run(['findmnt','-n','-o','SOURCE',str(ESP)]).strip()
    require(re.match(r'^/dev/[A-Za-z0-9_.-]+$', source), 'Dispositivo ESP inatteso')
    dev = Path(os.path.realpath(source)); require(stat.S_ISBLK(dev.stat().st_mode), 'ESP non block device')
    node = Path('/sys/class/block')/dev.name
    partition = int((node/'partition').read_text().strip())
    disk = Path('/dev')/node.resolve().parent.name
    require(partition > 0 and stat.S_ISBLK(disk.stat().st_mode), 'Disco/partizione ESP non validi')
    return str(disk), str(partition)


def host_preflight():
    require(os.geteuid() == 0 and run(['hostname']).strip() == 'hypervisor-host', 'Host/root inatteso')
    require(Path('/sys/class/dmi/id/board_name').read_text().strip() == 'AHWSA', 'Board inattesa')
    require(Path('/sys/class/dmi/id/bios_version').read_text().strip() == '1.26', 'BIOS inatteso')
    require(run(['findmnt','-n','-o','PARTUUID',str(ESP)]).strip() == PARTUUID, 'ESP diversa')
    require(not DST.is_symlink() and not STATE.is_symlink() and not BACKUP.is_symlink(), 'Link inatteso')
    return verify_baseline(), read_ccfg()


def verify_staged(state, package, entries):
    require(state['stage'] == 'staged' and state['files'] == package['files'] and
            state['metadata_sha256'] == package['metadata_sha256'], 'Stato staged/pacchetto diverso')
    require(state['kernel_args'] == ARGS and state['label'] == LABEL and state['loader'] == LOADER, 'Contratto stato diverso')
    require(DST.is_dir() and not DST.is_symlink() and {p.name for p in DST.iterdir()} == PACKAGE_NAMES,
            'Directory staged cambiata o contiene risultati')
    for n,digest in dict(package['files'], **package['metadata_sha256']).items(): require(sha(DST/n) == digest, 'File staged cambiato: ' + n)
    verify_new_entry(entries, state['original_entries'], state['entry'])
    return True


def require_idle_vms():
    require(run(['xe','vm-param-get','uuid='+VM,'param-name=power-state']).strip() == 'halted', 'Docker non halted')
    require(run(['xe','vm-list','power-state=running','is-control-domain=false','--minimal']).strip() == '', 'Altra VM running')
    require(run(['xe','vm-list','power-state=paused','is-control-domain=false','--minimal']).strip() == '', 'Altra VM paused')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--stage', action='store_true')
    group.add_argument('--arm', action='store_true')
    args = parser.parse_args()
    baseline, ccfg = host_preflight(); package = verify_package()
    boot = run(['efibootmgr','-v']); entries = parse_boot(boot)
    if args.arm:
        state = read_json(STATE); verify_staged(state, package, entries); require_idle_vms()
        require(baseline['sha256'] == state['baseline_sha256'], 'Baseline cambiata')
        state.update(stage='arm_pending', ccfg_before=read_ccfg(), epoch_arm_pending=time.time())
        atomic_json(STATE,state)
        # Ultima lettura prima della sola mutazione BootNext, nessun reboot qui.
        require(parse_boot(run(['efibootmgr','-v'])) == entries, 'Boot cambiato prima arm')
        require_idle_vms()
        run(['efibootmgr','--bootnext',state['entry']])
        armed = run(['efibootmgr','-v']); after = parse_boot(armed, state['entry'])
        require(after == entries, 'Voci EFI cambiate durante arm')
        verify_baseline(); read_ccfg()
        state.update(stage='armed', epoch_armed=time.time(), boot_armed=armed)
        atomic_json(STATE,state); os.sync()
        print(json.dumps({'status':'armed_no_reboot','entry':state['entry'],'state':str(STATE)})); return
    if STATE.exists():
        require(not args.stage, 'Stato gia esistente: nessuna nuova installazione')
        state = read_json(STATE); verify_staged(state,package,entries)
        print(json.dumps({'status':'staged_verified_read_only','entry':state['entry']})); return
    require(not DST.exists() and not BACKUP.exists(), 'Directory prova/backup gia presente')
    require(set(entries) == {'0000','0001'}, 'Voci EFI aggiuntive prima stage')
    required = sum((SRC/n).stat().st_size for n in PACKAGE_NAMES) + 32*1024*1024
    require(shutil.disk_usage(str(ESP)).free > required, 'Spazio ESP insufficiente con margine32MiB')
    disk,part = partition_location(); entry = first_free(entries)
    if not args.stage:
        print(json.dumps({'status':'ready_to_stage_read_only','entry_if_unchanged':entry,'ESP_bytes_required':required,
                          'ccfg':ccfg,'files':package['files'],'payload_files_verified':package['stream']['payload_files'],
                          'automatic_return_seconds':182,'program_timeout_seconds':60})); return
    # Il backup metadati precede creazione directory EFI e mutazioni NVRAM.
    BACKUP.mkdir()
    copy_verified(Path(baseline['source']),BACKUP/'native-read-state.json',baseline['sha256'])
    for n,digest in package['metadata_sha256'].items():copy_verified(SRC/n,BACKUP/n,digest)
    metadata={'epoch':time.time(),'boot_before':boot,'original_entries':entries,'original_files':baseline['baseline']['original_files'],
              'baseline_sha256':baseline['sha256'],'files':package['files'],'metadata_sha256':package['metadata_sha256'],
              'ccfg':ccfg,'package_stream_check':package['stream'],'disk':disk,'part':part}
    atomic_json(BACKUP/'pre-stage.json',metadata)
    state={'stage':'stage_pending','epoch':time.time(),'entry':entry,'files':package['files'],
           'metadata_sha256':package['metadata_sha256'],'baseline_sha256':baseline['sha256'],'original_entries':entries,
           'kernel_args':ARGS,'label':LABEL,'loader':LOADER,'boot_before':boot,'backup':str(BACKUP),
           'automatic_return_seconds':182,'program_timeout_seconds':60,'ccfg_before':ccfg,'disk':disk,'part':part}
    atomic_json(STATE,state); os.sync()
    require(parse_boot(run(['efibootmgr','-v'])) == entries, 'Boot cambiato prima stage')
    verify_baseline(); read_ccfg()
    DST.mkdir()
    for n,digest in dict(package['files'],**package['metadata_sha256']).items():copy_verified(SRC/n,DST/n,digest)
    os.sync()
    require(parse_boot(run(['efibootmgr','-v'])) == entries, 'Boot cambiato prima create-only')
    state['stage']='entry_create_pending'; atomic_json(STATE,state)
    run(['efibootmgr','--create-only','--disk',disk,'--part',part,'--bootnum',entry,
         '--label',LABEL,'--loader',LOADER,'--unicode',ARGS])
    staged = run(['efibootmgr','-v']); verify_new_entry(parse_boot(staged),entries,entry)
    verify_baseline(); read_ccfg()
    state.update(stage='staged',epoch_staged=time.time(),boot_staged=staged)
    atomic_json(STATE,state); os.sync()
    print(json.dumps({'status':'staged_not_armed','entry':entry,'state':str(STATE)}))


if __name__ == '__main__':
    main()
