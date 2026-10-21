from pathlib import Path
import ctypes as C,json,subprocess,time,sys
R=Path('/root/riscrivo-p2p-alias');R.mkdir(exist_ok=True);state=R/'state.json';uuid='d6338ea9-6820-b365-bd0f-7d3790ba2ea7'
mode=sys.argv[1];L=C.CDLL('/usr/lib64/libxenctrl.so.4.17',use_errno=True)
L.xc_interface_open.argtypes=[C.c_void_p,C.c_void_p,C.c_uint];L.xc_interface_open.restype=C.c_void_p
L.xc_interface_close.argtypes=[C.c_void_p];L.xc_domain_memory_mapping.argtypes=[C.c_void_p,C.c_uint32,C.c_ulong,C.c_ulong,C.c_ulong,C.c_uint32];L.xc_domain_memory_mapping.restype=C.c_int
h=L.xc_interface_open(None,None,0);assert h
rows=[]
def valid(d):
 try:return subprocess.check_output(['xenstore-read','/local/domain/'+str(d)+'/vm'],universal_newlines=True).strip()=='/vm/'+uuid
 except Exception:return False
def maprow(r,add):
 assert valid(r['domid']),'VM identity changed'
 rc=L.xc_domain_memory_mapping(h,r['domid'],r['gpa']>>12,r['hpa']>>12,r['bytes']>>12,add)
 v={'epoch':time.time(),'mapping':r,'add':add,'rc':rc,'errno':C.get_errno()};print(json.dumps(v),flush=True)
 with (R/'events.jsonl').open('a') as f:f.write(json.dumps(v)+'\n')
 if rc:raise RuntimeError(v)
try:
 if mode=='add':
  assert not state.exists(),'State exists; remove previous experiment first'
  d=int(subprocess.check_output(['xe','vm-param-get','uuid='+uuid,'param-name=dom-id'],universal_newlines=True));assert valid(d)
  for b,gpa,expected in [('0000:01:00.0',0x780000000,0x4000000000),('0000:06:00.0',0x7c0000000,0x4600000000)]:
   bar=Path('/sys/bus/pci/devices/'+b+'/resource').read_text().splitlines()[1].split();hpa=int(bar[0],16);assert hpa==expected
   row={'domid':d,'bdf':b,'gpa':gpa,'hpa':hpa,'bytes':32*1024*1024};maprow(row,1);rows.append(row);state.write_text(json.dumps(rows,indent=2))
 elif mode=='remove':
  rows=json.loads(state.read_text()) if state.exists() else []
  for row in reversed(rows):
   if valid(row['domid']):maprow(row,0)
  if state.exists():state.rename(R/('removed-'+str(int(time.time()))+'.json'))
 else:raise ValueError(mode)
finally:L.xc_interface_close(h)
