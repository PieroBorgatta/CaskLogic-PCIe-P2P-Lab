"""Separate counter calibration from GPU P2P success; preserve partial evidence."""
import re

POINTS=['HOST_PCIE','HOST_LANE','DOCK_LANE','DOCK_PCIE']
def need(ok,why):
    if not ok:raise ValueError(why)
def fields(line):return dict(re.findall(r'(\w+)=(\S+)',line))
def complete(raw,ccfg,kernel):
    lines=raw.splitlines()
    markers=['USB4_COUNTER_RUN_BEGIN version=1 gpu_program_executed=0',
             'USB4_COUNTER_DATA_DISKS unmounted','COUNTER_MODULE_LOAD_RC=0',
             'TB_COUNTER_PROBE_BEGIN version=1 gpu_program_executed=0 userspace_register_writes=0',
             'TB_COUNTER_PROBE_END protocol_complete=1 positive_controls=2 idle_controls=1 points=4',
             'COUNTER_CONTROL_RC=0','COUNTER_MODULE_UNLOADED=1',
             'TB_COUNTER_RESTORED original_module=1 four_paths=1',
             'USB4_COUNTER_RUN_END original_module_restored=1 data_disks_unmounted=1 gpu_program_executed=0',
             'SCRIPT_RC=0']
    for m in markers:need(lines.count(m)==1,'Missing/duplicate marker: '+m)
    need([lines.index(m) for m in markers]==sorted(lines.index(m) for m in markers),'Reordered counter lifecycle')
    need(lines.count('USB4_INSPECTION_GPU_MODULES absent')==2,'GPU module guards missing')
    need('module_blacklist=nouveau,nvidia,nvidia_uvm,nvidia_drm,nvidia_modeset' in raw,'GPU blacklist missing')
    need('TB_COUNTER_ABORT' not in raw and 'WATCHDOG_REBOOT' not in raw+kernel and 'INVALID_' not in raw,'Aborted/invalid run')
    need(kernel.strip() and 'NVRM:' not in kernel and 'nvidia-uvm: Loaded' not in kernel,'Missing kernel log or NVIDIA loaded')
    for bdf,(_,wanted) in ccfg.items():
        vals=re.findall(r'^(?:PEG_CCFG|TCSS_CCFG) '+re.escape(bdf[5:])+r' ([0-9a-f]+)$',raw,re.M)
        need(len(vals)==2 and all(int(v,16)==wanted for v in vals),'Firmware CCFG changed/missing')
    plans=[fields(x) for x in kernel.splitlines() if 'CASKTB_COUNTER_PLAN ' in x]
    expected={('0','8','0'),('0','1','1'),('1','1','1'),('1','3','0')}
    need(len(plans)==4 and {(x.get('route'),x.get('port'),x.get('index')) for x in plans}==expected,'Counter assignment topology differs')
    need(all(x.get('hop')=='8' and x.get('path_inactive')=='1' and x.get('standard_activation')=='1' for x in plans),'Counters not assigned before activation')
    path=[fields(x) for x in lines if x.startswith('TB_COUNTER_PATH ')]
    need(len(path)==12,'Path validation count differs')
    need([x.get('point') for x in path]==POINTS*3 and
         [x.get('enabled') for x in path]==['1']*8+['0']*4 and
         [x.get('index') for x in path]==['0','1','1','0']*3 and
         all(x.get('valid')=='1' for x in path),'Path/restore validation differs')
    samples=[fields(x) for x in lines if x.startswith('TB_COUNTER_SAMPLE ')]
    need(len(samples)==12,'Counter snapshots missing/duplicate')
    need([x.get('point') for x in samples]==POINTS*3,'Counter sample ordering differs')
    for k,x in enumerate(samples):
        group=k//4;n=[0,64,1024][group]
        need(x.get('reads')==str(n) and x.get('stage')==('IDLE' if not n else 'CPU_CONFIG_POSITIVE'),'Positive control identity differs')
        b,a,d=[int(x[z]) for z in ['before','after','delta']]
        db,da,dd=[int(x[z]) for z in ['dropped_before','dropped_after','dropped_delta']]
        need(0<=b<=a<2**64-1 and a-b==d,'Counter reset/saturation/incorrect delta')
        need(0<=db<=da<2**32-1 and da-db==dd==0,'Dropped packets/reset/saturation')
        need(not n or d>=n,'Positive control did not register traffic')
    return {'status':'counter_positive_controls_passed','protocol_complete':True,
            'gpu_program_executed':False,'nvidia_modules_loaded':False,'vm_data_disks_mounted':False,
            'original_module_restored':True,'points':POINTS,'positive_controls':[64,1024],
            'counter_samples':samples,'P2P_solution_claimed':False,'peer_traffic_measured':False,'comparisons':0}

def validate_log(raw,ccfg,kernel=''):
    try:return complete(raw,ccfg,kernel)
    except (ValueError,KeyError,TypeError) as e:
        return {'status':'incomplete_preserved','protocol_complete':False,'counter_error':str(e),
                'P2P_solution_claimed':False,'peer_traffic_measured':False,'comparisons':0,
                'logs_are_partial_evidence':True}
