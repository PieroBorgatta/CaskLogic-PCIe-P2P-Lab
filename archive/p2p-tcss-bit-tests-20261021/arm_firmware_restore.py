"""Prepara e arma il ripristino esatto dei soli settori del collaudo TCSS."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
R=Path('/root/riscrivo-p2p-tcss-bit-tests-20261021')
D=Path('/boot/efi/EFI/CaskLogicTcssTest')
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
assert 'Boot0002* CaskLogic TCSS lettura' in boot
state=json.loads((R/'native-read-state.json').read_text())
for name,details in state['original_files'].items(): assert sha(Path(name))==details['sha256']
expected=json.loads((R/'native-flash-package/files.json').read_text())
for name,digest in expected.items(): assert sha(D/name)==digest
assert sha(D/'region-after.bin')==expected['CANDIDATE.bin']
assert sha(R/'startup-restore.nsh')=='c903f43f5b69e4bb978c606601c0e5a042bdc76bbaedf18a3d9d8af70f0370c7'
assert (R/'native-flash-results/region-after.bin').read_bytes()==(D/'region-after.bin').read_bytes()
shutil.copyfile(str(D/'startup.nsh'),str(R/'startup-flash.executed.nsh'))
shutil.copyfile(str(R/'startup-restore.nsh'),str(D/'startup.nsh'))
assert sha(D/'startup.nsh')==sha(R/'startup-restore.nsh')
run(['efibootmgr','--bootnext','0002'])
now=run(['efibootmgr','-v'])
assert 'BootNext: 0002' in now
(R/'firmware-restore-state.json').write_text(json.dumps({'stage':'armed',
    'epoch':time.time(),'boot_armed':now,'restore_script_sha256':sha(D/'startup.nsh'),
    'target_original_sha256':expected['ORIGINAL.bin']},indent=2)+'\n')
os.sync()
print(json.dumps({'restore_armed':True,'entry':'0002'}))
