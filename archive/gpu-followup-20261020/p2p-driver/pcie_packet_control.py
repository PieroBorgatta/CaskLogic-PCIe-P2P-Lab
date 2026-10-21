from pathlib import Path
import json,struct,sys,time
B=Path('/root/riscrivo-p2p-packet-backup.json');mode=sys.argv[1];rows=[];mask=0x70e0
if mode=='capture':
 assert not B.exists(),'Backup already exists'
 for bdf in ['0000:00:01.0','0000:01:00.0','0000:01:00.1','0000:00:07.0','0000:04:00.0','0000:05:00.0','0000:06:00.0','0000:06:00.1']:
  with open('/sys/bus/pci/devices/'+bdf+'/config','rb') as f:
   f.seek(0x34);p=f.read(1)[0];seen=set()
   while p and p not in seen:
    seen.add(p);f.seek(p);id,nxt=f.read(2)
    if id==0x10:
     f.seek(p+8);ctrl=struct.unpack('<H',f.read(2))[0];rows.append({'bdf':bdf,'offset':p+8,'control':ctrl});break
    p=nxt
 B.write_text(json.dumps(rows,indent=2));print(json.dumps(rows));sys.exit(0)
rows=json.loads(B.read_text());observed=[]
for r in rows:
 with open('/sys/bus/pci/devices/'+r['bdf']+'/config','r+b' if mode in ['limit','restore'] else 'rb',buffering=0) as f:
  f.seek(r['offset']);v=struct.unpack('<H',f.read(2))[0];new=v
  if mode=='limit':new=v & ~mask
  if mode=='restore':new=(v & ~mask)|(r['control'] & mask)
  if new!=v:f.seek(r['offset']);f.write(struct.pack('<H',new))
  f.seek(r['offset']);now=struct.unpack('<H',f.read(2))[0];observed.append({'bdf':r['bdf'],'before':hex(v),'now':hex(now),'mps_bytes':128<<((now>>5)&7),'mrrs_bytes':128<<((now>>12)&7)})
print(json.dumps({'epoch':time.time(),'mode':mode,'devices':observed}))
