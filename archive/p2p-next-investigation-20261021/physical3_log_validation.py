"""Validatore puro PHYS: non apre dispositivi e non modifica file.

La raccolta deve conservare anche avvii parziali: la qualifica completa richiede
ogni riscontro; un errore del protocollo diventa esplicitamente incomplete.
"""
import re


def fields(line):
    return dict(re.findall(r'([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)',line))


def require(ok,message):
    if not ok: raise ValueError(message)


def complete(raw,ccfg):
    lines=raw.splitlines()
    def rows(prefix): return [fields(x) for x in lines if x.startswith(prefix+' ')]
    end=rows('PHYS_PROGRAM_END');require(len(end)==1,'Chiusura programma mancante/duplicata')
    end=end[0]
    require(end.get('protocol_complete')=='1' and end.get('p2p_comparisons')=='4' and
            end.get('physical_completed')=='2' and end.get('calibrations')=='4' and
            end.get('direct_route_proven')=='0','Protocollo non completo')
    fail=int(end['p2p_failures']);calfail=int(end['calibration_failures']);qualified=int(end['qualified_windows'])
    require(0<=fail<=4 and 0<=calfail<=4 and 0<=qualified<=4,'Conteggio fuori intervallo')
    expected_rc=6 if qualified!=4 or calfail else (5 if fail else 0)
    require(int(end['rc'])==expected_rc,'RC incoerente')
    for marker in ['NATIVE_TEST_RC='+str(expected_rc),'SCRIPT_RC='+str(expected_rc),'PROBE_COMPLETED']:
        require(lines.count(marker)==1,'Marker logger mancante/duplicato: '+marker)
    require(not rows('PHYS_CE_RETAINED') and not rows('PHYS_ABORT') and
            not any('WATCHDOG_REBOOT' in x for x in lines),'Conclusione completa con errore/watchdog')
    data=rows('PHYS_DATA_RESULT');cases=rows('PHYS_CASE')
    require(len(data)==len(cases)==4,'Casi P2P mancanti/duplicati')
    order=[('SM','0','1'),('PHYSICAL_CE','0','1'),('SM','1','0'),('PHYSICAL_CE','1','0')]
    full=rows('FULL_COMPARE')
    owner=[x for x in full if x.get('stage') in ('source_initialized','destination_poisoned')]
    require(len(owner)==8 and all(x.get('valid')=='1' and x.get('checked_words')=='1' and
            x.get('mismatches')=='0' for x in owner),'Controlli proprietari P2P mancanti/falliti')
    peers=[x for x in full if x.get('stage')=='peer_payload']
    require(len(peers)==4,'Confronti payload mancanti')
    for n,(row,case,peer,wanted) in enumerate(zip(data,cases,peers,order),1):
        require(row.get('id')==case.get('id')==str(n),'ID P2P errato')
        require((row.get('engine'),row.get('s'),row.get('d'))==wanted and
                (case.get('engine'),case.get('s'),case.get('d'))==wanted,'Ordine P2P errato')
        require(case.get('executor')==wanted[1] and case.get('bytes')=='4' and
                case.get('allocations_unchanged')=='1','Contesto caso errato')
        require(row.get('bytes')=='4' and row.get('checked_words')=='1' and
                row.get('mismatches') in ('0','1') and row.get('valid') in ('0','1') and
                (row['mismatches']=='0')==(row['valid']=='1'),'Confronto P2P invalido')
        require(row.get('physical_ioctl_completed')==str(int(wanted[0]=='PHYSICAL_CE')) and
                row.get('direct_route_proven')=='0','Scope P2P errato')
        require(peer.get('iteration')==str(n) and peer.get('s')==wanted[1] and peer.get('d')==wanted[2] and
                peer.get('bytes')=='4' and peer.get('checked_words')=='1' and
                peer.get('valid')==row['valid'] and peer.get('mismatches')==row['mismatches'],'Full compare diverso')
    require(sum(x['valid']=='0' for x in data)==fail,'Totale P2P diverso')
    ioctls=rows('PHYS_IOCTL_RESULT');require(len(ioctls)==2,'Riscontri ioctl mancanti/duplicati')
    require(len({x.get('request') for x in ioctls})==2,'Request ioctl duplicata')
    for row,case in zip(ioctls,[cases[1],cases[3]]):
        klass=int(row['ce_class'],16);launch=int(row['launch'],16)
        require(klass in (0xc6b5,0xc7b5) and launch==(0x3186 if klass==0xc6b5 else 0x04003186),'Metodi CE inattesi')
        require(row.get('rv')=='0' and int(row['rmStatus'],16)==0 and int(row['flags'],16)==0x77 and
                row.get('bytes')=='4' and row.get('inputs_unchanged')=='1' and
                int(row['source_mode'],16)==0 and int(row['destination_mode'],16)==1 and
                int(row['source_offset'],16)==int(row['destination_offset'],16)==0 and
                int(row['source_handle'],16)>0 and int(row['destination_handle'],16)>0,'Ioctl non qualificato')
        require(int(row['src'],16)==int(case['src'],16) and int(row['dst'],16)==int(case['dst'],16),
                'Indirizzi ioctl/caso diversi')
        require(int(row['source_pa'],16)%4==int(row['destination_pa'],16)%4==0,'PA disallineato')
    bars=rows('PHYS_BAR1');require(len(bars)==2 and [x.get('owner') for x in bars]==['1','0'] and
                                all(x.get('valid')=='1' for x in bars),'BAR1 target non verificati')
    for bar,ioctl in zip(bars,ioctls):
        start=int(bar['start'],16);endbar=int(bar['end'],16);pa=int(bar['destination_physical'],16)
        require(int(bar['flags'],16)&0x200 and start<=pa<=endbar-3 and
                pa==int(ioctl['destination_pa'],16),'Intervallo BAR1 incoerente')
    cal=rows('CALIBRATION_DATA_RESULT');wins=rows('CALIBRATION_WINDOW');samplers=rows('NVML_SAMPLER_END')
    calcases=rows('CALIBRATION_CASE')
    require(len(cal)==len(wins)==len(samplers)==len(calcases)==4,'Calibrazioni incomplete/duplicate')
    calorder=[('HOST_TO_DEVICE','0'),('DEVICE_TO_HOST','0'),('HOST_TO_DEVICE','1'),('DEVICE_TO_HOST','1')]
    init=[x for x in full if x.get('stage')=='calibration_owner_initialized']
    require(len(init)==4 and all(x.get('valid')=='1' and x.get('mismatches')=='0' and
                                x.get('checked_words')=='262144' for x in init),'Init calibrazione invalida')
    for n,(row,win,sampler,case,wanted) in enumerate(zip(cal,wins,samplers,calcases,calorder),1):
        require(row.get('id')==win.get('id')==case.get('id')==sampler.get('phase')==str(n),'ID calibrazione errato')
        require(all((x.get('operation'),x.get('owner'))==wanted for x in (row,win,case)),'Ordine calibrazione errato')
        require(case.get('owner_only')=='1' and case.get('peer_access')=='NONE' and
                all(x.get('p2p')=='0' for x in (row,win,case)),'Calibrazione scambiata per P2P')
        require(row.get('bytes')==case.get('bytes')=='1048576' and
                row.get('valid') in ('0','1') and row.get('sampling_valid') in ('0','1') and
                row.get('duration_valid') in ('0','1') and row.get('counter_sensitivity_proven')=='0','Risultato calibrazione errato')
        h=int(row['host_mismatches']);d=int(row['owner_mismatches'])
        require(0<=h<=262144 and 0<=d<=262144 and (row['valid']=='1')==(h==0 and d==0),'Mismatch calibrazione incoerenti')
        for stage,value in [('calibration_host_payload',h),('calibration_owner_payload',d)]:
            matches=[x for x in full if x.get('stage')==stage and x.get('iteration')==str(n)]
            require(len(matches)==1 and matches[0].get('owner')==wanted[1] and
                    matches[0].get('checked_words')=='262144' and int(matches[0]['mismatches'])==value and
                    (matches[0].get('valid')=='1')==(value==0),'Confronto calibrazione mancante/incoerente')
        begin=int(win['begin_ns']);finish=int(win['end_ns']);joined=int(win['sampler_joined_ns'])
        require(begin<finish<=joined and int(win['duration_ns'])==finish-begin,'Tempi calibrazione invalidi')
        batches=int(win['batches']);require(1<=batches<=4096 and int(win['submitted_host_payload_bytes'])==batches*64*1048576,'Byte host incoerenti')
        duration=1200000000<=finish-begin<=5000000000 and win.get('budget_exhausted')=='0'
        require((row['duration_valid']=='1')==duration and sampler.get('valid')==row['sampling_valid'],'Qualifica calibrazione incoerente')
    require(sum(x['valid']=='0' for x in cal)==calfail and
            sum(x['sampling_valid']=='1' and x['duration_valid']=='1' for x in cal)==qualified,'Totali calibrazione diversi')
    for uuid in ['00000000000000000000000000000001','00000000000000000000000000000002']:
        require(any(x.get('uuid')==uuid and x.get('valid')=='1' for x in rows('PHYS_GPU')),'Identita GPU mancante')
    for bdf,(_,value) in ccfg.items():
        values=re.findall(r'^(?:PEG_CCFG|TCSS_CCFG) '+re.escape(bdf[5:])+r' ([0-9a-f]+)$',raw,re.M)
        require(len(values)==3 and all(int(v,16)==value for v in values),'CCFG non originale nel log')
    return {'status':'complete_verified','protocol_complete':True,'program_rc':expected_rc,
            'comparisons':4,'failures':fail,'physical_completed':2,'calibrations':4,
            'calibration_failures':calfail,'qualified_windows':qualified,
            'data_all_comparisons_pass':fail==0,'P2P_solution_claimed':False,'direct_route_proven':False,
            'CE_method_submission_reported':True,'counters_are_aggregate':True}


def validate_log(raw,ccfg,kernel=''):
    try:
        require('WATCHDOG_REBOOT' not in kernel and 'objects_retained_until_reboot=1' not in kernel,
                'Kernel watchdog/retained: conservare risultato parziale')
        return complete(raw,ccfg)
    except (ValueError,KeyError,TypeError,OverflowError) as error:
        ends=[fields(x) for x in raw.splitlines() if x.startswith('PHYS_PROGRAM_END ')]
        return {'status':'incomplete_preserved','protocol_complete':False,'qualification_error':str(error),
                'program_rc':None,'terminal_records':ends,'comparisons':None,'failures':None,
                'data_all_comparisons_pass':False,'P2P_solution_claimed':False,'direct_route_proven':False,
                'watchdog_observed':'WATCHDOG_REBOOT' in raw or 'WATCHDOG_REBOOT' in kernel,
                'retained_observed':'PHYS_CE_RETAINED ' in raw or 'objects_retained_until_reboot=1' in kernel,
                'logs_are_partial_evidence':True}
