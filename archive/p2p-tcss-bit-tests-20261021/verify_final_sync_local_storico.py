#!/usr/bin/env python3
"""Verifica solo copie locali del ripristino e della pulizia finale."""
from pathlib import Path
import hashlib,json,stat,re,datetime,zoneinfo
R=Path(__file__).resolve().parent
B=R/'final-sync-esp-artifacts-verified-20261021T031941-acf86b3c'
F=R/'native-sync-restore-results'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for part in iter(lambda:f.read(1024*1024),b''):h.update(part)
 return h.hexdigest()
def txt(p):
 b=p.read_bytes();return b.decode('utf-16' if b[:2] in (b'\xff\xfe',b'\xfe\xff') else 'utf-8').strip()
def tree(root):
 dirs=[];files={}
 for p in root.rglob('*'):
  assert not p.is_symlink();rel=str(p.relative_to(root));st=p.lstat()
  if stat.S_ISDIR(st.st_mode):dirs.append(rel)
  else:
   assert stat.S_ISREG(st.st_mode);files[rel]={'size':st.st_size,'sha256':sha(p)}
 return {'directories':sorted(dirs),'files':files}
c=json.loads((R/'cleanup-sync-verified.json').read_text());h=json.loads((R/'final-sync-system-health.json').read_text());v=json.loads((F/'restore-verification.json').read_text());col=json.loads((F/'collected-sha256.json').read_text())
assert len(col)==28 and all(sha(F/n)==digest for n,digest in col.items())
assert c==json.loads((B/'cleanup-journal.json').read_text())==h['host']['cleanup']
assert c['status']=='cleanup_verified' and c['original_boot_files_unchanged'] and c['all_files_including_images_preserved'] and c['temporary_entries_and_directories_removed']
assert c['script_sha256']==sha(R/'cleanup_sync_trial_verified.py')=='47ef60bdff9802c70864369a61fcdded8cb925ef0020002c9569337b882236f5'
assert set(c['tree_manifests'])=={'CaskLogicTcssSyncTest','CaskLogicTcssNative'}
trees={}
for name,manifest in c['tree_manifests'].items():
 actual=tree(B/name);assert actual==manifest,name;trees[name]={'files':len(actual['files']),'directories':actual['directories'],'bytes':sum(v['size'] for v in actual['files'].values())}
assert sum(x['files'] for x in trees.values())==47
for n,digest in col.items():assert sha(B/'CaskLogicTcssSyncTest'/n)==digest
original=(R/'native-sync-flash-package/ORIGINAL.bin').read_bytes();actual=(F/'region-restored.bin').read_bytes()
assert len(original)==len(actual)==0x1e000 and original==actual and hashlib.sha256(actual).hexdigest()=='b81e705a87c89a668c4bbddd3538a82ccd5ebea4b156ce2d79762147310deba9'
assert sha(F/'region-after.bin')=='c37f53eec3a5702d4a3e7b9d55bf382050100e324f2ec1210d9b98439cabedf4'
assert txt(F/'restore-status.txt')=='ORIGINAL_RESTORED_AND_READBACK_VERIFIED'
assert 'TcssRegionGate Sync v4 RESTORE_CHECK PASS' in txt(F/'RESTORED.flag')
gate=txt(F/'region-restore-gate.txt');assert 'readback_byte_mismatches=0x0000000000000000' in gate and 'phase=all_checks_passed_before_flag' in gate and 'result=FAIL' not in gate
assert v['status']=='ORIGINAL_RESTORED_AND_READBACK_VERIFIED' and v['readback_mismatches']==0 and v['region_start']==0x1b0b000 and v['region_length']==0x1e000
want={'0000:00:01.0':0x04008077,'0000:00:07.0':0x0e009077,'0000:00:07.2':0x0e009077}
assert c['ccfg']==c['ccfg_final']==want and {k:int(x['CCFG'],16) for k,x in v['ccfg'].items()}==want
for boot in [c['boot_after'],h['host']['boot']['stdout']]:
 assert 'BootNext:' not in boot and re.search(r'^BootCurrent: 0000$',boot,re.M) and re.search(r'^BootOrder: 0000,0001$',boot,re.M)
 assert set(re.findall(r'^Boot([0-9A-F]{4})\*? ',boot,re.M))=={'0000','0001'}
