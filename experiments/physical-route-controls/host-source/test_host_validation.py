import unittest
import base_fixture
import host_log_validation as v


def fixture():
    raw, ccfg, kernel = base_fixture.fixture()
    rows = []
    def add(stage, request, index, mode=None, **kw):
        r = dict(request=request, stage=stage, executor=v.base.BDFS[index], index=index)
        if mode is not None:
            r['mode'] = mode
        r.update(kw)
        rows.append('CASKHOST '+' '.join(k+'='+str(x) for k,x in r.items()))
    for index, case in [(1,3),(0,9)]:
        req = 1000000+case
        for mode in (1,2):
            expected = (0x6975c23a ^ ((index+1)*0x11a33799) ^ (mode*0x9e3779b9)) & 0xffffffff
            sentinel = expected ^ 0xffffffff
            add('pci',req,index,mode,phase='before',pci_status='0010',read_rc=0)
            add('baseline',req,index,mode,checked_words=1024,expected=format(sentinel,'08x'),
                actual=format(sentinel,'08x'),mismatches=0,valid=1)
            add('pci',req,index,mode,phase='after_baseline',pci_status='0010',read_rc=0)
            add('methods',req,index,mode,source_phys='12345000',destination_phys='a000000',
                bytes=4,launch='4003186',p2p=1,privileged=1,no_virtual_fallback=1,**{'class':'c7b5'})
            add('pci',req,index,mode,phase='after_raw',pci_status='0010',read_rc=0)
            add('result',req,index,mode,bytes=4,checked_words=1024,expected=format(expected,'08x'),
                actual=format(expected,'08x'),sentinel=format(sentinel,'08x'),mismatches=0,
                source_changed=0,valid=1)
            add('pci',req,index,mode,phase='after_readback',pci_status='0010',read_rc=0)
        add('return',req,index,status=0,pending=0,last_phase='readback_wait')
    return raw, ccfg, kernel+'\n'.join(rows)+'\n'


class HostValidation(unittest.TestCase):
    def setUp(self):
        self.raw, self.ccfg, self.kernel = fixture()

    def check_rejected(self, before, after):
        self.assertIn(before,self.kernel)
        k = self.kernel.replace(before,after,1)
        r = v.validate_log(self.raw,self.ccfg,k)
        self.assertFalse(r['protocol_complete'],r)
        self.assertTrue(r['core_peer_protocol_complete'])
        self.assertFalse(r['host_controls_qualified'])

    def test_complete_with_peer_failures(self):
        r=v.validate_log(self.raw,self.ccfg,self.kernel)
        self.assertTrue(r['protocol_complete'],r)
        self.assertEqual(r['failures'],9)
        self.assertEqual(r['host_control_comparisons'],4)
        self.assertEqual(r['total_comparisons_including_host_controls'],16)
        self.assertFalse(r['P2P_solution_claimed'])

    def test_missing_host_evidence(self):
        k='\n'.join(x for x in self.kernel.splitlines() if 'CASKHOST ' not in x)
        self.assertFalse(v.validate_log(self.raw,self.ccfg,k)['protocol_complete'])

    def test_corrupt_actual(self):
        line=next(x for x in self.kernel.splitlines() if 'CASKHOST ' in x and 'stage=result' in x)
        actual=next(x for x in line.split() if x.startswith('actual='))
        self.check_rejected(line,line.replace(actual,'actual=ffffffff'))

    def test_changed_source(self):self.check_rejected('source_changed=0','source_changed=1')
    def test_baseline_corruption(self):self.check_rejected('mismatches=0 valid=1','mismatches=1 valid=0')
    def test_word_count(self):self.check_rejected('checked_words=1024','checked_words=1')
    def test_launch(self):self.check_rejected('launch=4003186 p2p=1','launch=4003187 p2p=1')
    def test_privilege(self):self.check_rejected('privileged=1 no_virtual_fallback=1','privileged=0 no_virtual_fallback=1')
    def test_unaligned_physical(self):self.check_rejected('source_phys=12345000','source_phys=12345001')
    def test_wrong_gpu(self):self.check_rejected('stage=result executor=0000:06:00.0','stage=result executor=0000:01:00.0')
    def test_pending(self):self.check_rejected('status=0 pending=0','status=0 pending=1')
    def test_pci_abort(self):self.check_rejected('pci_status=0010','pci_status=2010')
    def test_pci_read_failure(self):self.check_rejected('read_rc=0','read_rc=1')

    def test_duplicate_result(self):
        line=next(x for x in self.kernel.splitlines() if 'CASKHOST ' in x and 'stage=result' in x)
        self.assertFalse(v.validate_log(self.raw,self.ccfg,self.kernel+line+'\n')['protocol_complete'])

    def test_primary_protocol_not_overridden(self):
        r=v.validate_log('',self.ccfg,self.kernel)
        self.assertFalse(r['protocol_complete'])
        self.assertFalse(r['core_peer_protocol_complete'])


if __name__ == '__main__':
    unittest.main()
