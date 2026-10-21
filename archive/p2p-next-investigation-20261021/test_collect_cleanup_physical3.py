"""Fixture locali: solo file temporanei e comandi simulati."""
from pathlib import Path
import importlib.util,json,sys,tempfile,unittest
from unittest.mock import patch
P=Path(__file__).with_name('collect_cleanup_physical3.py');spec=importlib.util.spec_from_file_location('collector_fixture',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
from physical3_log_fixture import fixture_log as make_fixture

def fixture_log(failures=2,qualified=4,calfail=0):
 return make_fixture(m.i.CCFG,failures,qualified,calfail)
REAL=fixture_log()
BASE='BootCurrent: 0000\nBootOrder: 0000,0001\nBoot0000* XCP-ng original0\nBoot0001* UEFI OS original1\n'
class Tests(unittest.TestCase):
 def test_complete_data_failure_is_collectible(self):
  v=m.validate_log(REAL);self.assertEqual(v['program_rc'],5);self.assertEqual(v['failures'],2);self.assertFalse(v['P2P_solution_claimed'])
 def test_all_data_pass_does_not_claim_route(self):
  v=m.validate_log(fixture_log(0,4));self.assertEqual(v['program_rc'],0);self.assertTrue(v['data_all_comparisons_pass']);self.assertFalse(v['P2P_solution_claimed'])
 def test_unqualified_sampling_is_collectible(self):
  v=m.validate_log(fixture_log(2,3));self.assertEqual(v['program_rc'],6);self.assertEqual(v['qualified_windows'],3)
 def test_partial_logs_preserved_without_qualification(self):
  bad=[REAL.replace('PROBE_COMPLETED','NOT_COMPLETED'),REAL.replace('p2p_comparisons=4','p2p_comparisons=3'),REAL.replace('qualified_windows=4','qualified_windows=3'),REAL.replace('04008077','00008077'),REAL.replace('SCRIPT_RC=5','SCRIPT_RC=0'),REAL.replace('PHYS_DATA_RESULT id=4','PHYS_DATA_RESULT id=5'),REAL.replace('00000000000000000000000000000001','wrong'),REAL.replace('submitted_host_payload_bytes=335544320','submitted_host_payload_bytes=1'),REAL.replace('direct_route_proven=0','direct_route_proven=1'),REAL.replace('sampler_joined_ns=2300000000','sampler_joined_ns=2199999999'),REAL.replace('duration_valid=1','duration_valid=0'),REAL.replace('source_initialized','source_not_checked'),REAL.replace('launch=4003186','launch=4003182'),REAL.replace('flags=77','flags=73'),REAL.replace('destination_mode=1','destination_mode=2'),REAL.replace('source_offset=0','source_offset=4'),REAL.replace('physical_completed=2','physical_completed=1'),REAL.replace('PHYS_BAR1 owner=1','PHYS_BAR1 owner=0'),'', 'PHYS_ABORT reason=early protocol_complete=0 rc=27\n', 'PHYS_CE_RETAINED request=1 flags=7b parked=1\nWATCHDOG_REBOOT\n']
  for n,raw in enumerate(bad):
   with self.subTest(case=n):
    result=m.validate_log(raw);self.assertFalse(result['protocol_complete']);self.assertEqual(result['status'],'incomplete_preserved');self.assertFalse(result['P2P_solution_claimed']);self.assertFalse(result['data_all_comparisons_pass'])
 def test_kernel_watchdog_evidence(self):
  result=m.validate_log('', 'WATCHDOG_REBOOT objects_retained_until_reboot=1')
  self.assertTrue(result['watchdog_observed']);self.assertTrue(result['retained_observed']);self.assertFalse(result['protocol_complete'])
 def test_complete_user_log_with_kernel_watchdog_is_partial(self):
  result=m.validate_log(REAL,'WATCHDOG_REBOOT');self.assertFalse(result['protocol_complete']);self.assertTrue(result['watchdog_observed'])
 def test_calibration_data_failure_rc6(self):
  result=m.validate_log(fixture_log(2,4,1));self.assertTrue(result['protocol_complete']);self.assertEqual(result['program_rc'],6);self.assertEqual(result['calibration_failures'],1)
 def test_observations_preserve_missing_native_outputs(self):
  for scenario in ('complete','no_configs','kernel_only','no_logs','unexpected'):
   with self.subTest(scenario=scenario),tempfile.TemporaryDirectory() as temp:
    r=Path(temp);dst=r/'esp';dst.mkdir();statefile=r/'state.json'
    names=set(m.i.PACKAGE_NAMES)
    if scenario=='complete':
     (dst/'before-driver').mkdir();names|={'before-driver/'+n for n in m.EXPECTED_CONFIGS}
    if scenario in ('complete','no_configs','unexpected'):names|={'result.log','kernel.log'}
    if scenario=='kernel_only':names.add('kernel.log')
    if scenario=='unexpected':names.add('unplanned.bin')
    for name in names:(dst/name).write_text(REAL if name=='result.log' else name+' fixture')
    (dst/'IDENTITY.txt').write_bytes(m.i.IDENTITY)
    package={'files':{n:m.i.sha(dst/n) for n in ('probe-kernel.efi','probe-initrd.img','IDENTITY.txt')},
             'metadata_sha256':{n:m.i.sha(dst/n) for n in ('files.json','build-manifest.json')}}
    original=m.i.parse_boot(BASE)
    boot=BASE+'Boot0002* '+m.i.LABEL+'\tHD(4,GPT,'+m.i.PARTUUID+',x)/File('+m.i.LOADER+')'+m.i.ARGS+'\n'
    state=dict(stage='armed',original_entries=original,entry='0002',baseline_sha256='baseline',
               kernel_args=m.i.ARGS,label=m.i.LABEL,loader=m.i.LOADER,**package)
    statefile.write_text(json.dumps(state))
    with patch.multiple(m.i,DST=dst,STATE=statefile),patch.object(m.i,'host_preflight',return_value=({'sha256':'baseline'},{})),patch.object(m.i,'run',return_value=boot),patch.object(m.i,'verify_package',return_value=package):
     if scenario=='unexpected':
      with self.assertRaises(RuntimeError):m.observations()
     else:
      obs=m.observations();self.assertEqual(obs['result']['protocol_complete'],scenario=='complete');self.assertFalse(obs['result']['P2P_solution_claimed'])
      if scenario!='complete':self.assertTrue(obs['result']['missing_expected_files'])
 def test_tree_rejects_links(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);(p/'file').write_text('a');(p/'link').symlink_to('file')
   with self.assertRaises(RuntimeError):m.tree(p)
 def exercise(self,scenario):
  with tempfile.TemporaryDirectory() as t:
   r=Path(t);dst=r/'esp';dst.mkdir();(dst/'before-driver').mkdir();state=r/'state';state.write_text('{"stage":"armed"}\n')
   names=set(m.i.PACKAGE_NAMES)|{'result.log','kernel.log'}|{'before-driver/'+n for n in m.EXPECTED_CONFIGS}
   if scenario=='partial_cleanup':names=set(m.i.PACKAGE_NAMES)|{'result.log','kernel.log'}
   for n in names:(dst/n).write_text(('PHYS_CE_RETAINED request=1 flags=7b parked=1\nWATCHDOG_REBOOT\n' if scenario=='partial_cleanup' else REAL) if n=='result.log' else n+' fixture\n')
   raw_tree=m.tree(dst);entries=m.i.parse_boot(BASE);boot=[BASE+'Boot0002* CaskLogic TCSS physical3 probe exactfixture\n'];commands=[]
   obs={'tree':raw_tree,'state_sha256':m.i.sha(state),'baseline':{'sha256':'baseline','baseline':{'original_files':{'original':{'sha256':'abc'}}}},'state':{'entry':'0002','original_entries':entries},'boot':boot[0],'entries':m.i.parse_boot(boot[0]),'ccfg':{k:v[1] for k,v in m.i.CCFG.items()},'result':m.validate_log((dst/'result.log').read_text())}
   def run(args):
    commands.append(args)
    if args==['efibootmgr','-v']:return boot[0]
    if args==['efibootmgr','--bootnum','0002','--delete-bootnum']:
     boot[0]=BASE
     if scenario=='boot_mismatch':boot[0]=BASE.replace('original0','changed')
     return ''
    raise AssertionError('External command not mocked '+repr(args))
   with patch.multiple(m,R=r,BACKUP=r/'backup',RESULTS=r/'results',COLLECTION=r/'collection'),patch.multiple(m.i,DST=dst,STATE=state),patch.object(m,'observations',return_value=obs),patch.object(m.i,'run',side_effect=run),patch.object(m.i,'verify_baseline'),patch.object(m.i,'read_ccfg',return_value=obs['ccfg']),patch.object(m.os,'sync'),patch('builtins.print'):
    if scenario=='readonly':
     before=set(r.rglob('*'))
     with patch.object(sys,'argv',['fixture']):m.main()
     self.assertEqual(before,set(r.rglob('*')));self.assertEqual(commands,[]);return
    c=m.collect(obs);self.assertEqual(c['status'],'collected_verified');self.assertEqual(m.tree(m.BACKUP),raw_tree);self.assertEqual(len(m.i.read_json(m.RESULTS/m.RAW_MANIFEST)),len(names)-2);self.assertEqual(len(m.tree(m.RESULTS)['files']),len(names));self.assertTrue(dst.exists());self.assertEqual(commands,[])
    if scenario=='collect':return
    if scenario in ('backup_corrupt','source_corrupt','result_corrupt'):
     target={'backup_corrupt':m.BACKUP/'probe-initrd.img','source_corrupt':dst/'probe-initrd.img','result_corrupt':m.RESULTS/'result.log'}[scenario];target.write_bytes(b'changed')
     with self.assertRaises(RuntimeError):
      if scenario=='source_corrupt':m.cleanup(dict(obs,tree=m.tree(dst)),c)
      else:m.cleanup(obs,c)
     self.assertTrue(dst.exists());self.assertFalse(any('--delete-bootnum' in x for x in commands));return
    if scenario=='boot_mismatch':
     with self.assertRaises(RuntimeError):m.cleanup(obs,c)
     self.assertTrue(dst.exists());self.assertEqual(m.tree(m.BACKUP),raw_tree);return
    c=m.cleanup(obs,c);self.assertEqual(c['status'],'cleanup_verified');self.assertFalse(dst.exists());self.assertEqual(m.tree(m.BACKUP),raw_tree);self.assertEqual(len(m.tree(m.RESULTS)['files']),len(names));self.assertEqual(boot[0],BASE);self.assertEqual(sum('--delete-bootnum' in x for x in commands),1)
 def test_retained_partial_backup_and_cleanup(self):self.exercise('partial_cleanup')
 def test_default_no_mutations(self):self.exercise('readonly')
 def test_collection_preserves_every_file(self):self.exercise('collect')
 def test_cleanup_preserves_backup_and_original_boot(self):self.exercise('cleanup')
 def test_corrupted_backup_prevents_delete(self):self.exercise('backup_corrupt')
 def test_changed_source_prevents_delete(self):self.exercise('source_corrupt')
 def test_corrupted_results_prevent_delete(self):self.exercise('result_corrupt')
 def test_unexpected_boot_after_entry_delete_preserves_directory(self):self.exercise('boot_mismatch')
if __name__=='__main__':unittest.main()
