"""Pacchetto secondo collaudo: D7 più unico bit26 del ramo PEG."""
from pathlib import Path
import hashlib
import json
import shutil
R=Path(__file__).resolve().parent
F=R/'firmware-candidate-d1'
P=R/'native-d1-flash-package'
P.mkdir(exist_ok=True)
profile=json.loads((F/'flash-profile.json').read_text())
start,size=profile['region_start'],profile['region_bytes']
assert start%4096==0 and size%4096==0
assert start<=0x1b16000 and start+size>=0x1b29000
assert (0x1b02b60&~4095)<=start and start+size<=((0x1b02b60+154845+4095)&~4095)
for name in ['ORIGINAL.bin','CURRENT.bin','CANDIDATE.bin']:
    data=(F/name).read_bytes()
    assert len(data)==size and hashlib.sha256(data).hexdigest()==profile[name.split('.')[0].lower()+'_sha256']
    shutil.copyfile(F/name,P/name)
for name in ['RegionPre.efi','RegionPost.efi','RegionRestore.efi']:
    shutil.copyfile(F/name,P/name)
for name in ['Shell.efi','Fpt.efi']:
    shutil.copyfile(R/'native-read-package'/name,P/name)
for source,target in [('native-flash-package/startup.nsh','startup.nsh'),
                      ('startup-restore.nsh','startup-restore.nsh')]:
    text=(R/source).read_bytes().decode('utf-16')
    text=text.replace('CaskLogicTcssTest','CaskLogicTcssD1Test')
    text=text.replace('0x01B16000',f'0x{start:08X}').replace('0x00013000',f'0x{size:08X}')
    text=text.replace('19 settori',str(size//4096)+' settori')
    (P/target).write_bytes(text.encode('utf-16'))
files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in P.iterdir() if p.is_file() and p.name!='files.json'}
(P/'files.json').write_text(json.dumps(files,indent=2)+'\n')
print(json.dumps(files,indent=2))
