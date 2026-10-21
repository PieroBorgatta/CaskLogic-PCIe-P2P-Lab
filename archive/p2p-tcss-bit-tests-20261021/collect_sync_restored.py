"""Raccoglie solo dopo il ripristino UEFI e ne verifica la rilettura integrale."""
from pathlib import Path
import hashlib,json,os,re,shutil,struct,subprocess,time
R=Path('/root/riscrivo-p2p-tcss-bit-tests-20261021')
D=Path('/boot/efi/EFI/CaskLogicTcssSyncTest')
O=R/'native-sync-restore-results'
SOURCE=R/'native-sync-flash-package'
ORIGINAL='b81e705a87c89a668c4bbddd3538a82ccd5ebea4b156ce2d79762147310deba9'
CANDIDATE='c37f53eec3a5702d4a3e7b9d55bf382050100e324f2ec1210d9b98439cabedf4'
def run(a):return subprocess.check_output(a,universal_newlines=True)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def text(p):
    b=p.read_bytes();return b.decode('utf-16' if b[:2] in (b'\xff\xfe',b'\xfe\xff') else 'utf-8').strip()
assert os.geteuid()==0 and run(['hostname']).strip()=='hypervisor-host'
assert not O.exists()
assert run(['findmnt','-n','-o','PARTUUID','/boot/efi']).strip()=='3c6ae711-bbc9-4653-bf09-0baac6b3b380'
boot=run(['efibootmgr','-v'])
assert 'BootNext:' not in boot and 'BootCurrent: 0000' in boot
assert re.search(r'^BootOrder: (.+)$',boot,re.M).group(1)=='0000,0001'
state=json.loads((R/'native-sync-firmware-state.json').read_text())
assert state['stage']=='restore_armed'
files=json.loads((SOURCE/'files.json').read_text())
assert files==state['files'] and files['ORIGINAL.bin']==ORIGINAL
for n,h in files.items():
    assert sha(SOURCE/n)==h
    assert sha(D/n)==(files['startup-restore.nsh'] if n=='startup.nsh' else h)
assert sha(D/'region-after.bin')==CANDIDATE
assert sha(D/'region-restored.bin')==ORIGINAL
observed=(D/'region-restored.bin').read_bytes();original=(SOURCE/'ORIGINAL.bin').read_bytes()
assert len(observed)==len(original)==0x1e000 and observed==original
assert text(D/'restore-status.txt')=='ORIGINAL_RESTORED_AND_READBACK_VERIFIED'
assert 'TcssRegionGate Sync v4 RESTORE_CHECK PASS' in text(D/'RESTORED.flag')
gate=text(D/'region-restore-gate.txt')
assert 'readback_byte_mismatches=0x0000000000000000' in gate and 'phase=all_checks_passed_before_flag' in gate and 'result=FAIL' not in gate
registers={}
for bdf,ident,wanted in [('0000:00:01.0',0x460d8086,0x04008077),('0000:00:07.0',0x466e8086,0x0e009077),('0000:00:07.2',0x462f8086,0x0e009077)]:
    fd=os.open('/sys/bus/pci/devices/'+bdf+'/config',os.O_RDONLY)
    try:actualid=struct.unpack('<I',os.pread(fd,4,0))[0];value=struct.unpack('<I',os.pread(fd,4,0xd0))[0]
    finally:os.close(fd)
    assert actualid==ident and value==wanted
    registers[bdf]={'identity':hex(actualid),'CCFG':hex(value)}
baseline=json.loads((R/'native-read-state.json').read_text())
for p,v in baseline['original_files'].items():assert sha(Path(p))==v['sha256']
shutil.copytree(str(D),str(O))
collected={str(p.relative_to(D)):sha(p) for p in D.rglob('*') if p.is_file()}
for n,h in collected.items():assert sha(O/n)==h
shutil.copy2(str(R/'native-sync-firmware-state.json'),str(O/'native-sync-firmware-state.json'))
(O/'collected-sha256.json').write_text(json.dumps(collected,indent=2)+'\n')
proof={'status':'ORIGINAL_RESTORED_AND_READBACK_VERIFIED','collected_epoch':time.time(),'region_start':0x1b0b000,'region_length':0x1e000,'original_sha256':ORIGINAL,'candidate_read_before_restore_sha256':CANDIDATE,'readback_mismatches':0,'ccfg':registers,'original_boot_files_unchanged':True,'boot':boot,'collected_files':len(collected),'SaSetup_preservation_basis':'Restore writes only the FSP span; SaSetup lies outside that span and is not independently read by this collector'}
(O/'restore-verification.json').write_text(json.dumps(proof,indent=2)+'\n');os.sync()
print(json.dumps(proof))
