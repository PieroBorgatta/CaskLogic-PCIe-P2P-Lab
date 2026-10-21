from pathlib import Path
import json,subprocess,time,os
R=Path(__file__).parent
before=json.loads((R/'before.json').read_text());active=[s for s,v in before['services'].items() if v=='active'];events=[]
LABEL=os.environ.get('TRIAL_LABEL','static-capped');MOD=R/(os.environ.get('TRIAL_MODULES','compiled-static'));PARAM=os.environ.get('TRIAL_PARAMS','ForceP2P=0x11;RMForceP2PType=1;RMPcieP2PType=1;OverrideFbSize=0x1e00;RMForceStaticBar1=1')
def run(c,check=True,timeout=30):
 p=subprocess.run(c,capture_output=True,text=True,timeout=timeout);v={'epoch':time.time(),'command':c,'rc':p.returncode,'out':p.stdout,'err':p.stderr};events.append(v);(R/(LABEL+'-events.json')).write_text(json.dumps(events,indent=2));print(json.dumps(v),flush=True)
 if check and p.returncode:raise RuntimeError(str(c))
 return p
def unload():
 for m in ['nvidia_uvm','nvidia_drm','nvidia_modeset','nvidia']:run(['modprobe','-r',m],False)
assert run(['systemctl','is-active','riscrivo-training.service'],False).stdout.strip()=='inactive'
try:
 for s in active+['nvidia-cdi-refresh.service']:run(['systemctl','stop',s],False)
 run(['systemctl','mask','--runtime','nvidia-cdi-refresh.service'])
 u=run(['fuser','/dev/nvidia0','/dev/nvidia1','/dev/nvidiactl','/dev/nvidia-uvm'],False)
 assert u.returncode!=0,'GPU users remain'
 unload()
 run(['insmod',str(MOD/'nvidia.ko'),'NVreg_RegistryDwords='+PARAM],timeout=40)
 for m in ['nvidia_uvm','nvidia_modeset','nvidia_drm']:run(['modprobe',m])
 run(['nvidia-smi','-q','-d','MEMORY'])
 for s in reversed(active):run(['systemctl','start',s],False)
 cmd=['docker','run','--rm','--name','riscrivo-compiled-p2p','--gpus','all','--network','none','--cpus','4','--memory','2g','-v',str(R)+':/trial','-e','LD_LIBRARY_PATH=/trial/libcuda-experiment:/usr/local/cuda/lib64:/usr/local/nvidia/lib64','--entrypoint','/trial/'+os.environ.get('TRIAL_PROGRAM','peer_verify'),'casklogic-riscrivo:torch2.10-cu126']
 run(cmd,False,timeout=45)
 (R/(LABEL+'-dmesg.txt')).write_text(subprocess.run(['dmesg'],capture_output=True,text=True).stdout)
finally:
 run(['docker','rm','-f','riscrivo-compiled-p2p'],False)
 for s in active+['nvidia-cdi-refresh.service']:run(['systemctl','stop',s],False)
 unload();run(['modprobe','nvidia'],timeout=40)
 for m in ['nvidia_uvm','nvidia_modeset','nvidia_drm']:run(['modprobe',m])
 run(['systemctl','unmask','--runtime','nvidia-cdi-refresh.service'],False)
 for s in reversed(active):run(['systemctl','start',s],False)
 run(['nvidia-smi','--query-gpu=uuid,name,memory.total,power.limit','--format=csv'])
 print('STOCK_DRIVER_RESTORED',flush=True)
