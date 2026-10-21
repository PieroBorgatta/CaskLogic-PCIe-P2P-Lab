"""Riscontro finale del percorso CUDA/NCCL, separato dal registro principale."""
from pathlib import Path
import json
import subprocess
import time

ROOT = Path('/mnt/llm/riscrivo/runtime/reports/gpu-audit-20261020')
IMAGE = 'casklogic-riscrivo:torch2.10-cu126'
assert json.loads((ROOT/'status.json').read_text())['state'] == 'COMPLETED'
assert subprocess.run(['systemctl','is-active','riscrivo-training.service'],capture_output=True,text=True).stdout.strip() == 'inactive'
result = {'started_epoch': time.time(), 'reason': 'Verify actual CUDA peer capability and NCCL route after waived P2P tests'}
base = ['docker','run','--rm','--name','riscrivo-gpu-route','--gpus','all','--network','none',
        '--cpus','6','--memory','8g','--shm-size','1g','-v',str(ROOT)+':/audit',
        '-e','OMP_NUM_THREADS=2','-e','LD_LIBRARY_PATH=/audit/nccl-sdk/lib:/usr/local/cuda/lib64:/usr/local/nvidia/lib64']
code = '''import torch,json
d=[{"index":i,"name":torch.cuda.get_device_name(i),"uuid":str(torch.cuda.get_device_properties(i).uuid)} for i in range(torch.cuda.device_count())]
p=[{"source":i,"destination":j,"can_access_peer":torch.cuda.can_device_access_peer(i,j)} for i in range(len(d)) for j in range(len(d)) if i!=j]
print(json.dumps({"devices":d,"cuda_peer_access":p}))
'''
for name, command in [
    ('cuda_peer_confirmation', base+['--entrypoint','python',IMAGE,'-c',code]),
    ('nccl_route_confirmation',base+['-e','NCCL_DEBUG=INFO','-e','NCCL_DEBUG_SUBSYS=INIT,GRAPH,P2P,SHM',
        '--entrypoint','/audit/sources/nccl-tests/build/all_reduce_perf',IMAGE,
        '-b','128M','-e','128M','-g','2','-w','3','-n','10','-c','2','-T','25'])]:
    assert subprocess.run(['systemctl','is-active','riscrivo-training.service'],capture_output=True,text=True).stdout.strip() == 'inactive'
    start=time.time()
    try:
        p=subprocess.run(command,capture_output=True,text=True,timeout=60)
        (ROOT/(name+'.log')).write_text(p.stdout+p.stderr)
        result[name]={'returncode':p.returncode,'seconds':time.time()-start}
        if name=='cuda_peer_confirmation' and p.returncode==0:
            result['cuda_peer']=json.loads(p.stdout)
    except subprocess.TimeoutExpired:
        subprocess.run(['docker','stop','--timeout','5','riscrivo-gpu-route'],capture_output=True,timeout=10)
        result[name]={'timed_out':True,'seconds':time.time()-start}
        break
result['finished_epoch']=time.time()
(ROOT/'route_confirmation.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
