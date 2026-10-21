import argparse,csv,json,os,signal,subprocess,threading,time
from pathlib import Path

P=argparse.ArgumentParser();P.add_argument('plan');A=P.parse_args()
ROOT=Path(__file__).resolve().parent;PLAN=json.loads((ROOT/A.plan).read_text())
LABEL=Path(A.plan).stem;D=ROOT/LABEL;D.mkdir(exist_ok=False)
NAME='riscrivo-gpu-followup';STOP=threading.Event();DONE=threading.Event();PHASE='starting';REASON=None;RESULTS=[]
def atomic(p,v):
 t=p.with_suffix('.tmp');t.write_text(json.dumps(v,indent=2));t.replace(p)
def train_off():
 return subprocess.run(['systemctl','is-active','riscrivo-training.service'],capture_output=True,text=True,timeout=5).stdout.strip()=='inactive'
def stop():
 subprocess.run(['docker','stop','--timeout','5',NAME],capture_output=True,timeout=12)
def monitor():
 global REASON
 fields=['uuid','name','temperature.gpu','fan.speed','utilization.gpu','memory.used','power.draw','power.limit','clocks.current.sm','clocks_event_reasons.active']
 failures=0
 with (D/'telemetry.jsonl').open('a',buffering=1) as f:
  while not DONE.is_set():
   try:
    if not train_off():raise RuntimeError('original training is active')
    p=subprocess.run(['nvidia-smi','--query-gpu='+','.join(fields),'--format=csv,noheader,nounits'],capture_output=True,text=True,check=True,timeout=8)
    g=[dict(zip(fields,[v.strip() for v in row])) for row in csv.reader(p.stdout.splitlines())]
    x={'epoch':time.time(),'phase':PHASE,'gpus':g};f.write(json.dumps(x)+'\n');atomic(D/'latest.json',x)
    if any(float(v['temperature.gpu'])>=90 for v in g):REASON='temperature reached 90 C';STOP.set()
    failures=0
   except Exception as e:
    failures+=1;f.write(json.dumps({'epoch':time.time(),'error':repr(e)})+'\n')
    if failures>=3:REASON=repr(e);STOP.set()
   if STOP.is_set():
    try:stop()
    except Exception:pass
   DONE.wait(2)
def cancel(*_):
 global REASON
 REASON='requested stop';STOP.set()
signal.signal(signal.SIGTERM,cancel);signal.signal(signal.SIGINT,cancel)
assert train_off()
thread=threading.Thread(target=monitor,daemon=True);thread.start()
try:
 for s in PLAN:
  if STOP.is_set():raise RuntimeError(REASON)
  PHASE=s['name'];start=time.time();atomic(D/'status.json',{'state':'RUNNING','phase':PHASE,'started_epoch':start,'completed':len(RESULTS)})
  cmd=['docker','run','--rm','--name',NAME,'--gpus','all','--network','none','--cpus','8','--memory','12g','--shm-size','2g','--ulimit','memlock=-1',
       '-v',str(ROOT)+':/audit','-v','/mnt/llm/riscrivo/runtime/reports/gpu-audit-20261020:/tools:ro','-w',s.get('cwd','/audit'),
       '-e','OMP_NUM_THREADS=2','-e','LD_LIBRARY_PATH=/tools/nccl-sdk/lib:/usr/local/cuda/lib64:/usr/local/nvidia/lib64']
  for k,v in s.get('env',{}).items():cmd+=['-e',k+'='+str(v)]
  cmd+=['--entrypoint',s['command'][0],'casklogic-riscrivo:torch2.10-cu126']+s['command'][1:]
  print('START',PHASE,flush=True)
  timeout=False
  with (D/(PHASE+'.log')).open('w') as f:
   p=subprocess.Popen(cmd,stdout=f,stderr=subprocess.STDOUT)
   while p.poll() is None:
    if STOP.is_set() or time.time()-start>s.get('timeout',300):timeout=not STOP.is_set();stop();break
    time.sleep(1)
   rc=p.wait(timeout=15)
  result={**s,'started_epoch':start,'seconds':time.time()-start,'returncode':rc,'timed_out':timeout};RESULTS.append(result);atomic(D/'stages.json',RESULTS)
  print('END',PHASE,rc,flush=True)
  if STOP.is_set():raise RuntimeError(REASON)
  if s.get('required',False) and (rc or timeout):raise RuntimeError('required stage failed: '+PHASE)
 atomic(D/'status.json',{'state':'COMPLETED','completed':len(RESULTS),'finished_epoch':time.time()})
except BaseException as e:
 atomic(D/'status.json',{'state':'FAILED','phase':PHASE,'error':repr(e),'reason':REASON});raise
finally:
 DONE.set();thread.join(timeout=12)
