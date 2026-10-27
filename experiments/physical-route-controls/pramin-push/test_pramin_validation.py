import unittest
import test_bar0_validation
import pramin_log_validation as v


def fixture(success=None):
    raw,ccfg,kernel = test_bar0_validation.fixture()
    rows = []
    def add(stage,request,index,mode=None,**kw):
        r = dict(request=request,stage=stage,executor=v.base.BDFS[index],index=index)
        if mode is not None: r['mode'] = mode
        r.update(kw)
        rows.append('CASKPRAMIN '+' '.join(k+'='+str(x) for k,x in r.items()))
    for index,case in [(1,3),(0,9)]:
        request = 1000000+case; remote = v.base.BDFS[1-index]
        target = 0x1abc03000; source = 0x25000000; b = 0x60000000
        offset = 0x700000+(target&0xffff); dest = b+offset
        old = 0x2ffff; new = target>>16
        add('reference',request,index,remote=remote,bar=0,base=format(b,'x'),length='1000000',resource_flags='40200',
            source_vid=format(source,'x'),target_vid=format(target,'x'),alias_offset=format(offset,'x'),alias_phys=format(dest,'x'),
            bytes=4,window_register='1700',private_target=1)
        for mode in [1,2]:
            expected = v.pattern(index,mode,True); sentinel = v.pattern(index,mode,False)
            passes = bool(index) if success is None else success
            actual = expected if passes else sentinel
            add('baseline',request,index,mode,checked_words=1024,source_mismatches=0,target_mismatches=0,
                expected=format(expected,'08x'),sentinel=format(sentinel,'08x'),valid=1)
            add('window',request,index,mode,old=format(old,'08x'),programmed=format(new,'08x'),observed=format(new,'08x'),
                alias_checked_words=16,alias_mismatches=0)
            add('methods',request,index,mode,remote=remote,source_phys=format(source,'x'),destination_phys=format(dest,'x'),
                source_mode=0,destination_mode=mode,bytes=4,launch='4003186',p2p=1,privileged=1,host_relay=0,**{'class':'c7b5'})
            add('restored',request,index,mode,old=format(old,'08x'),observed_during=format(new,'08x'),restored=format(old,'08x'),
                alias_actual=format(actual,'08x'),alias_guard_changed=0)
            add('result',request,index,mode,remote=remote,bytes=4,checked_words=1024,expected=format(expected,'08x'),sentinel=format(sentinel,'08x'),
                actual=format(actual,'08x'),alias_actual=format(actual,'08x'),match=int(passes),alias_match=int(passes),
                guard_changed=0,alias_guard_changed=0,source_changed=0)
            for phase in ['before','after_raw','after_readback']:
                add('pci',request,index,mode,phase=phase,pci_status='2010',read_rc=0)
        add('return',request,index,status=0,pending=0)
    return raw,ccfg,kernel+'\n'.join(rows)+'\n'


class PraminValidation(unittest.TestCase):
    def setUp(self): self.raw,self.ccfg,self.kernel = fixture()
    def mutate(self,stage,before,after):
        line = next(x for x in self.kernel.splitlines() if x.startswith('CASKPRAMIN ') and 'stage='+stage+' ' in x)
        self.assertIn(before,line)
        r = v.validate_log(self.raw,self.ccfg,self.kernel.replace(line,line.replace(before,after,1),1))
        self.assertFalse(r['protocol_complete'],r)
    def test_mixed(self):
        r = v.validate_log(self.raw,self.ccfg,self.kernel)
        self.assertTrue(r['protocol_complete'],r); self.assertEqual(r['pramin_passes'],2)
        self.assertFalse(r['production_transport_proven']); self.assertFalse(r['P2P_solution_claimed'])
    def test_positive(self):
        a,b,c = fixture(True); r = v.validate_log(a,b,c)
        self.assertTrue(r['protocol_complete'],r); self.assertEqual(r['pramin_passes'],4)
    def test_negative(self):
        a,b,c = fixture(False); r = v.validate_log(a,b,c)
        self.assertTrue(r['protocol_complete'],r); self.assertEqual(r['pramin_failures'],4)
    def test_alias_wrong(self): self.mutate('reference','alias_phys=60703000','alias_phys=60703004')
    def test_unaligned_target(self): self.mutate('reference','target_vid=1abc03000','target_vid=1abc03004')
    def test_prefetch_bar(self): self.mutate('reference','resource_flags=40200','resource_flags=42200')
    def test_window_mismatch(self): self.mutate('window','alias_mismatches=0','alias_mismatches=1')
    def test_window_unrestored(self): self.mutate('restored','restored=0002ffff','restored=0002fffe')
    def test_window_race(self): self.mutate('restored','observed_during=0001abc0','observed_during=0001abc1')
    def test_host_relay(self): self.mutate('methods','host_relay=0','host_relay=1')
    def test_wrong_source_mode(self): self.mutate('methods','source_mode=0','source_mode=2')
    def test_guard(self): self.mutate('result','guard_changed=0','guard_changed=1')
    def test_source(self): self.mutate('result','source_changed=0','source_changed=1')
    def test_uncertain(self): self.mutate('return','pending=0','pending=1')
    def test_duplicate(self):
        line = next(x for x in self.kernel.splitlines() if x.startswith('CASKPRAMIN ') and 'stage=methods' in x)
        self.assertFalse(v.validate_log(self.raw,self.ccfg,self.kernel+line+'\n')['protocol_complete'])
    def test_missing(self):
        self.assertFalse(v.validate_log(self.raw,self.ccfg,'\n'.join(x for x in self.kernel.splitlines() if 'CASKPRAMIN ' not in x))['protocol_complete'])


if __name__ == '__main__': unittest.main()
