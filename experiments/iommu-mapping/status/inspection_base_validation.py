"""Qualify bounded USB4 reads separately from GPU data-transfer evidence."""
import re

def need(condition,message):
    if not condition: raise ValueError(message)

def complete(raw,ccfg,kernel):
    lines=raw.splitlines()
    need(lines.count('USB4_INSPECTION_BEGIN version=1 gpu_program_executed=0 explicit_register_writes=0')==1,'Inspection begin missing/duplicated')
    need(lines.count('USB4_INSPECTION_END protocol_complete=1 gpu_program_executed=0 explicit_register_writes=0')==1,'Inspection end missing/duplicated')
    need(lines.count('SCRIPT_RC=0')==1,'Inspection script did not complete')
    need('INVALID_' not in raw and 'WATCHDOG_REBOOT' not in raw+kernel,'Invalid/watchdog inspection')
    need(lines.count('USB4_INSPECTION_GPU_MODULES absent')==2,'NVIDIA module guards missing')
    need(lines.count('USB4_INSPECTION_DATA_DISKS unmounted')==1,'VM data disk guard missing')
    need('module_blacklist=nouveau,nvidia,nvidia_uvm,nvidia_drm,nvidia_modeset' in raw,'GPU blacklist missing')
    need(kernel.strip() and 'NVRM:' not in kernel and 'nvidia-uvm: Loaded' not in kernel,'Unexpected GPU driver or missing kernel log')
    for bdf,(_,value) in ccfg.items():
        values=re.findall(r'^(?:PEG_CCFG|TCSS_CCFG) '+re.escape(bdf[5:])+r' ([0-9a-f]+)$',raw,re.M)
        need(len(values)==2 and all(int(v,16)==value for v in values),'Firmware CCFG changed/incomplete')
    devices=re.findall(r'^TB_DEVICE_BEGIN name=(\S+)$',raw,re.M)
    need(devices==re.findall(r'^TB_DEVICE_END name=(\S+)$',raw,re.M) and len(set(devices))==len(devices),'Device inventory incomplete/duplicated')
    count=re.findall(r'^TB_DEVICE_COUNT=(\d+)$',raw,re.M)
    need(len(count)==1 and int(count[0])==len(devices),'Device count differs')
    begin=re.findall(r'^TB_FILE_BEGIN path=(\S+)$',raw,re.M)
    end=re.findall(r'^TB_FILE_END path=(\S+) rc=(\d+)$',raw,re.M)
    need(begin==[p for p,rc in end] and len(set(begin))==len(begin) and len(begin)<=64,'Debug file acquisition incomplete/duplicated')
    need(all(re.match(r'^/sys/kernel/debug/thunderbolt/[A-Za-z0-9_.:-]+/(?:port[0-9]+/)?(?:regs|path|counters)$',p) for p in begin),'Unexpected debugfs interface')
    counts=re.findall(r'^TB_FILE_COUNT=(\d+)$',raw,re.M)
    limited='TB_FILE_LIMIT_REACHED=64' in lines
    need(len(counts)==1 and int(counts[0])==len(begin)+int(limited),'Debug count differs')
    states=re.findall(r'^TB_DEBUGFS (present|absent)$',raw,re.M)
    need(len(states)==1 and (states[0]=='present' or not begin),'Debugfs state differs')
    begin_line=lines.index('USB4_INSPECTION_BEGIN version=1 gpu_program_executed=0 explicit_register_writes=0')
    end_line=lines.index('USB4_INSPECTION_END protocol_complete=1 gpu_program_executed=0 explicit_register_writes=0')
    need(begin_line<end_line<lines.index('SCRIPT_RC=0'),'Inspection markers reordered')
    for p,rc in end:
        need(begin_line<lines.index('TB_FILE_BEGIN path='+p)<lines.index('TB_FILE_END path='+p+' rc='+rc)<end_line,'Debug file markers reordered')
    return {'status':'complete_bounded_inspection','protocol_complete':True,'devices':devices,'debugfs_present':states[0]=='present',
            'debug_files':len(begin),'counter_files':[p for p in begin if p.endswith('/counters')],
            'read_errors':[{'path':p,'rc':int(rc)} for p,rc in end if int(rc)],
            'read_limit_reached':limited,'inaccessible_register_text':('<not accessible>' in raw or '<capability read failed>' in raw),
            'gpu_program_executed':False,'nvidia_modules_loaded':False,'vm_data_disks_mounted':False,
            'P2P_solution_claimed':False,'traffic_path_proven':False,'comparisons':0}

def validate_log(raw,ccfg,kernel=''):
    try:return complete(raw,ccfg,kernel)
    except (ValueError,KeyError,TypeError) as e:
        return {'status':'incomplete_preserved','protocol_complete':False,'inspection_error':str(e),
                'P2P_solution_claimed':False,'traffic_path_proven':False,'logs_are_partial_evidence':True,'comparisons':0}
