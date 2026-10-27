from pathlib import Path
import hashlib,importlib.util,re
BASE_SHA='f3f656a94bf1ffc9ac722c8e213c5ffb1a03568128dba16ac1d26ca316aad6f5'
p=Path(__file__).resolve().parent/'inspection_base_validation.py'
if hashlib.sha256(p.read_bytes()).hexdigest()!=BASE_SHA:raise RuntimeError('Inspection validator changed')
s=importlib.util.spec_from_file_location('dmar_inspection_base',str(p));base=importlib.util.module_from_spec(s);s.loader.exec_module(base)
def need(ok,why):
 if not ok:raise ValueError(why)
def fields(s):return dict(re.findall(r'(\w+)=(\S+)',s))
def complete(raw,ccfg,kernel):
 x=base.validate_log(raw,ccfg,kernel);need(x['protocol_complete'],'Base inspection incomplete')
 lines=raw.splitlines()
 markers=['DMAR_READ_BEGIN register_writes=0','DMAR_READ_MODULE_LOADED=1','DMAR_READ_MODULE_UNLOADED=1','DMAR_READ_END register_writes=0']
 for m in markers:need(lines.count(m)==1,'DMAR lifecycle missing/duplicate')
 need([lines.index(m) for m in markers]==sorted(lines.index(m) for m in markers),'DMAR lifecycle reordered')
 for token in ['CASKDMAR_BEGIN ','CASKDMAR_CAP ','CASKDMAR_END ','CASKDMAR_UNLOADED ']:
  need(sum(token in l for l in kernel.splitlines())==1,'DMAR kernel marker missing/duplicate')
 begin=fields(next(l for l in kernel.splitlines() if 'CASKDMAR_BEGIN ' in l))
 need(begin.get('version')=='1' and begin.get('units')=='1' and begin.get('table_bytes')=='80' and begin.get('register_writes')=='0','DMAR table contract differs')
 cap=fields(next(l for l in kernel.splitlines() if 'CASKDMAR_CAP ' in l))
 need(cap.get('base')=='fed91000' and cap.get('ver')=='00000050' and cap.get('cap')=='00d2008c40660462' and cap.get('ecap')=='0000000000f050da','DRHD identity differs')
 end=fields(next(l for l in kernel.splitlines() if 'CASKDMAR_END ' in l))
 unloaded=fields(next(l for l in kernel.splitlines() if 'CASKDMAR_UNLOADED ' in l))
 need(end.get('protocol_complete')=='1' and end.get('register_writes')=='0' and unloaded.get('register_writes')=='0','DMAR read-only completion missing')
 samples=[fields(l) for l in kernel.splitlines() if 'CASKDMAR_SAMPLE ' in l]
 need(len(samples)==2 and [v.get('index') for v in samples]==['0','1'],'DMAR samples incomplete')
 for v in samples:
  g,p=int(v['gsts'],16),int(v['pmen'],16);need(g!=0xffffffff and p!=0xffffffff,'Inaccessible register values')
  expected={'translation_enabled':int(bool(g&(1<<31))),'interrupt_remapping_enabled':int(bool(g&(1<<25))),
            'protected_region_enabled':int(bool(p&(1<<31))),'protected_region_status':int(bool(p&1))}
  need(all(v.get(k)==str(w) for k,w in expected.items()),'Status bit decoding differs')
 x.update(status='complete_native_dmar_read_only',dmar_register_writes=False,dmar_base='fed91000',dmar_samples=samples,
          translation_inactive_in_all_samples=all(v['translation_enabled']=='0' for v in samples),
          protected_regions_inactive_in_all_samples=all(v['protected_region_enabled']=='0' and v['protected_region_status']=='0' for v in samples),
          measurement_scope='Before NVIDIA load, after native USB4 authorization, with identical IOMMU-off arguments. Not an in-transfer hardware trace.')
 return x
def validate_log(raw,ccfg,kernel=''):
 try:return complete(raw,ccfg,kernel)
 except (ValueError,KeyError,TypeError) as e:
  return {'status':'incomplete_preserved','protocol_complete':False,'dmar_error':str(e),'P2P_solution_claimed':False,'logs_are_partial_evidence':True}
