"""Read-only evidence replay; no hardware, CUDA, firmware or register access."""
from pathlib import Path
import importlib.util,json,subprocess,sys,tempfile
R=Path(__file__).resolve().parent
CCFG={'0000:00:01.0':(0,0x04008077),'0000:00:07.0':(0,0x0e009077),'0000:00:07.2':(0,0x0e009077)}
def one(name,validator):
 d=R/name
 spec=importlib.util.spec_from_file_location('run_'+name.replace('-','_'),d/validator)
 v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
 got=v.validate_log((d/'results/result.log').read_text(),CCFG,(d/'results/kernel-research.log').read_text())
 want=json.loads((d/'results/qualified.json').read_text())
 assert got==want,(name,got.get('counter_error'))
 print(name,got['status'])
def main():
 if len(sys.argv)==3:
  one(sys.argv[1],sys.argv[2]);return
 for n,v in [('cpu-config','counter_log_validation.py'),('cpu-mmio','mmio_log_validation.py'),('gpu','gpu_log_validation.py')]:
  subprocess.run([sys.executable,str(Path(__file__).resolve()),n,v],check=True)
 analyzer=R.parent/'payload-diagnostics/analyze_payloads.py'
 with tempfile.TemporaryDirectory() as temporary:
  out=Path(temporary)/'payload.json'
  subprocess.run([sys.executable,str(analyzer),str(R/'gpu/results/payload'),'--output',str(out)],check=True)
  assert json.loads(out.read_text())==json.loads((R/'gpu/payload-analysis.json').read_text())
 print('All three qualifications and 36 full payload analyses match.')
if __name__=='__main__':main()
