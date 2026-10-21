"""Rimuove solo avvii e directory temporanee dopo ripristino verificato."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import time
R=Path('/root/riscrivo-p2p-tcss-bit-tests-20261021')
def run(args): return subprocess.check_output(args,universal_newlines=True)
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
assert os.geteuid()==0 and run(['hostname']).strip()=='hypervisor-host'
assert Path('/sys/class/dmi/id/board_name').read_text().strip()=='AHWSA'
assert run(['findmnt','-n','-o','PARTUUID','/boot/efi']).strip()=='3c6ae711-bbc9-4653-bf09-0baac6b3b380'
boot=run(['efibootmgr','-v'])
assert 'BootNext:' not in boot and 'BootCurrent: 0000' in boot
assert re.search(r'^BootOrder: (.+)$',boot,re.M).group(1)=='0000,0001'
state=json.loads((R/'native-read-state.json').read_text())
for name,item in state['original_files'].items(): assert sha(Path(name))==item['sha256']
restored=R/'native-sync-restore-results/region-restored.bin'
assert sha(restored)=='b81e705a87c89a668c4bbddd3538a82ccd5ebea4b156ce2d79762147310deba9'
values={}
for bdf,expected in [('0000:00:01.0',0x04008077),('0000:00:07.0',0x0e009077),('0000:00:07.2',0x0e009077)]:
    f=os.open('/sys/bus/pci/devices/'+bdf+'/config',os.O_RDONLY)
    try: values[bdf]=struct.unpack('<I',os.pread(f,4,0xd0))[0]
    finally: os.close(f)
    assert values[bdf]==expected,(bdf,values[bdf])
expected_entries={'0002':('CaskLogic TCSS sync prova','CaskLogicTcssSyncTest'),
                  '0003':('CaskLogic TCSS GPU sync','CaskLogicTcssNative')}
for entry,(label,directory) in expected_entries.items():
    assert ('Boot'+entry+'* '+label) in boot
    line=next(x for x in boot.splitlines() if x.startswith('Boot'+entry+'*'))
    assert '\\EFI\\'+directory+'\\' in line and '3c6ae711-bbc9-4653-bf09-0baac6b3b380' in line
backup=R/'final-sync-esp-artifacts'
assert not backup.exists();backup.mkdir()
for entry,(label,directory) in expected_entries.items():
    src=Path('/boot/efi/EFI')/directory
    # Immagini grandi già conservate nel pacchetto e backup SPI precedente.
    shutil.copytree(str(src),str(backup/directory),ignore=shutil.ignore_patterns('spi-current-*.bin','probe-initrd.img','probe-kernel.efi'))
    run(['efibootmgr','--bootnum',entry,'--delete-bootnum'])
    shutil.rmtree(str(src))
after=run(['efibootmgr','-v'])
assert 'BootNext:' not in after
assert re.search(r'^BootOrder: (.+)$',after,re.M).group(1)=='0000,0001'
assert set(re.findall(r'^Boot([0-9A-Fa-f]{4})\*?',after,re.M))=={'0000','0001'}
for name,item in state['original_files'].items(): assert sha(Path(name))==item['sha256']
result={'epoch':time.time(),'restored_spi_region_sha256':sha(restored),
        'ccfg_final':values,'original_boot_files_unchanged':True,
        'temporary_entries_and_esp_directories_removed':True,'boot_final':after,
        'preserved_prior_SaSetup_P2P_setting':True}
(R/'cleanup-sync-verified.json').write_text(json.dumps(result,indent=2)+'\n')
os.sync();print(json.dumps(result,indent=2))
