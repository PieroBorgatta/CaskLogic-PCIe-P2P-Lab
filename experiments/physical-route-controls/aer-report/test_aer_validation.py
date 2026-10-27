import unittest
import test_bar0_validation
import aer_log_validation as v


def fixture():
    raw,ccfg,kernel = test_bar0_validation.fixture()
    head = []; tail = []
    oldctl = [0x2f,0,0x2910,0x2910,0x2930,0x2910]
    def record(stage,n):
        bdf,identity,cap,aer,kind = v.DEVICES[n]
        active = stage in ['enabled','pre_restore']; old = oldctl[n]; mask = 0x10000 if n == 0 else 0
        r = dict(phase=stage,bdf=bdf,id=format(identity,'08x'),cap=format(cap,'03x'),aer=format(aer,'03x'),type=kind,
                 old_devctl=format(old,'04x'),devctl=format(old|0xa if active else old,'04x'),old_uem=format(mask,'08x'),
                 uem=format(0 if active else mask,'08x'),ues='00000000',ces='00000000',capctl='00000000',
                 header0='00000000',header1='00000000',header2='00000000',header3='00000000',status_clears=0,interrupt_enables=0)
        if kind == 4: r.update(rootctl='0008',rootcmd='00000000',rootsta='00000000',rootsource='00000000')
        return 'CASKAER '+' '.join(k+'='+str(x) for k,x in r.items())
    for stage in ['saved','enabled']:
        head.extend(record(stage,n) for n in range(6))
    head.append('CASKAER_BEGIN devices=6 devctl_mask=000a peg_unmask=00010000 status_clears=0 interrupt_enables=0')
    for n in range(6): tail.extend([record('pre_restore',n),record('restored',n)])
    tail.append('CASKAER_END restored=1 devices=6 status_clears=0 interrupt_enables=0')
    output = []
    for line in raw.splitlines():
        if line.startswith('PHYS_CASE id=1 '): output.extend(head)
        if line.startswith('PHYS_DATA_RESULT '):
            case = v.fields(line)['id']
            for side in ['before','after']:
                for n,(bdf,*_) in enumerate(v.DEVICES):
                    output.append('PCIE_SNAPSHOT phase=physical_pull_case_'+case+'_'+side+' bdf='+bdf+
                                  ' CONFIG_BYTES=4096 READ_ERRNO=0 DEVCTL='+format(oldctl[n]|0xa,'04x')+
                                  ' UEM=00000000 COMMAND=0407 ROOTCMD=00000000 DPC_CTL=0000')
        if line.startswith('PHYS_PROGRAM_END '): output.extend(tail)
        output.append(line)
    return '\n'.join(output)+'\n',ccfg,kernel


class AerValidation(unittest.TestCase):
    def setUp(self): self.raw,self.ccfg,self.kernel = fixture()
    def reject(self,before,after):
        self.assertIn(before,self.raw)
        r = v.validate_log(self.raw.replace(before,after,1),self.ccfg,self.kernel)
        self.assertFalse(r['protocol_complete'],r)
    def test_complete(self):
        r = v.validate_log(self.raw,self.ccfg,self.kernel)
        self.assertTrue(r['protocol_complete'],r); self.assertTrue(r['aer_controls_restored'])
        self.assertFalse(r['P2P_solution_claimed'])
    def test_restore(self): self.reject('CASKAER_END restored=1','CASKAER_END restored=0')
    def test_interrupt(self): self.reject('rootcmd=00000000','rootcmd=00000001')
    def test_system_error(self): self.reject('rootctl=0008','rootctl=0009')
    def test_wrong_mask(self): self.reject('devctl_mask=000a','devctl_mask=000f')
    def test_rw1c(self): self.reject('status_clears=0','status_clears=1')
    def test_wrong_cap(self): self.reject('cap=040','cap=044')
    def test_unrelated_devctl_bit(self): self.reject('devctl=002f','devctl=003f')
    def test_disabled_during_transfer(self): self.reject('DEVCTL=000a','DEVCTL=0000')
    def test_interrupt_during_transfer(self): self.reject('ROOTCMD=00000000','ROOTCMD=00000001')
    def test_serr_during_transfer(self): self.reject('COMMAND=0407','COMMAND=0507')
    def test_missing_snapshot(self): self.reject('phase=physical_pull_case_1_before','phase=other')
    def test_duplicate_snapshot(self):
        line = next(x for x in self.raw.splitlines() if x.startswith('PCIE_SNAPSHOT '))
        self.assertFalse(v.validate_log(self.raw+line+'\n',self.ccfg,self.kernel)['protocol_complete'])


if __name__ == '__main__': unittest.main()
