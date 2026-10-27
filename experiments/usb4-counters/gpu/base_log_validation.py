import re
def need(ok,message):
    if not ok:raise ValueError(message)
def fields(line):return dict(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)",line))

def validate_log(raw, ccfg):
    """Esito dati5 e dati0 entrambi raccoglibili; validita protocollo separata."""
    end=[fields(x) for x in raw.splitlines() if x.startswith('CE_PROGRAM_END ')]
    need(len(end)==1,'Chiusura programma mancante/duplicata')
    end=end[0]
    need(end.get('protocol_complete')=='1' and end.get('comparisons')=='36','Protocollo non concluso')
    rc=end.get('rc');need(rc in ('0','5'),'RC programma non classificato: '+str(rc))
    fail=int(end['failures']);need(0<=fail<=36 and (rc=='0')==(fail==0),'RC e fallimenti incoerenti')
    for marker in ['NATIVE_TEST_RC='+rc,'SCRIPT_RC='+rc,'PROBE_COMPLETED']:
        need(raw.splitlines().count(marker)==1,'Marker logger non valido: '+marker)
    need(end.get('trace_complete')=='1' and end.get('ce_observed')=='18' and
              end.get('sm_observed')=='18' and end.get('dropped')=='0' and end.get('trace_errors')=='0',
              'Traccia incompleta: conservare area e richiedere raccolta diagnostica dedicata')
    results=[fields(x) for x in raw.splitlines() if x.startswith('CE_DATA_RESULT ')]
    need(len(results)==36 and [int(x['id']) for x in results]==list(range(1,37)),'Risultati incompleti/duplicati')
    need(sum(x['valid']=='0' for x in results)==fail and all(x['valid'] in ('0','1') for x in results),'Conteggio dati incoerente')
    need([x['mode'] for x in results]==['PUSH','PULL','PUSH']*12,'Ordine modalita inatteso')
    for uid in ['00000000000000000000000000000001','00000000000000000000000000000002']:
        need(any(x.startswith('CE_GPU ') and 'uuid='+uid in x and 'valid=1' in x for x in raw.splitlines()),'Identita GPU assente')
    for bdf,(_,wanted) in ccfg.items():
        vals=re.findall(r'^(?:PEG_CCFG|TCSS_CCFG) '+re.escape(bdf[5:])+r' ([0-9a-f]+)$',raw,re.M)
        need(len(vals)==4 and all(int(v,16)==wanted for v in vals),'CCFG nel log non originale')
    return {'program_rc':int(rc),'failures':fail,'comparisons':36,'trace_complete':True,
            'data_all_comparisons_pass':fail==0,'P2P_solution_claimed':False,'direct_route_proven':False}
