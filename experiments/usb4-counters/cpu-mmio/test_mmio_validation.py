import unittest
from mmio_log_validation import validate_log,POINTS
CCFG={'0000:00:01.0':(0,0x04008077),'0000:00:07.0':(0,0x0e009077),'0000:00:07.2':(0,0x0e009077)}
def fixture():
 lines=['USB4_COUNTER_RUN_BEGIN version=1 gpu_program_executed=0','module_blacklist=nouveau,nvidia,nvidia_uvm,nvidia_drm,nvidia_modeset','USB4_INSPECTION_GPU_MODULES absent']
 cc=['PEG_CCFG 00:01.0 04008077','TCSS_CCFG 00:07.0 0e009077','TCSS_CCFG 00:07.2 0e009077']
 lines+=cc+['USB4_COUNTER_DATA_DISKS unmounted','COUNTER_MODULE_LOAD_RC=0','TB_MMIO_PROBE_BEGIN version=1 gpu_program_executed=0 mmio_writes=0 command_mask=0002']
 paths=lambda en:['TB_COUNTER_PATH point=%s enabled=%d index=%d valid=1'%(p,en,[0,1,1,0][i]) for i,p in enumerate(POINTS)]
 lines+=paths(1)+['TB_MMIO_COMMAND_BEGIN original=0000 requested=0002 bus_master_enable=0','TB_MMIO_COMMAND_ACTIVE observed=0002']
 previous={p:0 for p in POINTS}
 for group,n in enumerate([0,64,16384,0],1):
  for i,p in enumerate(POINTS):
   b=previous[p];delta=n+100 if p!='DOCK_PCIE' else 0;a=b+delta;previous[p]=a
   bt=group*1000000000+i*10000;at=bt+(100000000 if not n else 1000000+n*1000)
   lines+=['TB_MMIO_SAMPLE group=%d reads=%d point=%s before=%d after=%d delta=%d dropped_before=0 dropped_after=0 dropped_delta=0 before_ns=%d after_ns=%d elapsed_ns=%d'%(group,n,p,b,a,delta,bt,at,at-bt)]
  lines+=['TB_MMIO_DATA group=%d reads=%d expected=b76000a1 checked=%d valid=1'%(group,n,n)]
 lines+=['TB_MMIO_COMMAND_RESTORED observed=0000 bus_master_enable=0']+paths(1)+['TB_MMIO_PROBE_END protocol_complete=1 positive_controls=2 idle_controls=2 points=4 source_reads=16448 command_restored=1','COUNTER_CONTROL_RC=0','COUNTER_MODULE_UNLOADED=1']+paths(0)+['TB_COUNTER_RESTORED original_module=1 four_paths=1 command_original=1','USB4_INSPECTION_GPU_MODULES absent']+cc+['USB4_COUNTER_RUN_END original_module_restored=1 data_disks_unmounted=1 gpu_program_executed=0','SCRIPT_RC=0']
 kernel='\n'.join('[ 1] CASKTB_COUNTER_PLAN route=%s port=%d hop=8 index=%d path_inactive=1 standard_activation=1'%x for x in [('0',8,0),('1',1,1),('1',3,0),('0',1,1)])
 return '\n'.join(lines),kernel
class Validation(unittest.TestCase):
 def test_complete_without_false_calibration(self):
  r,k=fixture();x=validate_log(r,CCFG,k);self.assertTrue(x['protocol_complete']);self.assertEqual(x['unresponsive_points'],['DOCK_PCIE']);self.assertFalse(x['all_counters_calibrated']);self.assertFalse(x['P2P_solution_claimed'])
 def test_negative_variants(self):
  r,k=fixture()
  mutations=[(r.replace('SCRIPT_RC=0','SCRIPT_RC=27'),k),(r.replace('observed=0000 bus_master_enable=0','observed=0002 bus_master_enable=0'),k),(r.replace('bus_master_enable=0','bus_master_enable=1'),k),(r.replace('expected=b76000a1','expected=ffffffff'),k),(r.replace('checked=16384','checked=16383'),k),(r.replace('index=1','index=0'),k),(r.replace('COUNTER_MODULE_UNLOADED=1',''),k),(r.replace('command_original=1','command_original=0'),k),(r.replace('delta=16484','delta=16483'),k),(r.replace('elapsed_ns=100000000','elapsed_ns=100000001'),k),(r.replace('dropped_delta=0','dropped_delta=1'),k),(r.replace('04008077','04008076'),k),(r,k.replace('path_inactive=1','path_inactive=0')),(r,k+'\nWATCHDOG_REBOOT'),(r,k+'\nNVRM: loaded'),(r,k+'\n'+k.splitlines()[0]),(r+'\nSCRIPT_RC=0',k),(r,''),(r.replace('TB_MMIO_COMMAND_ACTIVE observed=0002','TB_MMIO_COMMAND_ACTIVE observed=0000'),k)]
  for a,b in mutations:
   with self.subTest(a=a[-70:],b=b[-50:]):self.assertFalse(validate_log(a,CCFG,b)['protocol_complete'])
if __name__=='__main__':unittest.main()