assert c['mutations']==[{'entry_removed':'0002'},{'entry_removed':'0003'},{'directory_removed':'CaskLogicTcssSyncTest'},{'directory_removed':'CaskLogicTcssNative'}]
vm=h['host']['vm_states']['stdout'];assert re.search(r'c1343d2f-8b8a-c957-a51c-c397f4ac0034.*?03-Windows_11.*?suspended.*?8589934592',vm,re.S) and re.search(r'd6338ea9-6820-b365-bd0f-7d3790ba2ea7.*?01-Docker_A.*?running.*?27917287424',vm,re.S)
assert h['host']['windows_suspend_vdi']['stdout']=='39affde2-d364-4e72-9d0e-cb422542db75'
g=h['guest'];assert g['hostname']['stdout']=='gpu-vm'
assert g['training_active']['stdout']=='inactive' and g['training_enabled']['stdout']=='disabled'
for svc in ['fan','persistence','docker']:assert g[svc]['stdout']=='active' and g[svc]['rc']==0
assert g['compute_apps']['stdout']=='' and g['compute_apps']['rc']==0 and g['xid_lines']==[]
gpus=g['gpus']['stdout'].splitlines();assert len(gpus)==2 and all('595.99.02' in x for x in gpus)
for uid in ['GPU-00000000-0000-0000-0000-000000000002','GPU-00000000-0000-0000-0000-000000000001']:assert sum(uid in x for x in gpus)==1
assert g['driver_disk_srcversion']['stdout']==g['driver_loaded_srcversion']=='919309EF6954372EFADD77E'
assert g['driver_path']['stdout']=='/lib/modules/7.0.0-38-generic/updates/dkms/nvidia.ko.zst'
cecol=json.loads((R/'native-ce-gpu-results/collected-sha256.json').read_text())
for n,digest in cecol.items():
 p=B/'CaskLogicTcssNative'/n
 if p.exists():assert sha(p)==digest
when=lambda t:datetime.datetime.fromtimestamp(t,zoneinfo.ZoneInfo('Europe/Rome')).isoformat()
report={'status':'PASS_LOCAL_RESTORE_BACKUP_AND_RECORDED_HEALTH_AUDIT','reviewer_hardware_operations':False,'restore_collected_files_verified':len(col),'restore_sha256':sha(F/'region-restored.bin'),'candidate_before_restore_sha256':sha(F/'region-after.bin'),'region_start':0x1b0b000,'region_bytes':0x1e000,'byte_mismatches':0,'restore_gate_checked':True,'backup':str(B),'backup_trees_recomputed':trees,'backup_file_count':47,'backup_journal_matches_cleanup_report':True,'cleanup_time_CEST':when(c['epoch']),'restore_collection_time_CEST':when(v['collected_epoch']),'CCFG_restored':{k:f'{x:08x}' for k,x in want.items()},'boot_entries':['0000','0001'],'BootNext_present':False,'original_boot_files_unchanged_recorded':True,'temporary_entries_and_directories_removed_recorded':True,'host_health_time_CEST':when(h['host']['observed_epoch']),'guest_health_time_CEST':when(g['observed_epoch']),'guest_services_active':['fan','persistence','docker'],'training':'inactive and disabled','GPU_count':2,'GPU_driver_version':'595.99.02','compute_apps':[],'Xid_lines_in_health_snapshot':[],'module_path':g['driver_path']['stdout'],'loaded_disk_srcversion':g['driver_loaded_srcversion'],'disk_module_sha256':g['driver_disk_sha256'],'Windows_state':'suspended','Windows_suspend_VDI':h['host']['windows_suspend_vdi']['stdout'],'Windows_memory_bytes':8589934592,'Docker_state':'running','Docker_memory_bytes':27917287424,'source_files_sha256':{n:sha(R/n) for n in ['cleanup-sync-verified.json','final-sync-system-health.json','native-sync-restore-results/restore-verification.json']},'limits':['This audit rehashes local copies and checks recorded observations; it is not a new live interrogation.','The restored span is the FSP region only. SaSetup is outside it and was not independently reread.','srcversion919309EF6954372EFADD77E is also present in the experimental dynamic module; source version equality alone does not prove full stock RM identity.','No preexisting authoritative stock reference for compressed module hash0b3110fde7eb34d578ea50b7da21d2539b1ff228fd017efc03e71a6aeace008d was found in this local audit.','The health snapshot is not a complete data-integrity audit and does not imply Windows has resumed.']}
(R/'final-sync-independent-review-storico.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({'status':report['status'],'restore_files':len(col),'backup_files':47,'trees':trees,'cleanup_CEST':report['cleanup_time_CEST'],'stock_identity_limitation':True}))
