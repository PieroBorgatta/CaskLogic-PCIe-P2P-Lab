"""Parser fixtures only, not register-read evidence."""
import unittest
from pathlib import Path
from dmar_log_validation import validate_log
R=Path(__file__).resolve().parent
CCFG={'0000:00:01.0':(0,0x04008077),'0000:00:07.0':(0,0x0e009077),'0000:00:07.2':(0,0x0e009077)}
def fixture(active=False):
 d=R/'results'
 r=(d/'result-markers.log').read_text()
 r='\n'.join(l for l in r.splitlines() if not l.startswith('DMAR_READ_'))+'\n'
 r=r.replace('USB4_INSPECTION_DATA_DISKS unmounted','USB4_INSPECTION_DATA_DISKS unmounted\nDMAR_READ_BEGIN register_writes=0\nDMAR_READ_MODULE_LOADED=1\nDMAR_READ_MODULE_UNLOADED=1\nDMAR_READ_END register_writes=0')
 k='SYNTHETIC_PARSER_FIXTURE\n'+'\nCASKDMAR_BEGIN version=1 units=1 table_bytes=80 table_flags=05 register_writes=0\nCASKDMAR_CAP base=fed91000 ver=00000050 cap=00d2008c40660462 ecap=0000000000f050da\n'
 for i in range(2):k+='CASKDMAR_SAMPLE index=%d gsts=%s pmen=%s translation_enabled=%d interrupt_remapping_enabled=1 protected_region_enabled=%d protected_region_status=%d\n'%(i,'86000000' if active else '06000000','80000001' if active else '00000000',active,active,active)
 k+='CASKDMAR_END protocol_complete=1 register_writes=0\nCASKDMAR_UNLOADED register_writes=0\n';return r,k
class Validation(unittest.TestCase):
 def test_inactive(self):
  r,k=fixture();x=validate_log(r,CCFG,k);self.assertTrue(x['protocol_complete']);self.assertTrue(x['translation_inactive_in_all_samples']);self.assertTrue(x['protected_regions_inactive_in_all_samples'])
 def test_active_is_not_mislabelled(self):
  r,k=fixture(True);x=validate_log(r,CCFG,k);self.assertTrue(x['protocol_complete']);self.assertFalse(x['translation_inactive_in_all_samples']);self.assertFalse(x['protected_regions_inactive_in_all_samples'])
 def test_negative_variants(self):
  r,k=fixture();mutations=[(r.replace('DMAR_READ_MODULE_UNLOADED=1',''),k),(r.replace('SCRIPT_RC=0','SCRIPT_RC=27'),k),(r,k.replace('base=fed91000','base=fed90000')),(r,k.replace('ver=00000050','ver=ffffffff')),(r,k.replace('gsts=06000000','gsts=86000000')),(r,k.replace('pmen=00000000','pmen=80000001')),(r,k.replace('CASKDMAR_SAMPLE index=1','CASKDMAR_SAMPLE index=0')),(r,k.replace('register_writes=0','register_writes=1')),(r,k.replace('CASKDMAR_END ','MISSING_END ')),(r,k+'CASKDMAR_UNLOADED register_writes=0\n'),(r,k+'WATCHDOG_REBOOT\n'),(r,'')]
  for a,b in mutations:
   with self.subTest(a=a[-50:],b=b[-50:]):self.assertFalse(validate_log(a,CCFG,b)['protocol_complete'])
if __name__=='__main__':unittest.main()
