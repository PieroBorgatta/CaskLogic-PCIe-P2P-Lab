"""Tentativo reversibile: soli parametri del modulo caricato, nessuna installazione."""
from pathlib import Path
import json,subprocess,time
R=Path('/mnt/llm/riscrivo/runtime/reports/gpu-followup-20261020/p2p-driver')
before=json.loads((R/'before.json').read_text());events=[];active=[s for s,v in before['services'].items() if v=='active']
def run(c,check=True,timeout=25):
 p=subprocess.run(c,capture_output=True,text=True,timeout=timeout);row={'epoch':time.time(),'command':c,'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr};events.append(row);(R/'parameter-events.json').write_text(json.dumps(events,indent=2));print(json.dumps(row),flush=True)
 if check and p.returncode:raise RuntimeError(str(c))
 return p
query='''import ctypes,json
c=ctypes.CDLL("libcuda.so.1");assert c.cuInit(0)==0
rows=[]
for a,b in [(0,1),(1,0)]:
 v=ctypes.c_int();rc=c.cuDeviceCanAccessPeer(ctypes.byref(v),a,b);rows.append({"source":a,"destination":b,"rc":rc,"access":v.value})
print(json.dumps(rows))
'''
def unload():
 for m in ['nvidia_uvm','nvidia_drm','nvidia_modeset','nvidia']:run(['modprobe','-r',m])
def load(extra=None):
 run(['modprobe','nvidia']+(extra or []),timeout=40)
 for m in ['nvidia_uvm','nvidia_modeset','nvidia_drm']:run(['modprobe',m])
ok=False
try:
 assert run(['systemctl','is-active','riscrivo-training.service'],check=False).stdout.strip()=='inactive'
 for s in active:run(['systemctl','stop',s])
 users=run(['fuser','/dev/nvidia0','/dev/nvidia1','/dev/nvidiactl','/dev/nvidia-uvm'],check=False)
 if users.returncode==0:raise RuntimeError('GPU users remain; not unloading')
 unload();load(['NVreg_RegistryDwords=ForceP2P=0x11;RMForceP2PType=1;RMPcieP2PType=1'])
 run(['nvidia-smi','--query-gpu=uuid,name,driver_version,power.limit','--format=csv'])
 p=run(['python3','-c',query],timeout=40);rows=json.loads(p.stdout);ok=all(x['access']==1 for x in rows)
 (R/'parameter-result.json').write_text(json.dumps({'enabled':ok,'peer_access':rows,'runtime_only':True},indent=2))
 if not ok:unload();load()
except BaseException as e:
 (R/'parameter-error.json').write_text(json.dumps({'error':repr(e),'events_count':len(events)},indent=2))
 try:
  unload();load()
 except Exception:pass
 raise
finally:
 for s in reversed(active):run(['systemctl','start',s],check=False)
 print('PARAMETER_TRIAL_COMPLETE',ok,flush=True)
