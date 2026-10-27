"""Offline replay of scoped published records; does not access hardware."""
from pathlib import Path
import importlib.util,json
R=Path(__file__).resolve().parent
CCFG={'0000:00:01.0':(0,0x04008077),'0000:00:07.0':(0,0x0e009077),'0000:00:07.2':(0,0x0e009077)}
p=R/'status/dmar_log_validation.py';s=importlib.util.spec_from_file_location('status_validation',p);v=importlib.util.module_from_spec(s);s.loader.exec_module(v)
d=R/'status/results';x=v.validate_log((d/'result-markers.log').read_text(),CCFG,(d/'kernel-research.log').read_text())
# Presence of all raw files was checked by the private collector. The public
# replay checks scoped markers/register observations, not omitted inventories.
expected=json.loads((d/'qualified.json').read_text());expected.pop('missing_expected_files',None)
assert x==expected,(x,expected)
assert x['protocol_complete'] and x['translation_inactive_in_all_samples'] and x['protected_regions_inactive_in_all_samples']
print('Read-only IOMMU-off status: scoped records match the qualified result.')
p=R/'translated/iova_log_validation.py';s=importlib.util.spec_from_file_location('iova_validation',p);v=importlib.util.module_from_spec(s);s.loader.exec_module(v)
for folder in ['results','attempt-01']:
 d=R/'translated'/folder
 x=v.validate_log((d/'result-markers.log').read_text(),CCFG,(d/'kernel-research.log').read_text())
 expected=json.loads((d/'qualified.json').read_text());expected.pop('missing_expected_files',None)
 assert x==expected,(folder,x,expected)
 if folder=='results':assert x['protocol_complete'] and x['host_controls_passed']==8 and x['peer_reads_passed']==0
 else:assert not x['protocol_complete']
print('Translated IOVA: 8 RAM controls pass, 0/4 peer reads pass; the pre-GPU aborted attempt remains incomplete.')
