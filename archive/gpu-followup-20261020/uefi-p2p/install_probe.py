from pathlib import Path
import subprocess,json,re,shutil,hashlib,time,os
R=Path('/root/riscrivo-uefi-p2p');before=json.loads((R/'before.json').read_text());src=R/'CaskLogicP2P';dst=Path('/boot/efi/EFI/CaskLogicP2P')
def cmd(c):return subprocess.check_output(c,universal_newlines=True)
current=cmd(['efibootmgr','-v']);assert 'BootNext:' not in current
order=re.search(r'^BootOrder: (.+)$',current,re.M).group(1);assert order=='0000,0001'
assert Path('/sys/class/dmi/id/board_name').read_text().strip()=='AHWSA'
assert Path('/sys/class/dmi/id/bios_version').read_text().strip()=='1.26'
assert cmd(['findmnt','-n','-o','SOURCE','/boot/efi']).strip()=='/dev/nvme1n1p4'
for name,data in before['files'].items():assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==data['sha256'],name
assert not dst.exists();shutil.copytree(src,dst)
assert hashlib.sha256((dst/'Shell.efi').read_bytes()).hexdigest()=='24dcc034bf6a5158f43b23b71a16acbfdcf1597de55aa309f7f6ac5af90666e6'
assert hashlib.sha256((dst/'setup_var.efi').read_bytes()).hexdigest()=='cbe5777b61276d3f3506a28b34845326e92f6c171bff59177e3912fe20f49840'
oldids=set(re.findall(r'^Boot([0-9A-Fa-f]{4})\*?',current,re.M));newid=None
try:
 output=cmd(['efibootmgr','--create-only','--disk','/dev/nvme1n1','--part','4','--label','CaskLogic P2P lettura','--loader','\\EFI\\CaskLogicP2P\\Shell.efi']);print(output)
 now=cmd(['efibootmgr','-v']);newids=set(re.findall(r'^Boot([0-9A-Fa-f]{4})\*?',now,re.M))-oldids;assert len(newids)==1,newids
 newid=newids.pop();assert re.search(r'^BootOrder: (.+)$',now,re.M).group(1)==order
 state={'epoch':time.time(),'entry':newid,'boot_order_before':order,'path':str(dst),'stage':'read_probe','bios_setting_writes':False};(R/'state.json').write_text(json.dumps(state,indent=2))
 print(cmd(['efibootmgr','--bootnext',newid]));os.sync();after=cmd(['efibootmgr','-v']);assert 'BootNext: '+newid in after
 assert re.search(r'^BootOrder: (.+)$',after,re.M).group(1)==order
 (R/'prepared-boot.txt').write_text(after);print('PREPARED_ONCE_READ_ONLY')
except Exception:
 if newid:
  subprocess.call(['efibootmgr','--delete-bootnext']);subprocess.call(['efibootmgr','--bootnum',newid,'--delete-bootnum'])
 raise
