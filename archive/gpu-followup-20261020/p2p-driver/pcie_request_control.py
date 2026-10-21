from pathlib import Path
import json,struct,sys,time
P=Path('/root/riscrivo-p2p-request-backup.json');mode=sys.argv[1]
bdfs=['0000:00:01.0','0000:01:00.0','0000:00:07.0','0000:04:00.0','0000:05:00.0','0000:06:00.0']
def word(f,o,v=None):
 f.seek(o)
 if v is not None:f.write(struct.pack('<H',v));f.seek(o)
 return struct.unpack('<H',f.read(2))[0]
def capexp(f):
 ptr=word(f,0x34)&255
 for _ in range(32):
  if not ptr:break
  val=word(f,ptr)
  if val&255==0x10:return ptr
  ptr=(val>>8)&255
 raise RuntimeError('no PCIe capability')
def readall():
 out=[]
 for b in bdfs:
  with open('/sys/bus/pci/devices/'+b+'/config','r+b',buffering=0) as f:
   c=capexp(f);r={'bdf':b,'exp':c,'control':word(f,c+8),'status':word(f,c+10)}
   if b in ['0000:00:01.0','0000:00:07.0']:r['acs']=word(f,0x226)
   out.append(r)
 return out
if mode=='capture':
 assert not P.exists();P.write_text(json.dumps(readall(),indent=2))
elif mode=='apply':
 assert P.exists()
 for r in json.loads(P.read_text()):
  with open('/sys/bus/pci/devices/'+r['bdf']+'/config','r+b',buffering=0) as f:
   o=r['exp']+8;word(f,o,word(f,o)&~0x810)
   if 'acs' in r:word(f,0x226,0)
elif mode=='restore':
 if P.exists():
  for r in json.loads(P.read_text()):
   with open('/sys/bus/pci/devices/'+r['bdf']+'/config','r+b',buffering=0) as f:
    o=r['exp']+8;word(f,o,(word(f,o)&~0x810)|(r['control']&0x810))
    if 'acs' in r:word(f,0x226,r['acs'])
  P.rename('/root/riscrivo-p2p-request-restored-'+str(int(time.time()))+'.json')
elif mode!='observe':raise ValueError(mode)
print(json.dumps({'epoch':time.time(),'mode':mode,'rows':readall()}))
