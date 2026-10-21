"""Prepara il collaudo Linux in RAM; --arm richiede la VM arrestata."""
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

R = Path('/root/riscrivo-p2p-tcss-bit-tests-20261021')
SRC = R/'native-sync-probe-package'
DST = Path('/boot/efi/EFI/CaskLogicTcssNative')
STATE = R/'native-sync-gpu-state.json'
VM = 'd6338ea9-6820-b365-bd0f-7d3790ba2ea7'
ARGS = ('initrd=\\EFI\\CaskLogicTcssNative\\probe-initrd.img rdinit=/init '
        'intel_iommu=off iommu=off module_blacklist=nouveau,nvidia_drm,nvidia_modeset '
        'panic=10 loglevel=4 console=tty0')
def run(args): return subprocess.check_output(args, universal_newlines=True)
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
assert os.geteuid()==0 and run(['hostname']).strip()=='hypervisor-host'
assert Path('/sys/class/dmi/id/board_name').read_text().strip()=='AHWSA'
assert run(['findmnt','-n','-o','PARTUUID','/boot/efi']).strip()=='3c6ae711-bbc9-4653-bf09-0baac6b3b380'
boot=run(['efibootmgr','-v'])
assert 'BootNext:' not in boot and 'BootCurrent: 0000' in boot
assert re.search(r'^BootOrder: (.+)$',boot,re.M).group(1)=='0000,0001'
before=json.loads((R/'native-read-state.json').read_text())
for path, item in before['original_files'].items(): assert sha(Path(path))==item['sha256']
files=json.loads((SRC/'files.json').read_text())
assert set(files)=={'probe-kernel.efi','probe-initrd.img','IDENTITY.txt'}
assert files['probe-kernel.efi']=='9f55ef7253055a9cf68f8a04323c93dead2fca617386d842fbde9ca7b178b27e'
for name,digest in files.items(): assert sha(SRC/name)==digest
if sys.argv[1:]==['--arm']:
    state=json.loads(STATE.read_text())
    assert state['stage']=='staged' and state['files']==files
    for name,digest in files.items(): assert sha(DST/name)==digest
    assert run(['xe','vm-param-get','uuid='+VM,'param-name=power-state']).strip()=='halted'
    assert run(['xe','vm-list','power-state=running','is-control-domain=false','--minimal']).strip()=='', 'Another VM is still running'
    values={}
    for bdf,expected in [('0000:00:01.0',0x8077),('0000:00:07.0',0x9077),('0000:00:07.2',0x9077)]:
        fd=os.open('/sys/bus/pci/devices/'+bdf+'/config',os.O_RDONLY)
        try: values[bdf]=struct.unpack('<I',os.pread(fd,4,0xd0))[0]
        finally: os.close(fd)
        assert values[bdf]==expected,(bdf,values[bdf])
    assert not (DST/'result.log').exists() and not (DST/'kernel.log').exists()
    state['ccfg_before']=values
    run(['efibootmgr','--bootnext',state['entry']])
    armed=run(['efibootmgr','-v'])
    assert 'BootNext: '+state['entry'] in armed
    assert re.search(r'^BootOrder: (.+)$',armed,re.M).group(1)=='0000,0001'
    state.update(stage='armed',epoch_armed=time.time(),boot_armed=armed)
    STATE.write_text(json.dumps(state,indent=2)+'\n');os.sync()
    print(json.dumps({'armed':True,'entry':state['entry']}))
else:
    assert not sys.argv[1:] and not STATE.exists() and not DST.exists()
    source=run(['findmnt','-n','-o','SOURCE','/boot/efi']).strip()
    disk=re.fullmatch(r'(/dev/nvme\d+n\d+)p4',source).group(1)
    shutil.copytree(str(SRC),str(DST))
    for name,digest in files.items(): assert sha(DST/name)==digest
    ids=set(re.findall(r'^Boot([0-9A-Fa-f]{4})\*?',boot,re.M))
    run(['efibootmgr','--create-only','--disk',disk,'--part','4',
         '--label','CaskLogic TCSS GPU sync','--loader',
         '\\EFI\\CaskLogicTcssNative\\probe-kernel.efi','--unicode',ARGS])
    now=run(['efibootmgr','-v'])
    added=set(re.findall(r'^Boot([0-9A-Fa-f]{4})\*?',now,re.M))-ids
    assert len(added)==1
    assert re.search(r'^BootOrder: (.+)$',now,re.M).group(1)=='0000,0001'
    state={'stage':'staged','epoch':time.time(),'entry':added.pop(),'files':files,
           'kernel_args':ARGS,'boot_before':boot,'boot_staged':now,'automatic_return_seconds':180}
    STATE.write_text(json.dumps(state,indent=2)+'\n');os.sync()
    print(json.dumps({'staged':True,'entry':state['entry'],'armed':False}))
