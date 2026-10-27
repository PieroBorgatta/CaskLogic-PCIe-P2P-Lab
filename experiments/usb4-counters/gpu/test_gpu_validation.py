"""Synthetic composition of prior logs; never represents a new hardware run."""
import unittest
from pathlib import Path
from gpu_log_validation import validate_log,POINTS
R=Path(__file__).resolve().parent
CCFG={'0000:00:01.0':(0,0x04008077),'0000:00:07.0':(0,0x0e009077),'0000:00:07.2':(0,0x0e009077)}
def fixture():
 return (R/'synthetic-fixture.log').read_text(),(R/'synthetic-kernel.log').read_text()

class Validation(unittest.TestCase):
 def test_synthetic_valid(self):
  r,k=fixture();x=validate_log(r,CCFG,k);self.assertTrue(x['protocol_complete'],x);self.assertEqual(x['comparisons'],36);self.assertEqual(len(x['gpu_counter_samples']),288);self.assertFalse(x['P2P_solution_claimed'])
 def test_mutations(self):
  r,k=fixture()
  mutations=[(r.replace('COUNTER_MODULE_UNLOADED=1',''),k),(r.replace('TB_GPU_DRIVER_UNLOADED=1',''),k),(r.replace('bus_master_enable=0','bus_master_enable=1'),k),(r.replace('TB_MMIO_COMMAND_RESTORED observed=0000','TB_MMIO_COMMAND_RESTORED observed=0002'),k),(r.replace('delta=1000','delta=999'),k),(r.replace('elapsed_ns=20000000','elapsed_ns=20000001'),k),(r.replace('point=HOST_PCIE enabled=0','point=HOST_PCIE enabled=1'),k),(r.replace('engine=SM mode=PUSH executor=0','engine=SM mode=PUSH executor=1'),k),(r.replace('stage=source_initialized','stage=missing_source'),k),(r.replace('id=1 stage=IDLE','id=2 stage=IDLE'),k),(r.replace('bytes=1048576 point=HOST_PCIE','bytes=4 point=HOST_PCIE'),k),(r.replace('CUPTI_CASE_END id=36','CUPTI_CASE_END id=35'),k),(r.replace('04008077','04008076'),k),(r,k+'\nWATCHDOG_REBOOT'),(r,k.replace('path_inactive=1','path_inactive=0')),(r,k+'\n'+next(z for z in k.splitlines() if 'CASKTB_COUNTER_PLAN ' in z)),(r,''),(r+'SCRIPT_RC=5\n',k)]
  for a,b in mutations:
   with self.subTest(a=a[-60:],b=b[-60:]):self.assertFalse(validate_log(a,CCFG,b)['protocol_complete'])
if __name__=='__main__':unittest.main()
