"""Sostituisce solo l'immagine RAM temporanea, dopo backup e confronto hash."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess
R=Path('/root/riscrivo-p2p-tcss-bit-tests-20261021')
S=R/'native-d1-probe-package'
D=Path('/boot/efi/EFI/CaskLogicTcssNative')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(a):return subprocess.check_output(a,universal_newlines=True)
assert os.geteuid()==0 and run(['hostname']).strip()=='hypervisor-host'
assert run(['findmnt','-n','-o','PARTUUID','/boot/efi']).strip()=='3c6ae711-bbc9-4653-bf09-0baac6b3b380'
assert 'BootNext:' not in run(['efibootmgr'])
old=json.loads((R/'native-gpu-state.json').read_text())
for name,digest in old['files'].items():
    assert sha(D/name)==digest
    assert sha(R/'native-probe-package'/name)==digest
for name in ['result.log','kernel.log']:
    assert (R/'native-gpu-results'/name).read_bytes()==(D/name).read_bytes()
files=json.loads((S/'files.json').read_text())
assert set(files)=={'probe-kernel.efi','probe-initrd.img','IDENTITY.txt'}
manifest=json.loads((S/'build-manifest.json').read_text())
assert files['probe-kernel.efi']==old['files']['probe-kernel.efi']==manifest['kernel_sha256']
assert files['probe-initrd.img']==manifest['initrd_sha256']
assert files['IDENTITY.txt']==old['files']['IDENTITY.txt']
for name,digest in files.items(): assert sha(S/name)==digest
for name,digest in files.items():
    if sha(D/name)!=digest: shutil.copyfile(str(S/name),str(D/name))
    assert sha(D/name)==digest
shutil.copyfile(str(S/'build-manifest.json'),str(D/'build-manifest.json'))
shutil.copyfile(str(S/'files.json'),str(D/'files.json'))
os.sync();print(json.dumps({'native_d1_probe_staged':True,'files':files}))
