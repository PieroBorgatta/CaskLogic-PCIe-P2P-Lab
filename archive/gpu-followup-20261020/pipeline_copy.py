import json,statistics,time,ctypes
from pathlib import Path
import torch
torch.set_num_threads(2)
size=512*1024**2;unit=8*1024**2;results=[]
for src,dst in [(0,1),(1,0)]:
 torch.cuda.set_device(src);source=torch.empty(size,device=src,dtype=torch.uint8)
 for offset in range(0,size,unit):source[offset:offset+unit].fill_(17+offset//unit)
 target=torch.empty(size,device=dst,dtype=torch.uint8)
 for chunk_mib in [8,32,128,512]:
  chunk=chunk_mib*1024**2;hosts=[torch.empty(chunk,pin_memory=True,dtype=torch.uint8) for _ in range(2)]
  with torch.cuda.device(src):send=torch.cuda.Stream()
  with torch.cuda.device(dst):recv=torch.cuda.Stream()
  def transfer():
   ready=[torch.cuda.Event() for _ in range(2)];free=[torch.cuda.Event() for _ in range(2)]
   for index,offset in enumerate(range(0,size,chunk)):
    slot=index%2
    with torch.cuda.device(src),torch.cuda.stream(send):
     if index>=2:send.wait_event(free[slot])
     hosts[slot].copy_(source[offset:offset+chunk],non_blocking=True);ready[slot].record(send)
    with torch.cuda.device(dst),torch.cuda.stream(recv):
     recv.wait_event(ready[slot]);target[offset:offset+chunk].copy_(hosts[slot],non_blocking=True);free[slot].record(recv)
   send.synchronize();recv.synchronize()
  torch.cuda.synchronize(src);transfer();samples=[]
  for _ in range(5):
   start=time.perf_counter();transfer();samples.append(time.perf_counter()-start)
  for offset in range(0,size,unit):assert bool(torch.all(target[offset:offset+unit]==17+offset//unit)),(src,dst,chunk_mib,offset)
  row={'source':src,'destination':dst,'chunk_MiB':chunk_mib,'buffers':2,'bytes':size,'seconds':samples,'median_GBps':size/statistics.median(samples)/1e9,'integrity':True};results.append(row);print(json.dumps(row),flush=True)
  del hosts
 del source,target;torch.cuda.empty_cache()
Path('/audit/pipelined_transfers.json').write_text(json.dumps(results,indent=2))
