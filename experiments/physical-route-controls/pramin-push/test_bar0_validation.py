import unittest
import host_fixture
import bar0_log_validation as v


def fixture(passes=False):
    raw,ccfg,kernel=host_fixture.fixture()
    rows=[]
    def add(stage,request,index,mode=None,**kw):
        r=dict(request=request,stage=stage,executor=v.host.base.BDFS[index],index=index)
        if mode is not None:r['mode']=mode
        r.update(kw)
        rows.append('CASKBAR0 '+' '.join(k+'='+str(x) for k,x in r.items()))
    for index,case in [(1,3),(0,9)]:
        request=1000000+case;remote=v.host.base.BDFS[1-index]
        expected=0x190000a1+index*0x10000;sentinel=expected^0xffffffff
        address=0xf6000000+(1-index)*0x2000000
        add('cpu_reference',request,index,remote=remote,bar=0,offset=0,base=format(address,'x'),
            length='1000000',resource_flags='40200',expected=format(expected,'08x'),
            register='NV_PMC_BOOT_0',read_only=1)
        for mode in (1,2):
            for phase in ['before','after_raw','after_readback']:
                add('pci',request,index,mode,phase=phase,pci_status='0010' if passes or phase=='before' else '2010',read_rc=0)
            add('baseline',request,index,mode,checked_words=1024,expected=format(sentinel,'08x'),actual=format(sentinel,'08x'),mismatches=0,valid=1)
            add('methods',request,index,mode,remote=remote,source_phys=format(address,'x'),destination_phys='a000000',
                bytes=4,launch='4003186',p2p=1,privileged=1,register_offset=0,read_only=1,**{'class':'c7b5'})
            add('result',request,index,mode,remote=remote,bytes=4,checked_words=1024,expected=format(expected,'08x'),
                actual=format(expected if passes else 0xffffffff,'08x'),sentinel=format(sentinel,'08x'),match=int(passes),
                guard_changed=0,cpu_after=format(expected,'08x'),source_stable=1)
        add('return',request,index,status=0,pending=0)
    return raw,ccfg,kernel+'\n'.join(rows)+'\n'


class Bar0Validation(unittest.TestCase):
    def setUp(self):self.raw,self.ccfg,self.kernel=fixture()
    def rejected(self,before,after):
        self.assertIn(before,self.kernel)
        r=v.validate_log(self.raw,self.ccfg,self.kernel.replace(before,after,1))
        self.assertFalse(r['protocol_complete'],r)
    def test_complete_negative_reads(self):
        r=v.validate_log(self.raw,self.ccfg,self.kernel)
        self.assertTrue(r['protocol_complete'],r);self.assertEqual(r['bar0_read_failures'],4)
        self.assertTrue(r['bar0_values_known']);self.assertFalse(r['P2P_solution_claimed'])
    def test_complete_positive_reads(self):
        a,b,c=fixture(True);r=v.validate_log(a,b,c)
        self.assertTrue(r['protocol_complete'],r);self.assertEqual(r['bar0_read_passes'],4)
    def test_guard(self):self.rejected('guard_changed=0','guard_changed=1')
    def test_readonly(self):self.rejected('register_offset=0 read_only=1','register_offset=0 read_only=0')
    def test_register_offset(self):self.rejected('register_offset=0','register_offset=4')
    def test_source_address(self):self.rejected('source_phys=f6000000','source_phys=f6000004')
    def test_unstable_source(self):self.rejected('source_stable=1','source_stable=0')
    def test_pending(self):
        line=next(x for x in self.kernel.splitlines() if x.startswith('CASKBAR0 ') and 'stage=return' in x)
        self.rejected(line,line.replace('pending=0','pending=1'))
    def test_contradictory_match(self):self.rejected('match=0 guard_changed=0','match=1 guard_changed=0')
    def test_missing_bar0_evidence(self):
        k='\n'.join(x for x in self.kernel.splitlines() if not x.startswith('CASKBAR0 '))
        self.assertFalse(v.validate_log(self.raw,self.ccfg,k)['protocol_complete'])
    def test_duplicate(self):
        line=next(x for x in self.kernel.splitlines() if x.startswith('CASKBAR0 ') and 'stage=methods' in x)
        self.assertFalse(v.validate_log(self.raw,self.ccfg,self.kernel+line+'\n')['protocol_complete'])
    def test_unexpected_value_flagged(self):
        line=next(x for x in self.kernel.splitlines() if x.startswith('CASKBAR0 ') and 'stage=result' in x)
        k=self.kernel.replace(line,line.replace('actual=ffffffff','actual=12345678'),1)
        r=v.validate_log(self.raw,self.ccfg,k)
        self.assertTrue(r['protocol_complete'],r);self.assertFalse(r['bar0_values_known'])


if __name__=='__main__':unittest.main()
