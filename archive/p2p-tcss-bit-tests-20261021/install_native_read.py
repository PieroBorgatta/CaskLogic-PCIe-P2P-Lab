"""Prepara un solo avvio UEFI di lettura; non esegue flash o riavvio."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import time

R = Path('/root/riscrivo-p2p-tcss-bit-tests-20261021')
SRC = R / 'native-read-package'
DST = Path('/boot/efi/EFI/CaskLogicTcssTest')

def run(args):
    return subprocess.check_output(args, universal_newlines=True)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

assert os.geteuid() == 0
assert run(['hostname']).strip() == 'hypervisor-host'
assert Path('/sys/class/dmi/id/board_name').read_text().strip() == 'AHWSA'
assert Path('/sys/class/dmi/id/bios_version').read_text().strip() == '1.26'
assert run(['findmnt', '-n', '-o', 'SOURCE', '/boot/efi']).strip() == '/dev/nvme1n1p4'
boot = run(['efibootmgr', '-v'])
assert 'BootNext:' not in boot
order = re.search(r'^BootOrder: (.+)$', boot, re.M).group(1)
assert order == '0000,0001'
assert not DST.exists()
files = {}
for p in sorted(Path('/boot/efi/EFI').rglob('*')):
    if p.is_file():
        files[str(p)] = {'bytes': p.stat().st_size, 'sha256': sha(p)}
old = json.loads(Path('/root/riscrivo-uefi-p2p/before.json').read_text())
for name, details in old['files'].items():
    assert files[name]['sha256'] == details['sha256'], name
expected = json.loads((SRC / 'files.json').read_text())
assert set(expected) == {'Shell.efi', 'Fpt.efi', 'BootGuardRead.efi', 'startup.nsh'}
for name, digest in expected.items():
    assert sha(SRC / name) == digest, name
assert expected['Shell.efi'] == '24dcc034bf6a5158f43b23b71a16acbfdcf1597de55aa309f7f6ac5af90666e6'
assert expected['Fpt.efi'] == 'd3747b061cf185f9883562a0b2ee890079872541af4f43f2caa074c2fb256a05'
state = {'epoch': time.time(), 'stage': 'preparation', 'boot_before': boot,
         'boot_order_before': order, 'original_files': files,
         'package_sha256': expected, 'flash_writes': False,
         'vm_before': run(['xe', 'vm-list', 'is-control-domain=false',
                           'params=uuid,name-label,power-state']), 'entry': None}
state_path = R / 'native-read-state.json'
assert not state_path.exists()
state_path.write_text(json.dumps(state, indent=2) + '\n')
oldids = set(re.findall(r'^Boot([0-9A-Fa-f]{4})\*?', boot, re.M))
newid = None
try:
    shutil.copytree(str(SRC), str(DST))
    for name, digest in expected.items():
        assert sha(DST / name) == digest
    run(['efibootmgr', '--create-only', '--disk', '/dev/nvme1n1', '--part', '4',
         '--label', 'CaskLogic TCSS lettura', '--loader',
         '\\EFI\\CaskLogicTcssTest\\Shell.efi'])
    now = run(['efibootmgr', '-v'])
    newids = set(re.findall(r'^Boot([0-9A-Fa-f]{4})\*?', now, re.M)) - oldids
    assert len(newids) == 1
    newid = newids.pop()
    assert re.search(r'^BootOrder: (.+)$', now, re.M).group(1) == order
    state['entry'] = newid
    state_path.write_text(json.dumps(state, indent=2) + '\n')
    run(['efibootmgr', '--bootnext', newid])
    after = run(['efibootmgr', '-v'])
    assert 'BootNext: ' + newid in after
    assert re.search(r'^BootOrder: (.+)$', after, re.M).group(1) == order
    state.update(stage='prepared_read_only', boot_after=after)
    state_path.write_text(json.dumps(state, indent=2) + '\n')
    os.sync()
    print(json.dumps({'prepared': True, 'entry': newid, 'flash_writes': False}))
except BaseException:
    if newid:
        subprocess.call(['efibootmgr', '--delete-bootnext'])
        subprocess.call(['efibootmgr', '--bootnum', newid, '--delete-bootnum'])
    raise
