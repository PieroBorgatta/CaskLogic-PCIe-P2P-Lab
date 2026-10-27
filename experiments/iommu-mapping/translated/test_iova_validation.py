"""Synthetic protocol fixtures only. These are not hardware measurements."""
import unittest
from iova_log_validation import validate_log
CCFG={'0000:00:01.0':(0,0x04008077),'0000:00:07.0':(0,0x0e009077),'0000:00:07.2':(0,0x0e009077)}
def fixture(peer_success=False):
 raw='intel_iommu=on iommu.passthrough=0 iommu.strict=1\nIOVA_MMIO_PARAMETER=Y BUILTIN_TESTS_PARAMETER=1\nIOVA_DMAR_BEFORE_BEGIN\nIOVA_DMAR_BEFORE_END\nIOVA_BEGIN abi=1 peer_register_offset=0 peer_reads_only=1 ordinary_peer_access=0 host_staging_for_peer=0\n'
 for _ in range(3):
  for b,(_,v) in CCFG.items():raw+=('PEG_CCFG' if '01.0' in b else 'TCSS_CCFG')+' '+b[5:]+' %08x\n'%v
 kernel=''
 for _ in range(2):
  kernel+='CASKDMAR_BEGIN version=1 units=1 table_bytes=80 register_writes=0\nCASKDMAR_CAP base=fed91000 ver=00000050 cap=00d2008c40660462 ecap=0000000000f050da\n'
  for i in range(2):kernel+='CASKDMAR_SAMPLE index=%d gsts=c7000000 pmen=00000000 translation_enabled=1 interrupt_remapping_enabled=1 protected_region_enabled=0 protected_region_status=0\n'%i
  kernel+='CASKDMAR_END protocol_complete=1 register_writes=0\nCASKDMAR_UNLOADED register_writes=0\n'
 for index in range(2):
  prefix='CASKIOVA request=%d index=%d '%(101+index,index);expected_peer=0x197000a1 if index else 0xb76000a1
  iova=0xfe000000-index*4096;bar=0x50000000 if index else 0x60000000;host=0xf0000000-index*4096
  kernel+=prefix+'stage=mapping executor=%s peer=%s domain_type=3 iova=%x physical=%x translated=%x bytes=4096 direction=DMA_TO_DEVICE source_register=NV_PMC_BOOT_0 offset=0 expected=%08x\n'%('0000:06:00.0' if index else '0000:01:00.0','0000:01:00.0' if index else '0000:06:00.0',iova,bar,bar,expected_peer)
  kernel+=prefix+'stage=host_mapping iova=%x physical=120000000 translated=120000000 valid=1\n'%host
  for seq in range(6):
   peer=seq%3==1;expected=expected_peer if peer else 0x6975c23a^(index<<8);actual=expected if not peer or peer_success else 0xffffffff
   kernel+=prefix+'stage=result seq=%d mode=%d kind=%s source_iova=%x bytes=4 expected=%08x actual=%08x sentinel=%08x match=%d guard_changed=0 baseline_valid=1 checked_words=1024 class=c7b5 launch=4003186 p2p_channel=0 privileged=1\n'%(seq,1+seq//3,'peer_bar0' if peer else 'host_ram',iova if peer else host,expected,actual,~expected&0xffffffff,actual==expected)
  mask=3 if peer_success else 0
  kernel+=prefix+'stage=source_after cpu_after=%08x source_stable=1 host_source_changed=0\n'%expected_peer
  kernel+=prefix+'stage=return operation=1 status=0 flags=7 host_mask=2d peer_mask=%x completed_mask=3f pending=0 dma_unmapped=1 last_phase=reads\n'%mask
  raw+='IOVA_IOCTL index=%d request=%d rv=0 errno=0 status=0 flags=7 domain=3 host_mask=2d peer_mask=%x completed_mask=3f iova=%x physical=%x inputs_unchanged=1\n'%(index,101+index,mask,iova,bar)
 raw+='IOVA_END protocol_complete=1 p2p_solution_claimed=0\nNATIVE_TEST_RC=0\nIOVA_DMAR_AFTER_BEGIN\nIOVA_DMAR_AFTER_END\nIOVA_DATA_DISKS_UNMOUNTED\nrootfs / rootfs rw 0 0\nproc /proc proc rw 0 0\n/dev/nvme2n1p4 /mnt/esp vfat rw 0 0\nPROBE_COMPLETED\nSCRIPT_RC=0\n'
 return raw,kernel
class Validation(unittest.TestCase):
 def test_negative_hardware_result_is_not_incomplete(self):
  r,k=fixture();x=validate_log(r,CCFG,k);self.assertTrue(x['protocol_complete']);self.assertEqual(x['peer_reads_passed'],0);self.assertFalse(x['P2P_solution_claimed'])
 def test_success_is_still_not_general_p2p(self):
  r,k=fixture(True);x=validate_log(r,CCFG,k);self.assertTrue(x['protocol_complete']);self.assertEqual(x['peer_reads_passed'],4);self.assertFalse(x['P2P_solution_claimed'])
 def test_rejections(self):
  r,k=fixture()
  mutations=[(r.replace('SCRIPT_RC=0','SCRIPT_RC=20'),k),(r.replace('intel_iommu=on','intel_iommu=off'),k),(r.replace('NATIVE_TEST_RC=0',''),k),(r.replace('IOVA_END protocol_complete=1','IOVA_END protocol_complete=0'),k),(r.replace('inputs_unchanged=1','inputs_unchanged=0'),k),(r.replace('host_mask=2d','host_mask=0'),k),(r+'WATCHDOG_REBOOT\n',k),(r+'disk /mnt/llm ext4 rw 0 0\n',k),
   (r,k.replace('translation_enabled=1','translation_enabled=0')),(r,k.replace('gsts=c7000000','gsts=47000000')),(r,k.replace('pmen=00000000','pmen=80000001')),(r,k.replace('domain_type=3','domain_type=4')),(r,k.replace('translated=60000000','translated=60001000')),(r,k.replace('source_register=NV_PMC_BOOT_0','source_register=UNKNOWN')),(r,k.replace('offset=0','offset=4')),(r,k.replace('direction=DMA_TO_DEVICE','direction=DMA_FROM_DEVICE')),(r,k.replace('guard_changed=0','guard_changed=1')),(r,k.replace('baseline_valid=1','baseline_valid=0')),(r,k.replace('kind=host_ram','kind=peer_bar0')),(r,k.replace('seq=5','seq=4')),(r,k.replace('dma_unmapped=1','dma_unmapped=0')),(r,k.replace('pending=0','pending=1')),(r,k.replace('host_source_changed=0','host_source_changed=1')),(r,k.replace('source_stable=1','source_stable=0')),(r,k+'NVRM: Xid 79\n'),(r,k+'DMAR: fault event\n'),(r,k.replace('p2p_channel=0','p2p_channel=1')),(r,k.replace('class=c7b5','class=c6b5')),(r,k.replace('actual=6975c23a','actual=ffffffff'))]
  mutations += [(r.replace('rootfs / rootfs','/dev/sda / ext4'),k), (r.replace('proc /proc proc','disk /proc ext4'),k)]
  for a,b in mutations:
   with self.subTest(a=a[-60:],b=b[-60:]):self.assertFalse(validate_log(a,CCFG,b)['protocol_complete'])
if __name__=='__main__':unittest.main()
