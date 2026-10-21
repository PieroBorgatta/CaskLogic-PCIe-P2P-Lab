"""Exercise the actual shell AWK gate on synthetic ordinary-text logs only."""
from pathlib import Path
import re,subprocess,tempfile,json
P=Path(__file__).parent
source=(P/'init-tcss-native.sh').read_text()
m=re.search(r'  awk -v expected_rc="\$probe_rc" \'\n(.*?)\n  \' "\$probe_dir/result.log"',source,re.S)
assert m
script=m.group(1)
names=['baseline_initial','ada_off','baseline_restored','both_off','baseline_final'];modes=[0,1,0,2,0]
lines=[]
for i,(name,mode) in enumerate(zip(names,modes)):
 lines.append(f'ATTR_PHASE_BEGIN index={i} name={name} mode={mode}')
 lines.append(f'ATTR_SNAPSHOT label=phase{i} valid=1')
 for owner in range(2):
  lines.append(f'REMOTE_READ phase={i} s={owner} d={1-owner} valid=0')
  lines.append(f'REMOTE_WRITE phase={i} s={1-owner} d={owner} valid={int(owner==0)}')
 lines.append(f'ATTR_PHASE_RESULT index={i} name={name} mode={mode} failures=3 comparisons=4 valid_protocol=1')
lines+=['ATTR_WRITE width=16 mask=0810 valid=1']*6
lines+=['ATTR_RESTORE valid=1']*8
lines+=['ATTR_FINAL_RESTORE valid=1','ATTR_PROGRAM_END protocol_complete=1 restored=1 rc=5']
base='\n'.join(lines)+'\n'
cases=[('valid_3fail_per_phase',base,True)]
for name,old,new in [
 ('missing_phase','ATTR_PHASE_RESULT index=2','NOT_A_PHASE index=2'),
 ('duplicate_phase','ATTR_PHASE_RESULT index=2','ATTR_PHASE_RESULT index=1'),
 ('wrong_mode','name=ada_off mode=1','name=ada_off mode=2'),
 ('failure_sum_disagrees','failures=3 comparisons=4','failures=2 comparisons=4'),
 ('missing_read','REMOTE_READ phase=3 s=0','NOT_A_READ phase=3 s=0'),
 ('wrong_operation_phase','REMOTE_READ phase=3 s=0','REMOTE_READ phase=4 s=0'),
 ('invalid_result','REMOTE_READ phase=0 s=0 d=1 valid=0','REMOTE_READ phase=0 s=0 d=1 valid=2'),
 ('attributes_changed','ATTR_SNAPSHOT label=phase2 valid=1','ATTR_SNAPSHOT label=phase2 valid=0'),
 ('write_wrong_width','width=16','width=32'),
 ('write_wrong_mask','mask=0810','mask=ffff'),
 ('missing_write','ATTR_WRITE width=16 mask=0810 valid=1\n',''),
 ('failed_restore','ATTR_RESTORE valid=1','ATTR_RESTORE valid=0'),
 ('missing_final_restore','ATTR_FINAL_RESTORE valid=1\n',''),
 ('wrong_rc','restored=1 rc=5','restored=1 rc=0'),
 ('incomplete','protocol_complete=1','protocol_complete=0'),
 ('not_restored','protocol_complete=1 restored=1','protocol_complete=1 restored=0'),
]:cases.append((name,base.replace(old,new,1),False))
cases.append(('abort_even_with_complete_records',base+'ATTR_TRIAL_ABORT reason=fixture\n',False))
cases.append(('out_of_order_phase',base.replace('ATTR_PHASE_BEGIN index=0','ATTR_PHASE_BEGIN index=1',1),False))
with tempfile.TemporaryDirectory() as t:
 path=Path(t)/'log'
 for name,text,expect in cases:
  path.write_text(text)
  r=subprocess.run(['awk','-v','expected_rc=5',script,str(path)],capture_output=True,text=True)
  assert (r.returncode==0)==expect,(name,r.returncode,r.stderr)
out={'status':'PASS','cases':len(cases),'uses_actual_init_awk':True,'hardware_or_remote_actions':False,'case_names':[x[0] for x in cases]}
(P/'log-gate-validation.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out))
