from pathlib import Path
import hashlib,json,os,re,shutil,subprocess,sys,time
R=Path('/root/riscrivo-p2p-tcss-bit-tests-20261021')
assert len(sys.argv)==2 and re.fullmatch(r'[a-z0-9-]+',sys.argv[1])
tag=sys.argv[1]
assert os.geteuid()==0 and subprocess.check_output(['hostname']).decode().strip()=='hypervisor-host'
D=Path('/boot/efi/EFI/CaskLogicTcssNative');O=R/(tag+'-gpu-results')
assert not O.exists()
S=R/(tag+'-gpu-state.json');state=json.loads(S.read_text())
assert state['stage']=='armed'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for n,h in state['files'].items():assert sha(D/n)==h
boot=subprocess.check_output(['efibootmgr','-v']).decode()
assert 'BootNext:' not in boot and 'BootCurrent: 0000' in boot and 'BootOrder: 0000,0001' in boot
assert (D/'result.log').stat().st_size>0 and (D/'kernel.log').stat().st_size>0
O.mkdir()
for n in ['result.log','kernel.log','files.json','build-manifest.json']:
 shutil.copy2(str(D/n),str(O/n))
for n in ['before-driver','after-relocation','after-driver','after-test']:
 if (D/n).is_dir():shutil.copytree(str(D/n),str(O/n))
for n in ['dmar-before-driver.bin','dmar-after-test.bin','vtd-before-driver.log','vtd-after-test.log']:
 if (D/n).is_file():shutil.copy2(str(D/n),str(O/n))
shutil.copy2(str(S),str(O/S.name))
files={str(p.relative_to(O)):sha(p) for p in O.rglob('*') if p.is_file()}
for n in files:
 if n==S.name:assert files[n]==sha(S)
 else:assert files[n]==sha(D/n)
(O/'collected-sha256.json').write_text(json.dumps(files,indent=2)+'\n')
os.sync()
print(json.dumps({'result_dir':str(O),'verified_files':len(files),'collected_epoch':time.time()}))
