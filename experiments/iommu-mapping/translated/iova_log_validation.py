"""Qualify the bounded IOVA experiment; a completed negative is not a P2P fix."""
import re
def fields(s):return dict(re.findall(r'(\w+)=(\S+)',s))
def need(ok,why):
 if not ok:raise ValueError(why)
def complete(raw,ccfg,kernel):
 lines=raw.splitlines();kl=kernel.splitlines()
 for marker in ['IOVA_BEGIN abi=1 peer_register_offset=0 peer_reads_only=1 ordinary_peer_access=0 host_staging_for_peer=0','IOVA_END protocol_complete=1 p2p_solution_claimed=0','IOVA_DMAR_BEFORE_BEGIN','IOVA_DMAR_BEFORE_END','IOVA_DMAR_AFTER_BEGIN','IOVA_DMAR_AFTER_END','IOVA_DATA_DISKS_UNMOUNTED','NATIVE_TEST_RC=0','SCRIPT_RC=0','PROBE_COMPLETED']:
  need(lines.count(marker)==1,'Missing/duplicate marker: '+marker)
 need('IOVA_ERROR' not in raw and 'IOVA_PARKED' not in raw and 'WATCHDOG_REBOOT' not in raw+kernel,'Aborted/error/watchdog')
 need('intel_iommu=on iommu.passthrough=0 iommu.strict=1' in raw and 'intel_iommu=off' not in raw and ' iommu=off' not in raw,'Translated strict boot absent')
 need('IOVA_MMIO_PARAMETER=Y BUILTIN_TESTS_PARAMETER=1' in raw,'Diagnostic parameters absent')
 need(not re.search(r' /(?:mnt|media)/(?!esp(?: |/))',raw),'Unexpected mounted data path')
 mounts=[l.split() for l in lines if re.match(r'^\S+ /\S* \S+ \S+ \d+ \d+$',l)]
 types={'/proc':'proc','/sys':'sysfs','/dev':'devtmpfs','/run':'tmpfs','/mnt/esp':'vfat'}
 need(mounts and all((v[1]=='/' and v[0]=='rootfs' and v[2]=='rootfs') or
                    (v[1] in types and v[2]==types[v[1]]) for v in mounts),'Mount inventory missing/unexpected')
 for bdf,(_,value) in ccfg.items():
  vals=re.findall(r'^(?:PEG_CCFG|TCSS_CCFG) '+re.escape(bdf[5:])+r' ([0-9a-f]+)$',raw,re.M)
  need(len(vals)==3 and all(int(v,16)==value for v in vals),'Firmware CCFG differs')
 begins=[fields(l) for l in kl if 'CASKDMAR_BEGIN ' in l];caps=[fields(l) for l in kl if 'CASKDMAR_CAP ' in l]
 ends=[fields(l) for l in kl if 'CASKDMAR_END ' in l];unloads=[fields(l) for l in kl if 'CASKDMAR_UNLOADED ' in l]
 need(len(begins)==len(caps)==len(ends)==len(unloads)==2,'DMAR lifecycle incomplete')
 need(all(v.get('units')=='1' and v.get('table_bytes')=='80' and v.get('register_writes')=='0' for v in begins),'DMAR table differs')
 need(all(v.get('base')=='fed91000' and v.get('ver')=='00000050' and v.get('cap')=='00d2008c40660462' and v.get('ecap')=='0000000000f050da' for v in caps),'DMAR identity differs')
 need(all(v.get('protocol_complete')=='1' and v.get('register_writes')=='0' for v in ends) and all(v.get('register_writes')=='0' for v in unloads),'DMAR completion absent')
 samples=[fields(l) for l in kl if 'CASKDMAR_SAMPLE ' in l]
 need(len(samples)==4 and [v.get('index') for v in samples]==['0','1','0','1'],'DMAR samples missing/reordered')
 for v in samples:
  g,p=int(v['gsts'],16),int(v['pmen'],16)
  need(g!=0xffffffff and (g>>31)&1 and p==0 and v.get('translation_enabled')=='1' and v.get('protected_region_enabled')==v.get('protected_region_status')=='0','DMA translation not active or protected regions active')
  need(v.get('interrupt_remapping_enabled')==str(int(bool(g&(1<<25)))),'IRQ remap decode differs')
 need(not re.search(r'NVRM: Xid|DMAR:.*(?:fault|FAULT)|DMA Read NO_PASID|DMA Write NO_PASID',kernel),'GPU/IOMMU fault reported')
 rows=[fields(l) for l in kl if 'CASKIOVA ' in l]
 out=[]
 for index in range(2):
  subset=[v for v in rows if v.get('index')==str(index) and v.get('request')==str(101+index)]
  def one(stage):
   a=[v for v in subset if v.get('stage')==stage];need(len(a)==1,'Missing/duplicate '+stage);return a[0]
  m=one('mapping');h=one('host_mapping');a=one('source_after')
  need(m.get('executor')==('0000:06:00.0' if index else '0000:01:00.0') and m.get('peer')==('0000:01:00.0' if index else '0000:06:00.0'),'GPU placement differs')
  need(m.get('domain_type')=='3' and m.get('direction')=='DMA_TO_DEVICE' and m.get('source_register')=='NV_PMC_BOOT_0' and m.get('offset')=='0' and m.get('bytes')=='4096','MMIO mapping scope differs')
  iova,physical,translated=[int(m[k],16) for k in ['iova','physical','translated']]
  need(iova and iova!=physical and physical==translated and not (iova&4095) and not (physical&4095),'MMIO mapping not translated correctly')
  need(h.get('valid')=='1' and int(h['physical'],16)==int(h['translated'],16) and int(h['iova'],16)>0,'Host mapping differs')
  expected_peer=0x197000a1 if index else 0xb76000a1
  need(int(m['expected'],16)==expected_peer and int(a['cpu_after'],16)==expected_peer and a.get('source_stable')=='1' and a.get('host_source_changed')=='0','Source control changed')
  results=[v for v in subset if v.get('stage')=='result']
  need(len(results)==6 and [v.get('seq') for v in results]==list(map(str,range(6))),'Six reads missing/reordered')
  peer_mask=0
  for seq,v in enumerate(results):
   ispeer=seq%3==1;expected=expected_peer if ispeer else 0x6975c23a^(index<<8)
   need(v.get('mode')==str(1+seq//3) and v.get('kind')==('peer_bar0' if ispeer else 'host_ram'),'Read operation differs')
   need(int(v['source_iova'],16)==(iova if ispeer else int(h['iova'],16)) and v.get('bytes')=='4','Read address differs')
   actual=int(v['actual'],16)
   need(int(v['expected'],16)==expected and int(v['sentinel'],16)==(~expected&0xffffffff) and v.get('match')==str(int(actual==expected)),'Data result inconsistent')
   need(v.get('guard_changed')=='0' and v.get('baseline_valid')=='1' and v.get('checked_words')=='1024' and v.get('class')=='c7b5' and int(v['launch'],16)==0x04003186 and v.get('p2p_channel')=='0' and v.get('privileged')=='1','Engine/guard controls differ')
   need(ispeer or actual==expected,'Host positive control failed')
   if ispeer and actual==expected:peer_mask|=1<<(seq//3)
  returns=[v for v in subset if v.get('stage')=='return' and v.get('operation')=='1'];need(len(returns)==1,'Execution return missing/duplicate')
  ret=returns[0]
  need(ret.get('status')=='0' and ret.get('flags')=='7' and ret.get('host_mask')=='2d' and int(ret['peer_mask'],16)==peer_mask and ret.get('completed_mask')=='3f' and ret.get('pending')=='0' and ret.get('dma_unmapped')=='1' and ret.get('last_phase')=='reads','DMA lifecycle incomplete')
  io=[fields(l) for l in lines if l.startswith('IOVA_IOCTL ') and fields(l).get('index')==str(index)]
  need(len(io)==1,'Client execution result absent');v=io[0]
  need(v.get('rv')=='0' and v.get('status')=='0' and v.get('flags')=='7' and v.get('domain')=='3' and v.get('host_mask')=='2d' and v.get('completed_mask')=='3f' and int(v['peer_mask'],16)==peer_mask and int(v['iova'],16)==iova and int(v['physical'],16)==physical and v.get('inputs_unchanged')=='1','Client/kernel results differ')
  out.append({'index':index,'host_controls_passed':4,'peer_reads_passed':peer_mask.bit_count() if hasattr(int,'bit_count') else bin(peer_mask).count('1'),'peer_pass_mask':peer_mask,'mmio_iova':hex(iova),'mmio_physical':hex(physical),'dma_mapping_unmapped':True,'results':results})
 need(len([v for v in rows if v.get('stage')=='result'])==12,'Unexpected extra GPU reads')
 return {'status':'complete_native_iova_mmio_read_only','protocol_complete':True,'executors':out,'translation_active_before_and_after':True,'peer_register_writes':False,'ordinary_peer_mappings':0,'host_controls_passed':8,'peer_reads_passed':sum(v['peer_reads_passed'] for v in out),'vm_data_disks_mounted':False,'P2P_solution_claimed':False,'scope':'Four read-only GPU BOOT_0 reads via translated IOVA, bracketed by eight RAM positive controls. No general VRAM P2P claim.'}
def validate_log(raw,ccfg,kernel=''):
 try:return complete(raw,ccfg,kernel)
 except (ValueError,KeyError,TypeError) as e:return {'status':'incomplete_preserved','protocol_complete':False,'error':str(e),'P2P_solution_claimed':False,'logs_are_partial_evidence':True}
