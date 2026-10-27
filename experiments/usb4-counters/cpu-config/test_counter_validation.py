import unittest
from counter_log_validation import validate_log,POINTS

CCFG={'0000:00:01.0':(0,0x04008077),'0000:00:07.0':(0,0x0e009077),'0000:00:07.2':(0,0x0e009077)}
def fixture():
    lines=['USB4_COUNTER_RUN_BEGIN version=1 gpu_program_executed=0',
           'module_blacklist=nouveau,nvidia,nvidia_uvm,nvidia_drm,nvidia_modeset',
           'USB4_INSPECTION_GPU_MODULES absent']
    cc=['PEG_CCFG 00:01.0 04008077','TCSS_CCFG 00:07.0 0e009077','TCSS_CCFG 00:07.2 0e009077']
    lines+=cc+['USB4_COUNTER_DATA_DISKS unmounted','COUNTER_MODULE_LOAD_RC=0',
       'TB_COUNTER_PROBE_BEGIN version=1 gpu_program_executed=0 userspace_register_writes=0']
    paths=lambda enabled:['TB_COUNTER_PATH point=%s enabled=%d index=%d valid=1'%(p,enabled,[0,1,1,0][i]) for i,p in enumerate(POINTS)]
    lines+=paths(1)
    for n in [0,64,1024]:
        for p in POINTS:
            lines+=['TB_COUNTER_SAMPLE stage=%s reads=%d point=%s before=0 after=%d delta=%d dropped_before=0 dropped_after=0 dropped_delta=0'%('CPU_CONFIG_POSITIVE' if n else 'IDLE',n,p,n,n)]
    lines+=paths(1)+['TB_COUNTER_PROBE_END protocol_complete=1 positive_controls=2 idle_controls=1 points=4',
       'COUNTER_CONTROL_RC=0','COUNTER_MODULE_UNLOADED=1']+paths(0)+[
       'TB_COUNTER_RESTORED original_module=1 four_paths=1','USB4_INSPECTION_GPU_MODULES absent']+cc+[
       'USB4_COUNTER_RUN_END original_module_restored=1 data_disks_unmounted=1 gpu_program_executed=0','SCRIPT_RC=0']
    kernel='\n'.join('[ 1.0] CASKTB_COUNTER_PLAN route=%s port=%d hop=8 index=%d path_inactive=1 standard_activation=1'%x for x in [('0',8,0),('1',1,1),('1',3,0),('0',1,1)])
    return '\n'.join(lines),kernel
class Validation(unittest.TestCase):
    def test_complete(self):
        r,k=fixture();self.assertTrue(validate_log(r,CCFG,k)['protocol_complete'])
    def test_reject_mutations(self):
        r,k=fixture()
        mutations=[(r.replace('SCRIPT_RC=0','SCRIPT_RC=27'),k),
          (r.replace('COUNTER_MODULE_UNLOADED=1',''),k),
          (r.replace('TB_COUNTER_RESTORED original_module=1 four_paths=1',''),k),
          (r.replace('enabled=0','enabled=1'),k),
          (r.replace('index=1','index=0'),k),
          (r.replace('after=64 delta=64','after=0 delta=0'),k),
          (r.replace('delta=1024','delta=1023'),k),
          (r.replace('dropped_after=0','dropped_after=1'),k),
          (r.replace('after=1024 delta=1024','after=18446744073709551615 delta=18446744073709551615'),k),
          (r.replace('before=0 after=64','before=65 after=64'),k),
          (r.replace('04008077','04008076'),k),
          (r.replace('TB_COUNTER_SAMPLE stage=IDLE reads=0 point=HOST_PCIE','TB_COUNTER_SAMPLE stage=IDLE reads=0 point=DOCK_PCIE'),k),
          (r,k.replace('path_inactive=1','path_inactive=0')),
          (r,k+'\nNVRM: driver loaded'),(r,k+'\nWATCHDOG_REBOOT'),(r,''),
          (r+'\nSCRIPT_RC=0',k),(r,k+'\n'+k.splitlines()[0])]
        for a,b in mutations:
            with self.subTest(a=a[-80:],b=b[-80:]):self.assertFalse(validate_log(a,CCFG,b)['protocol_complete'])
if __name__=='__main__':unittest.main()
