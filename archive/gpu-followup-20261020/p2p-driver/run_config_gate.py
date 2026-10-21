from pathlib import Path
import subprocess,json,time
D=Path(__file__).parent;remote='/mnt/llm/riscrivo/runtime/reports/gpu-followup-20261020/p2p-driver';rows=[]
def ssh(host,cmd,check=True):
 p=subprocess.run(['ssh',host,cmd],capture_output=True,text=True,timeout=20)
 if check and p.returncode:raise RuntimeError(p.stderr+p.stdout)
 return p
try:
 ssh('gpu-vm','rm -f '+remote+'/config-gate-ready '+remote+'/config-gate-go')
 cmd='systemd-run --unit riscrivo-coherent-config-gate-v2 --collect --setenv=TRIAL_LABEL=coherent-config-gate-v2 --setenv=TRIAL_PROGRAM=peer_vmm_config_gate --setenv=TRIAL_MODULES=compiled-coherent --setenv="TRIAL_PARAMS=ForceP2P=0x11;RMForceP2PType=1;RMPcieP2PType=1;RMForceStaticBar1=0" --property=StandardOutput=append:'+remote+'/coherent-config-gate-v2.log --property=StandardError=inherit python3 '+remote+'/trial_compiled.py'
 ssh('gpu-vm',cmd)
 for n in range(2):
  start=time.time()
  while ssh('gpu-vm','cat '+remote+'/config-gate-ready',False).stdout.strip()!=str(n):
   if time.time()-start>55:raise TimeoutError('gate '+str(n))
   time.sleep(.2)
  r={'source_cuda':n,'before':json.loads(ssh('hypervisor-host','python3 /root/riscrivo-p2p-request-control.py observe').stdout),'applied':json.loads(ssh('hypervisor-host','python3 /root/riscrivo-p2p-request-control.py apply').stdout)}
  assert all(not (v['control']&0x810) for v in r['applied']['rows'])
  ssh('gpu-vm','printf '+str(n)+' > '+remote+'/config-gate-go')
  rows.append(r);(D/'coherent-config-gate-v2-host.json').write_text(json.dumps(rows,indent=2));print(json.dumps(r),flush=True)
finally:
 print(ssh('hypervisor-host','python3 /root/riscrivo-p2p-request-control.py restore',False).stdout,flush=True)
 ssh('hypervisor-host','systemctl stop riscrivo-p2p-request-restore-v2.timer',False)
