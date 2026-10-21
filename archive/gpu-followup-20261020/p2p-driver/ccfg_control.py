from pathlib import Path
import struct,json,time,sys
P=Path('/root/riscrivo-p2p-ccfg-backup.json');mode=sys.argv[1];mask=0x16000000
bdfs=['0000:00:01.0','0000:00:07.0']
def rd(f,o):f.seek(o);return struct.unpack('<I',f.read(4))[0]
def wr(f,o,v):f.seek(o);f.write(struct.pack('<I',v));return rd(f,o)
def rows():
 out=[]
 for b in bdfs:
  with open('/sys/bus/pci/devices/'+b+'/config','rb',buffering=0) as f:
   out.append({'bdf':b,'id':hex(rd(f,0)),'ccfg':rd(f,0xd0)})
 return out
if mode=='capture':assert not P.exists();P.write_text(json.dumps(rows(),indent=2))
elif mode in ['peer','fabric']:
 assert P.exists()
 for row in json.loads(P.read_text()):
  with open('/sys/bus/pci/devices/'+row['bdf']+'/config','r+b',buffering=0) as f:
   assert rd(f,0)&65535==0x8086
   v=rd(f,0xd0)&~0x06000000
   if mode=='fabric':v|=0x10000000
   got=wr(f,0xd0,v);assert got&mask==v&mask,(row,hex(v),hex(got))
elif mode=='restore':
 if P.exists():
  for r in json.loads(P.read_text()):
   with open('/sys/bus/pci/devices/'+r['bdf']+'/config','r+b',buffering=0) as f:wr(f,0xd0,(rd(f,0xd0)&~mask)|(r['ccfg']&mask))
  P.rename('/root/riscrivo-p2p-ccfg-restored-'+str(int(time.time()))+'.json')
elif mode!='observe':raise ValueError(mode)
out={'epoch':time.time(),'mode':mode,'rows':rows()};print(json.dumps(out))
with open('/root/riscrivo-p2p-ccfg-events.jsonl','a') as f:f.write(json.dumps(out)+'\n')
