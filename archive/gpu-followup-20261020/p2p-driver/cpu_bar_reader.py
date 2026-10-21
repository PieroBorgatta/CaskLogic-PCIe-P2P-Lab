from pathlib import Path
import mmap,os,json,time,struct
R=Path(__file__).parent;rows=[];start=time.time()
for n in range(2):
 while not (R/'cpu-window-request').exists() or (R/'cpu-window-request').read_text().strip()!=str(n):
  if time.time()-start>45:raise TimeoutError('request')
  time.sleep(.05)
 source=int((R/'cpu-window-request').read_text());out={'source_cuda':source,'epoch':time.time(),'bar1_offset':4194304,'gpus':[]}
 for index,bdf in [(0,'0000:00:09.0'),(1,'0000:00:06.0')]:
  try:
   fd=os.open('/sys/bus/pci/devices/'+bdf+'/resource1',os.O_RDONLY|os.O_SYNC)
   with mmap.mmap(fd,4096,flags=mmap.MAP_SHARED,prot=mmap.PROT_READ,offset=4194304) as m:values=list(struct.unpack('<8I',m[:32]))
   os.close(fd);out['gpus'].append({'cuda_index':index,'values':values,'expected_first':12345 if index==source else 0})
  except Exception as e:out['gpus'].append({'cuda_index':index,'error':repr(e)})
 rows.append(out);(R/'cpu-bar-observations.json').write_text(json.dumps(rows,indent=2));(R/'cpu-window-response').write_text('done')

