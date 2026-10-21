"""Dati sintetici PHYS, nessun risultato hardware implicato."""

def fixture_log(ccfg,failures=2,qualified=4,calfail=0):
 lines=[]
 def row(kind,**values):lines.append(kind+' '+' '.join('%s=%s'%(k,v) for k,v in values.items()))
 for bdf,(_,value) in ccfg.items():
  for _ in range(3):lines.append(('PEG_CCFG ' if bdf=='0000:00:01.0' else 'TCSS_CCFG ')+bdf[5:]+' %08x'%value)
 for uuid in ['00000000000000000000000000000001','00000000000000000000000000000002']:row('PHYS_GPU',uuid=uuid,valid=1)
 for n,(engine,src,dst) in enumerate([('SM',0,1),('PHYSICAL_CE',0,1),('SM',1,0),('PHYSICAL_CE',1,0)],1):
  addr_src=0x100000+src*0x100000;addr_dst=0x300000+dst*0x100000
  row('PHYS_CASE',id=n,engine=engine,s=src,d=dst,executor=src,bytes=4,src='%x'%addr_src,dst='%x'%addr_dst,allocations_unchanged=1)
  for stage in ['source_initialized','destination_poisoned']:row('FULL_COMPARE',stage=stage,checked_words=1,mismatches=0,valid=1)
  valid=int(n>failures);mismatch=1-valid
  if engine=='PHYSICAL_CE':
   pa=0x4600400000 if dst else 0x4000400000;bar=0x4600000000 if dst else 0x4000000000
   row('PHYS_IOCTL_RESULT',request=1000+n,src='%x'%addr_src,dst='%x'%addr_dst,bytes=4,rv=0,errno=0,rmStatus=0,flags='77',source_pa='100000',destination_pa='%x'%pa,source_offset=0,destination_offset=0,source_handle='123',destination_handle='456',ce_class='c7b5',launch='4003186',source_mode=0,destination_mode=1,inputs_unchanged=1)
   row('PHYS_BAR1',owner=dst,start='%x'%bar,end='%x'%(bar+0x10000000-1),flags='200',destination_physical='%x'%pa,valid=1)
  row('FULL_COMPARE',stage='peer_payload',owner=dst,s=src,d=dst,bytes=4,iteration=n,checked_words=1,mismatches=mismatch,valid=valid)
  row('PHYS_DATA_RESULT',id=n,engine=engine,s=src,d=dst,bytes=4,checked_words=1,mismatches=mismatch,valid=valid,physical_ioctl_completed=int(engine=='PHYSICAL_CE'),direct_route_proven=0)
 for n,(mode,owner) in enumerate([('HOST_TO_DEVICE',0),('DEVICE_TO_HOST',0),('HOST_TO_DEVICE',1),('DEVICE_TO_HOST',1)],1):
  row('CALIBRATION_CASE',id=n,operation=mode,owner=owner,bytes=1048576,owner_only=1,peer_access='NONE',p2p=0)
  row('FULL_COMPARE',stage='calibration_owner_initialized',owner=owner,iteration=n,checked_words=262144,mismatches=0,valid=1)
  sample=int(n<=qualified);valid=int(n>calfail);mismatch=0 if valid else 1
  row('CALIBRATION_WINDOW',id=n,operation=mode,owner=owner,begin_ns=1000000000,end_ns=2200000000,sampler_joined_ns=2300000000,duration_ns=1200000000,batches=5,submitted_host_payload_bytes=335544320,budget_exhausted=0,p2p=0)
  row('NVML_SAMPLER_END',phase=n,valid=sample)
  for stage in ['calibration_host_payload','calibration_owner_payload']:row('FULL_COMPARE',stage=stage,owner=owner,iteration=n,checked_words=262144,mismatches=mismatch,valid=valid)
  row('CALIBRATION_DATA_RESULT',id=n,operation=mode,owner=owner,bytes=1048576,host_mismatches=mismatch,owner_mismatches=mismatch,valid=valid,sampling_valid=sample,duration_valid=1,p2p=0,counter_sensitivity_proven=0)
 rc=6 if qualified!=4 or calfail else (5 if failures else 0)
 row('PHYS_PROGRAM_END',protocol_complete=1,p2p_comparisons=4,p2p_failures=failures,physical_completed=2,calibrations=4,calibration_failures=calfail,qualified_windows=qualified,direct_route_proven=0,rc=rc)
 lines.extend(['NATIVE_TEST_RC='+str(rc),'SCRIPT_RC='+str(rc),'PROBE_COMPLETED'])
 return '\n'.join(lines)+'\n'
