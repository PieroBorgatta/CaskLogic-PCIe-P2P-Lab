"""Fixture sintetiche offline: non rappresentano risultati hardware."""
import unittest
from analyze_p2ptrc import analyze

RESULT = '''CaskLogicPeer phase=mapping_begin monotonic=1.000000000 s=0 d=1
CaskLogicPeer phase=owner_init_ready monotonic=1.100000000 s=0 d=1
OWNER_CHECK stage=initialized device=0 observed=00003039 expected=00003039 valid=1
REMOTE_READ s=0 d=1 bytes=4 valid=0
'''
KERNEL = '''[ 1.005] CaskLogicPeer phase=mapping_begin monotonic=1.000000000 s=0 d=1
[ 1.010] P2PTRC DMA_MAP src=0000:06:00.0 dst=0000:01:00.0 input=4600002000 output=4600002000 pages=10 os_page=4096 bar_index=1 resource_start=4600000000 resource_end=460fffffff bus_base=4600000000 iommu_resource=1 status=0
[ 1.011] P2PTRC WINDOW_CREATE id=1 mem=aa subdev=bb src=1 dst=0 src_gpu_id=0 dst_gpu_id=1 desc=123 iovas=0 size=10000 bar1=4600000000 bar1_size=10000000 bar1_off=2000 window_phys=4600002000 dma=4600002000 ranges=1
[ 1.012] P2PTRC RM_REQUEST client=cc mem=aa src=1 dst=0 desc=123 offset=0 size=10000 dynamic=1 dma=4600002000
[ 1.013] P2PTRC RM_PTE client=cc src=1 dst=0 desc=123 offset=0 page=1000 pte_count=1 entry=8 fmt=2 aperture=3 valid=1 readonly=0 atomic=0 volatile=1 dynamic=1 dma_base=4600002000 phys_input=4600002000 decoded=4600002000 addr_shift=12 raw0=000000046000020f raw1=0000000000000000
[ 1.014] P2PTRC RM_RETURN client=cc mem=aa src=1 status=0
[ 1.015] P2PTRC UVM_PTE gpu=GPU 1 [UUID GPU-fake] mem=aa gpu_va=1234500000 map_offset=0 map_size=10000 page=1000 entry=8 count=1 table_ap=VID table_pa=888000 last=1 raw0=000000046000020f raw1=0000000000000000
[ 1.016] P2PTRC UVM_SUBMIT gpu=GPU 1 [UUID GPU-fake] mem=aa gpu_va=1234500000 status=0
[ 1.017] P2PTRC UVM_MAP_COMPLETE gpu_va=1234500000 length=10000 status=0
'''


class OfflineChainTests(unittest.TestCase):
    def test_consistent_mapping_does_not_claim_transport_success(self):
        value = analyze(KERNEL, RESULT)
        self.assertEqual(value['status'], 'observed_software_mapping_chain_consistent')
        self.assertEqual(value['data_operations'][0]['valid'], '0')
        self.assertEqual(value['chains'][0]['probe_allocation_role'], 'src: actual peer-read/peer-write target')
        self.assertEqual(value['chains'][0]['owner_bdf'], '0000:01:00.0')
        self.assertEqual(value['chains'][0]['gpu_name'], 'GPU 1 [UUID GPU-fake]')

    def test_bad_pte_detected_instead_of_excluded_from_matching(self):
        lines = KERNEL.splitlines()
        lines = [x.replace('000000046000020f', '000000046000021f') if 'UVM_PTE' in x else x for x in lines]
        value = analyze('\n'.join(lines), RESULT)
        self.assertEqual(value['status'], 'mapping_chain_mismatch')
        self.assertTrue(any(c['check'] == 'UVM_equals_RM_raw0' and c['ok'] is False for c in value['checks']))

    def test_missing_completion_is_not_success(self):
        value = analyze('\n'.join(x for x in KERNEL.splitlines() if 'UVM_MAP_COMPLETE' not in x), RESULT)
        self.assertEqual(value['status'], 'trace_incomplete')

    def test_decode_truncation_detected(self):
        value = analyze(KERNEL.replace('decoded=4600002000', 'decoded=600002000'), RESULT)
        self.assertEqual(value['status'], 'mapping_chain_mismatch')

    def test_no_driver_trace_is_incomplete(self):
        self.assertEqual(analyze('', RESULT)['status'], 'trace_incomplete')

    def test_prefixed_probe_pointer_is_direct_evidence(self):
        value = analyze(KERNEL, RESULT + 'PROBE_PTR s=0 d=1 src=0x1234500000 dst=0x9990000000 bytes=4\n')
        self.assertEqual(value['chains'][0]['probe_role_source'], 'direct PROBE_PTR address within UVM mapping')
        self.assertEqual(value['chains'][0]['direct_probe_pointer_matches'][0]['address'], '0x1234500000')

    def test_equal_words_do_not_hide_page_misalignment(self):
        value = analyze(KERNEL.replace('page=1000 ', 'page=200000 '), RESULT)
        self.assertEqual(value['chain_equality_status'], 'observed_software_mapping_chain_consistent')
        self.assertEqual(value['status'], 'PTE_page_alignment_mismatch_requires_resolution')


if __name__ == '__main__':
    unittest.main()
