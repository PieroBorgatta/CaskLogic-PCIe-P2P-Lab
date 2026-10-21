from pathlib import Path
import subprocess,json,time
r=Path('/root/riscrivo-uefi-p2p')
for name,reg,mask in [('attrs-after-bios-backup.json','CAP_EXP+8.w',0x0810),('acs-after-bios-backup.json','226.w',0xffff)]:
 p=r/name
 if not p.exists():continue
 j=json.loads(p.read_text())
 for x in j['rows']:
  subprocess.check_call(['setpci','-s',x['device'],reg+'=%04x:%04x'%(x['value'],mask)])
  after=int(subprocess.check_output(['setpci','-s',x['device'],reg],universal_newlines=True).strip(),16)
  assert after&mask==x['value']&mask,(x,after)
 j.update(restore_required=False,restored_epoch=time.time());p.write_text(json.dumps(j,indent=2))
print('PCI controls restored; persistent BIOS P2P setting retained')
