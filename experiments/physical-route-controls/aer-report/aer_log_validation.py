"""Offline qualifier for transient standard PCIe error-reporting controls."""
from pathlib import Path
import importlib.util
import hashlib

p = Path(__file__).with_name('bar0_log_validation.py')
if hashlib.sha256(p.read_bytes()).hexdigest() != 'c8c5f97b4b189d3b3530020e644eeae6b3ac22d4a2edfb4ccad40d32acffceee':
    raise RuntimeError('BAR0 validation changed')
s = importlib.util.spec_from_file_location('bar0_aer_base',str(p))
bar0 = importlib.util.module_from_spec(s); s.loader.exec_module(bar0)
require = bar0.require
fields = bar0.host.base.fields
DEVICES = [
    ('0000:00:01.0',0x460d8086,0x40,0x100,4),
    ('0000:00:07.0',0x466e8086,0x40,0x100,4),
    ('0000:04:00.0',0x24611b21,0x80,0x100,5),
    ('0000:05:00.0',0x24611b21,0x80,0x100,6),
    ('0000:01:00.0',0x28b010de,0x78,0x420,1),
    ('0000:06:00.0',0x257110de,0x78,0x420,1)]


def qualify_aer(raw):
    lines = raw.splitlines()
    begin = [i for i,x in enumerate(lines) if x.startswith('CASKAER_BEGIN ')]
    end = [i for i,x in enumerate(lines) if x.startswith('CASKAER_END ')]
    require(len(begin) == len(end) == 1,'AER begin/end missing/duplicate')
    require(lines[begin[0]] == 'CASKAER_BEGIN devices=6 devctl_mask=000a peg_unmask=00010000 status_clears=0 interrupt_enables=0','AER enable scope differs')
    require(lines[end[0]] == 'CASKAER_END restored=1 devices=6 status_clears=0 interrupt_enables=0','AER restoration failed')
    first = next(i for i,x in enumerate(lines) if x.startswith('PHYS_CASE id=1 '))
    last = next(i for i,x in enumerate(lines) if x.startswith('PHYS_DATA_RESULT id=12 '))
    require(begin[0] < first < last < end[0],'AER reporting lifetime differs')
    records = [(i,fields(x[len('CASKAER '):])) for i,x in enumerate(lines) if x.startswith('CASKAER ')]
    require(len(records) == 24,'AER record count differs')
    require([r['phase'] for i,r in records] == ['saved']*6+['enabled']*6+sum((['pre_restore','restored'] for _ in range(6)),[]),'AER phases differ')
    def one(stage,bdf):
        selected = [(i,r) for i,r in records if r.get('phase') == stage and r.get('bdf') == bdf]
        require(len(selected) == 1,'AER missing/duplicate '+stage+' '+bdf)
        return selected[0]
    summary = []
    for bdf,identity,cap,aer,kind in DEVICES:
        stages = [one(stage,bdf) for stage in ['saved','enabled','pre_restore','restored']]
        old = int(stages[0][1]['old_devctl'],16); mask = int(stages[0][1]['old_uem'],16)
        expected_mask = mask & ~0x10000 if kind == 4 and identity == 0x460d8086 else mask
        for (pos,row),stage in zip(stages,['saved','enabled','pre_restore','restored']):
            require(int(row['id'],16) == identity and int(row['cap'],16) == cap and int(row['aer'],16) == aer and int(row['type']) == kind and
                    row['status_clears'] == '0' and row['interrupt_enables'] == '0' and int(row['old_devctl'],16) == old and int(row['old_uem'],16) == mask,'AER device/scope differs')
            active = stage in ['enabled','pre_restore']
            require(int(row['devctl'],16) == (old|0xa if active else old) and int(row['uem'],16) == (expected_mask if active else mask),'AER controls changed outside owned masks')
            require((pos < begin[0]) if stage in ['saved','enabled'] else (last < pos < end[0]),'AER observations reordered')
            if kind == 4:
                require(not(int(row['rootctl'],16)&7) and not(int(row['rootcmd'],16)&7),'AER system error/interrupt enabled')
            for key in ['ues','ces','capctl','header0','header1','header2','header3']:
                require(0 <= int(row[key],16) <= 0xffffffff,'AER truncated register')
        # Every pre/post transfer snapshot must witness enabled controls.
        expected_phases = {'physical_pull_case_'+str(i)+'_'+side for i in range(1,13) for side in ['before','after']}
        snapshots = [(i,fields(x[len('PCIE_SNAPSHOT '):])) for i,x in enumerate(lines) if x.startswith('PCIE_SNAPSHOT ') and 'bdf='+bdf+' ' in x]
        active_snapshots = [(i,r) for i,r in snapshots if r.get('phase') in expected_phases]
        require(len(active_snapshots) == 24 and {r['phase'] for i,r in active_snapshots} == expected_phases,'AER transfer snapshots missing/duplicate')
        for case in range(1,13):
            ci = next(i for i,x in enumerate(lines) if x.startswith('PHYS_CASE id='+str(case)+' '))
            ri = next(i for i,x in enumerate(lines) if x.startswith('PHYS_DATA_RESULT id='+str(case)+' '))
            positions = [next(i for i,r in active_snapshots if r['phase'] == 'physical_pull_case_'+str(case)+'_'+side) for side in ['before','after']]
            require(ci < positions[0] < positions[1] < ri,'AER snapshots outside their transfer case')
        for pos,row in active_snapshots:
            require(begin[0] < pos < end[0] and row['CONFIG_BYTES'] == '4096' and row['READ_ERRNO'] == '0' and
                    int(row['DEVCTL'],16) == (old|0xa) and int(row['UEM'],16) == expected_mask and not(int(row['COMMAND'],16)&0x100),'AER controls not active across transfers')
            if kind == 4: require(int(row['ROOTCMD'],16) == 0,'AER root interrupt command differs')
            if identity == 0x466e8086: require(int(row['DPC_CTL'],16) == 0,'DPC enabled during test')
        before = stages[0][1]; after = stages[2][1]
        summary.append({'bdf':bdf,'old_devctl':before['devctl'],'enabled_devctl':stages[1][1]['devctl'],
                        'restored':True,'ues_before':before['ues'],'ues_after':after['ues'],
                        'header_after':[after['header'+str(i)] for i in range(4)],
                        'root_status_after':after.get('rootsta'),'root_source_after':after.get('rootsource')})
    return summary


def validate_log(raw,ccfg,kernel=''):
    result = bar0.validate_log(raw,ccfg,kernel)
    result['aer_reporting_qualified'] = False
    if not result['protocol_complete']: return result
    try: summary = qualify_aer(raw)
    except (ValueError,KeyError,TypeError,StopIteration) as exc:
        result.update(status='incomplete_preserved',protocol_complete=False,logs_are_partial_evidence=True,aer_error=str(exc));return result
    result.update(aer_reporting_qualified=True,aer_devices=summary,aer_controls_restored=True,
                  aer_status_cleared=False,aer_interrupts_enabled=False)
    return result
