"""Fixture locali: solo file temporanei e comandi simulati."""
from pathlib import Path
import importlib.util,json,sys,tempfile,unittest
from unittest.mock import patch
P=Path(__file__).with_name('collect_cleanup_traffic.py');spec=importlib.util.spec_from_file_location('collector_fixture',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def fixture_log(failures=2,qualified=4):
 lines=[]
 for bdf,(_,value) in m.i.CCFG.items():
  for _ in range(3):lines.append(('PEG_CCFG ' if bdf=='0000:00:01.0' else 'TCSS_CCFG ')+bdf[5:]+' %08x'%value)
 for uid in ['00000000000000000000000000000001','00000000000000000000000000000002']:
  lines.append('TRAFFIC_GPU uuid='+uid+' valid=1')
 for n,(engine,source,destination) in enumerate([('SM',0,1),('CUDA_COPY_REQUEST',0,1),('SM',1,0),('CUDA_COPY_REQUEST',1,0)],1):
  for stage in ['source_initialized','destination_poisoned']:lines.append('FULL_COMPARE stage='+stage+' checked_words=262144 mismatches=0 valid=1')
  lines.append('TRAFFIC_WINDOW id=%d engine=%s s=%d d=%d begin_ns=1000000000 end_ns=2200000000 sampler_joined_ns=2300000000 duration_ns=1200000000 batches=5 submitted_payload_bytes=335544320 budget_exhausted=0 no_host_payload_ops_during_window=1'%(n,engine,source,destination))
  sample=int(n<=qualified);valid=int(n>failures)
  lines.append('NVML_SAMPLER_END phase=%d valid=%d'%(n,sample))
  lines.append('TRAFFIC_DATA_RESULT id=%d engine=%s s=%d d=%d bytes=1048576 checked_words=262144 mismatches=%d valid=%d sampling_valid=%d duration_valid=1 ce_observed=0 direct_route_proven=0'%(n,engine,source,destination,0 if valid else 262144,valid,sample))
 rc=6 if qualified!=4 else (5 if failures else 0)
 lines.extend(['TRAFFIC_PROGRAM_END protocol_complete=1 comparisons=4 failures=%d qualified_windows=%d nvml_only=1 ce_observed=0 direct_route_proven=0 rc=%d'%(failures,qualified,rc),'NATIVE_TEST_RC='+str(rc),'SCRIPT_RC='+str(rc),'PROBE_COMPLETED'])
 return '\n'.join(lines)+'\n'
REAL=fixture_log()
BASE='BootCurrent: 0000\nBootOrder: 0000,0001\nBoot0000* XCP-ng original0\nBoot0001* UEFI OS original1\n'
class Tests(unittest.TestCase):
 def test_complete_data_failure_is_collectible(self):
  v=m.validate_log(REAL);self.assertEqual(v['program_rc'],5);self.assertEqual(v['failures'],2);self.assertFalse(v['P2P_solution_claimed'])
 def test_all_data_pass_does_not_claim_route(self):
  v=m.validate_log(fixture_log(0,4));self.assertEqual(v['program_rc'],0);self.assertTrue(v['data_all_comparisons_pass']);self.assertFalse(v['P2P_solution_claimed'])
 def test_unqualified_sampling_is_collectible(self):
  v=m.validate_log(fixture_log(2,3));self.assertEqual(v['program_rc'],6);self.assertEqual(v['qualified_windows'],3)
 def test_log_refusals(self):
  bad=[REAL.replace('PROBE_COMPLETED','NOT_COMPLETED'),REAL.replace('comparisons=4','comparisons=3'),REAL.replace('qualified_windows=4','qualified_windows=3'),REAL.replace('04008077','00008077'),REAL.replace('SCRIPT_RC=5','SCRIPT_RC=0'),REAL.replace('TRAFFIC_DATA_RESULT id=4','TRAFFIC_DATA_RESULT id=5'),REAL.replace('00000000000000000000000000000001','wrong'),REAL.replace('submitted_payload_bytes=335544320','submitted_payload_bytes=1'),REAL.replace('direct_route_proven=0','direct_route_proven=1'),REAL.replace('sampler_joined_ns=2300000000','sampler_joined_ns=2199999999'),REAL.replace('duration_valid=1','duration_valid=0'),REAL.replace('source_initialized','source_not_checked')]
  for n,s in enumerate(bad):
   with self.subTest(case=n),self.assertRaises((RuntimeError,ValueError)):m.validate_log(s)
 def test_tree_rejects_links(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);(p/'file').write_text('a');(p/'link').symlink_to('file')
   with self.assertRaises(RuntimeError):m.tree(p)
 def exercise(self,scenario):
  with tempfile.TemporaryDirectory() as t:
   r=Path(t);dst=r/'esp';dst.mkdir();(dst/'before-driver').mkdir();state=r/'state';state.write_text('{"stage":"armed"}\n')
   names=set(m.i.PACKAGE_NAMES)|{'result.log','kernel.log'}|{'before-driver/'+n for n in m.EXPECTED_CONFIGS}
   for n in names:(dst/n).write_text(REAL if n=='result.log' else n+' fixture\n')
   raw_tree=m.tree(dst);entries=m.i.parse_boot(BASE);boot=[BASE+'Boot0002* CaskLogic TCSS traffic probe exactfixture\n'];commands=[]
   obs={'tree':raw_tree,'state_sha256':m.i.sha(state),'baseline':{'sha256':'baseline','baseline':{'original_files':{'original':{'sha256':'abc'}}}},'state':{'entry':'0002','original_entries':entries},'boot':boot[0],'entries':m.i.parse_boot(boot[0]),'ccfg':{k:v[1] for k,v in m.i.CCFG.items()},'result':m.validate_log(REAL)}
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
    c=m.collect(obs);self.assertEqual(c['status'],'collected_verified');self.assertEqual(m.tree(m.BACKUP),raw_tree);self.assertEqual(len(m.i.read_json(m.RESULTS/m.RAW_MANIFEST)),17);self.assertEqual(len(m.tree(m.RESULTS)['files']),19);self.assertTrue(dst.exists());self.assertEqual(commands,[])
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
    c=m.cleanup(obs,c);self.assertEqual(c['status'],'cleanup_verified');self.assertFalse(dst.exists());self.assertEqual(m.tree(m.BACKUP),raw_tree);self.assertEqual(len(m.tree(m.RESULTS)['files']),19);self.assertEqual(boot[0],BASE);self.assertEqual(sum('--delete-bootnum' in x for x in commands),1)
 def test_default_no_mutations(self):self.exercise('readonly')
 def test_collection_preserves_every_file(self):self.exercise('collect')
 def test_cleanup_preserves_backup_and_original_boot(self):self.exercise('cleanup')
 def test_corrupted_backup_prevents_delete(self):self.exercise('backup_corrupt')
 def test_changed_source_prevents_delete(self):self.exercise('source_corrupt')
 def test_corrupted_results_prevent_delete(self):self.exercise('result_corrupt')
 def test_unexpected_boot_after_entry_delete_preserves_directory(self):self.exercise('boot_mismatch')
if __name__=='__main__':unittest.main()
