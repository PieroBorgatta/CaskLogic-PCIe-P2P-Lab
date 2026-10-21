"""Staging e avvio una tantum del secondo collaudo, oppure ripristino esatto."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
R=Path('/root/riscrivo-p2p-tcss-bit-tests-20261021')
SRC=R/'native-d1-flash-package'
D=Path('/boot/efi/EFI/CaskLogicTcssD1Test')
STATE=R/'native-d1-state.json'
VM='d6338ea9-6820-b365-bd0f-7d3790ba2ea7'
def run(args): return subprocess.check_output(args,universal_newlines=True)
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def ccfg(bdf):
    f=os.open('/sys/bus/pci/devices/'+bdf+'/config',os.O_RDONLY)
    try: return struct.unpack('<I',os.pread(f,4,0xd0))[0]
    finally: os.close(f)
assert os.geteuid()==0 and run(['hostname']).strip()=='hypervisor-host'
assert Path('/sys/class/dmi/id/board_name').read_text().strip()=='AHWSA'
assert Path('/sys/class/dmi/id/bios_version').read_text().strip()=='1.26'
assert run(['findmnt','-n','-o','PARTUUID','/boot/efi']).strip()=='3c6ae711-bbc9-4653-bf09-0baac6b3b380'
boot=run(['efibootmgr','-v'])
assert 'BootNext:' not in boot and 'BootCurrent: 0000' in boot
assert re.search(r'^BootOrder: (.+)$',boot,re.M).group(1)=='0000,0001'
baseline=json.loads((R/'native-read-state.json').read_text())
for name,item in baseline['original_files'].items(): assert sha(Path(name))==item['sha256']
files=json.loads((SRC/'files.json').read_text())
assert set(files)=={'Shell.efi','Fpt.efi','ORIGINAL.bin','CURRENT.bin','CANDIDATE.bin',
                    'RegionPre.efi','RegionPost.efi','RegionRestore.efi','startup.nsh','startup-restore.nsh'}
for name,digest in files.items(): assert sha(SRC/name)==digest
assert files['Shell.efi']=='24dcc034bf6a5158f43b23b71a16acbfdcf1597de55aa309f7f6ac5af90666e6'
assert files['Fpt.efi']=='d3747b061cf185f9883562a0b2ee890079872541af4f43f2caa074c2fb256a05'
mode=sys.argv[1:]
if mode in [['--arm'],['--restore']]:
    state=json.loads(STATE.read_text())
    assert state['files']==files
    for name,digest in files.items(): assert sha(D/name)==digest
    assert run(['xe','vm-param-get','uuid='+VM,'param-name=power-state']).strip()=='halted'
    if mode==['--arm']:
        assert state['stage']=='staged'
        assert ccfg('0000:00:07.0')==0x9077 and ccfg('0000:00:01.0')==0x04008077
        state['stage']='armed'
    else:
        assert state['stage']=='armed'
        assert sha(D/'region-after.bin')==files['CANDIDATE.bin']
        assert (R/'native-d1-flash-results/region-after.bin').read_bytes()==(D/'region-after.bin').read_bytes()
        shutil.copyfile(str(SRC/'startup-restore.nsh'),str(D/'startup.nsh'))
        assert sha(D/'startup.nsh')==files['startup-restore.nsh']
        state['stage']='restore_armed'
    run(['efibootmgr','--bootnext',state['entry']])
    now=run(['efibootmgr','-v'])
    assert 'BootNext: '+state['entry'] in now
    state.update(epoch_last_arm=time.time(),boot_armed=now)
    STATE.write_text(json.dumps(state,indent=2)+'\n');os.sync()
    print(json.dumps({'stage':state['stage'],'entry':state['entry']}))
else:
    assert not mode and not STATE.exists() and not D.exists()
    assert ccfg('0000:00:07.0')==0x9077 and ccfg('0000:00:01.0')==0x04008077
    disk=re.fullmatch(r'(/dev/nvme\d+n\d+)p4',run(['findmnt','-n','-o','SOURCE','/boot/efi']).strip()).group(1)
    shutil.copytree(str(SRC),str(D))
    for name,digest in files.items(): assert sha(D/name)==digest
    oldids=set(re.findall(r'^Boot([0-9A-Fa-f]{4})\*?',boot,re.M))
    run(['efibootmgr','--create-only','--disk',disk,'--part','4',
         '--label','CaskLogic TCSS PEG prova','--loader','\\EFI\\CaskLogicTcssD1Test\\Shell.efi'])
    now=run(['efibootmgr','-v'])
    added=set(re.findall(r'^Boot([0-9A-Fa-f]{4})\*?',now,re.M))-oldids
    assert len(added)==1 and re.search(r'^BootOrder: (.+)$',now,re.M).group(1)=='0000,0001'
    state={'stage':'staged','epoch':time.time(),'entry':added.pop(),'files':files,
           'boot_before':boot,'boot_staged':now,'patch':'D7 mask plus D1 bit26 experiment'}
    STATE.write_text(json.dumps(state,indent=2)+'\n');os.sync()
    print(json.dumps({'stage':'staged','entry':state['entry']}))
