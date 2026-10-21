"""Ripete la stessa prova nativa, dopo verifica dei nuovi valori D1 e D7."""
from pathlib import Path
import hashlib
import json
import os
import re
import struct
import subprocess
import time
R=Path('/root/riscrivo-p2p-tcss-bit-tests-20261021')
D=Path('/boot/efi/EFI/CaskLogicTcssNative')
VM='d6338ea9-6820-b365-bd0f-7d3790ba2ea7'
def run(args): return subprocess.check_output(args,universal_newlines=True)
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
assert os.geteuid()==0 and run(['hostname']).strip()=='hypervisor-host'
assert Path('/sys/class/dmi/id/board_name').read_text().strip()=='AHWSA'
assert run(['findmnt','-n','-o','PARTUUID','/boot/efi']).strip()=='3c6ae711-bbc9-4653-bf09-0baac6b3b380'
assert run(['xe','vm-param-get','uuid='+VM,'param-name=power-state']).strip()=='halted'
boot=run(['efibootmgr','-v'])
assert 'BootNext:' not in boot and 'BootCurrent: 0000' in boot
assert re.search(r'^BootOrder: (.+)$',boot,re.M).group(1)=='0000,0001'
state=json.loads((R/'native-gpu-state.json').read_text())
assert state['entry']=='0003' and 'Boot0003* CaskLogic TCSS GPU nativo' in boot
files=json.loads((R/'native-d1-probe-package/files.json').read_text())
for name,digest in files.items(): assert sha(D/name)==digest
values={}
for bdf,expected in [('0000:00:01.0',0x8077),('0000:00:07.0',0x9077),('0000:00:07.2',0x9077)]:
    f=os.open('/sys/bus/pci/devices/'+bdf+'/config',os.O_RDONLY)
    try: values[bdf]=struct.unpack('<I',os.pread(f,4,0xd0))[0]
    finally: os.close(f)
    assert values[bdf]==expected,(bdf,values[bdf])
for name in ['result.log','kernel.log']:
    assert (R/'native-gpu-results'/name).read_bytes()==(D/name).read_bytes()
    (D/name).unlink()
run(['efibootmgr','--bootnext','0003'])
now=run(['efibootmgr','-v'])
assert 'BootNext: 0003' in now
(R/'native-d1-gpu-state.json').write_text(json.dumps({'stage':'armed','epoch':time.time(),
    'boot_armed':now,'ccfg_before':values,'probe_files':files,
    'probe_change':'All GPU frees deferred until four data comparisons; monotonic markers'},indent=2)+'\n')
os.sync()
print(json.dumps({'armed':True,'entry':'0003','ccfg_before':values}))
