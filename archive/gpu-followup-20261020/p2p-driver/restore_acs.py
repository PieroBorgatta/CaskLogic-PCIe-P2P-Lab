from pathlib import Path
import json,os,struct
rows=json.loads(Path('/root/riscrivo-p2p-acs-backup.json').read_text())
for r in rows:
 with open('/sys/bus/pci/devices/'+r['bdf']+'/config','r+b',buffering=0) as f:
  f.seek(r['cap_offset']+6);f.write(struct.pack('<H',r['acs_control']));f.seek(r['cap_offset']+6);print(r['bdf'],struct.unpack('<H',f.read(2))[0])
