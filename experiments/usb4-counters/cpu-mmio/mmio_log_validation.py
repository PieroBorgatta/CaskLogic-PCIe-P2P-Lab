"""Qualify completed MMIO counter measurements without assuming all counters work."""
import re
POINTS=['HOST_PCIE','HOST_LANE','DOCK_LANE','DOCK_PCIE']
def need(ok,why):
    if not ok:raise ValueError(why)
def fields(line):return dict(re.findall(r'(\w+)=(\S+)',line))
def complete(raw,ccfg,kernel):
    lines=raw.splitlines()
    markers=['USB4_COUNTER_RUN_BEGIN version=1 gpu_program_executed=0',
       'USB4_COUNTER_DATA_DISKS unmounted','COUNTER_MODULE_LOAD_RC=0',
       'TB_MMIO_PROBE_BEGIN version=1 gpu_program_executed=0 mmio_writes=0 command_mask=0002',
       'TB_MMIO_COMMAND_BEGIN original=0000 requested=0002 bus_master_enable=0',
       'TB_MMIO_COMMAND_ACTIVE observed=0002',
       'TB_MMIO_COMMAND_RESTORED observed=0000 bus_master_enable=0',
       'TB_MMIO_PROBE_END protocol_complete=1 positive_controls=2 idle_controls=2 points=4 source_reads=16448 command_restored=1',
       'COUNTER_CONTROL_RC=0','COUNTER_MODULE_UNLOADED=1',
       'TB_COUNTER_RESTORED original_module=1 four_paths=1 command_original=1',
       'USB4_COUNTER_RUN_END original_module_restored=1 data_disks_unmounted=1 gpu_program_executed=0','SCRIPT_RC=0']
    for m in markers:need(lines.count(m)==1,'Missing/duplicate marker: '+m)
    need([lines.index(m) for m in markers]==sorted(lines.index(m) for m in markers),'Reordered lifecycle')
    need(lines.count('USB4_INSPECTION_GPU_MODULES absent')==2,'GPU module guards missing')
    need('module_blacklist=nouveau,nvidia,nvidia_uvm,nvidia_drm,nvidia_modeset' in raw,'GPU blacklist missing')
    need('TB_MMIO_ABORT' not in raw and 'TB_MMIO_RESTORE_FAILED' not in raw and 'WATCHDOG_REBOOT' not in raw+kernel,'Aborted run')
    need(kernel.strip() and 'NVRM:' not in kernel and 'nvidia-uvm: Loaded' not in kernel,'Missing kernel log/NVIDIA present')
    for bdf,(_,wanted) in ccfg.items():
        vals=re.findall(r'^(?:PEG_CCFG|TCSS_CCFG) '+re.escape(bdf[5:])+r' ([0-9a-f]+)$',raw,re.M)
        need(len(vals)==2 and all(int(v,16)==wanted for v in vals),'Firmware CCFG changed/missing')
    plans=[fields(x) for x in kernel.splitlines() if 'CASKTB_COUNTER_PLAN ' in x]
    need(len(plans)==4 and {(x.get('route'),x.get('port'),x.get('index')) for x in plans}=={('0','8','0'),('0','1','1'),('1','1','1'),('1','3','0')},'Counter assignment topology differs')
    need(all(x.get('hop')=='8' and x.get('path_inactive')=='1' and x.get('standard_activation')=='1' for x in plans),'Live counter changes')
    paths=[fields(x) for x in lines if x.startswith('TB_COUNTER_PATH ')]
    need(len(paths)==12 and [x.get('point') for x in paths]==POINTS*3 and
         [x.get('enabled') for x in paths]==['1']*8+['0']*4 and
         [x.get('index') for x in paths]==['0','1','1','0']*3 and all(x.get('valid')=='1' for x in paths),'Paths not verified/restored')
    data=[fields(x) for x in lines if x.startswith('TB_MMIO_DATA ')]
    need(len(data)==4 and [x.get('group') for x in data]==['1','2','3','4'] and
         [x.get('reads') for x in data]==['0','64','16384','0'] and
         all(x.get('reads')==x.get('checked') and x.get('expected')=='b76000a1' and x.get('valid')=='1' for x in data),'MMIO data validation incomplete')
    samples=[fields(x) for x in lines if x.startswith('TB_MMIO_SAMPLE ')]
    need(len(samples)==16 and [x.get('point') for x in samples]==POINTS*4,'Counter samples incomplete')
    previous={};dropped=[]
    for k,x in enumerate(samples):
        group=k//4+1;n=[0,64,16384,0][group-1];point=x['point']
        need(x.get('group')==str(group) and x.get('reads')==str(n),'Sample identity differs')
        b,a,d=[int(x[z]) for z in ['before','after','delta']]
        db,da,dd=[int(x[z]) for z in ['dropped_before','dropped_after','dropped_delta']]
        bt,at,dt=[int(x[z]) for z in ['before_ns','after_ns','elapsed_ns']]
        need(0<=b<=a<2**64-1 and a-b==d and 0<=db<=da<2**32-1 and da-db==dd,'Reset/saturation/incorrect count')
        need(0<bt<at and at-bt==dt,'Invalid measurement interval')
        if point in previous:
            pa,pda,pt=previous[point];need(b>=pa and db>=pda and bt>=pt,'Counter reset between windows')
        previous[point]=(a,da,at)
        if dd:dropped.append({'group':group,'point':point,'delta':dd})
    unresponsive=[p for p in POINTS if all(int(x['delta'])==0 for x in samples if x['point']==p and int(x['reads']))]
    return {'status':'complete_cpu_mmio_counter_measurement','protocol_complete':True,
            'gpu_program_executed':False,'nvidia_modules_loaded':False,'vm_data_disks_mounted':False,
            'original_module_restored':True,'original_pci_command_restored':True,
            'positive_controls':[64,16384],'source_reads_in_measurement_windows':16448,
            'counter_samples':samples,'unresponsive_points':unresponsive,'drops':dropped,
            'all_counters_calibrated':False,'background_attribution_required':True,
            'P2P_solution_claimed':False,'peer_traffic_measured':False,'comparisons':0}
def validate_log(raw,ccfg,kernel=''):
    try:return complete(raw,ccfg,kernel)
    except (ValueError,KeyError,TypeError) as e:
        return {'status':'incomplete_preserved','protocol_complete':False,'counter_error':str(e),
                'P2P_solution_claimed':False,'peer_traffic_measured':False,'comparisons':0,'logs_are_partial_evidence':True}
