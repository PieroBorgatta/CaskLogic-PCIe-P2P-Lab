"""Qualifica pura, Python 3.6: conserva l'evidenza incompleta senza dispositivi.

Questi riscontri documentano il protocollo e la submission software; non sono
una cattura PCIe, una prova di supporto vendor o una correzione P2P.
"""
import re

BDFS = ('0000:01:00.0', '0000:06:00.0')
SIZE = 8 * 1024 * 1024
STEPS = ('SM_PUSH_BEFORE', 'PHYS_PUSH_CONTROL', 'PHYS_PULL_NC',
         'PHYS_PULL_COH', 'SM_PULL', 'SM_PUSH_AFTER')


def fields(line):
    pairs = re.findall(r'([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)', line)
    require(len(dict(pairs)) == len(pairs), 'Chiave log duplicata')
    return dict(pairs)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def number(row, key, base=10):
    return int(row[key], base)


def equal(row, **values):
    for key, value in values.items():
        require(row.get(key) == str(value), 'Campo {}: {} != {}'.format(key, row.get(key), value))


def pattern(seed):
    x = seed & 0xffffffff
    x ^= x >> 16
    x = (x * 0x7feb352d) & 0xffffffff
    x ^= x >> 15
    x = (x * 0x846ca68b) & 0xffffffff
    return (x ^ (x >> 16)) & 0xffffffff


def spec(case_id):
    step = (case_id - 1) % 6
    executor = 1 if case_id <= 6 else 0
    pull = step in (2, 3, 4)
    seed = (0x4287a1c9 ^ (0x13579bdf * (executor + 1)) ^
            ((case_id * 0x9e3779b9) & 0xffffffff)) & 0xffffffff
    return dict(id=case_id, group=(case_id - 1) // 6 + 1, step=STEPS[step],
                executor=executor, s=1-executor if pull else executor,
                d=executor if pull else 1-executor, mode='PULL' if pull else 'PUSH',
                engine='UVM_PHYSICAL_CE' if step in (1, 2, 3) else 'SM',
                source_mode=2 if step == 2 else 1 if step == 3 else 0,
                destination_mode=2 if step == 1 else 0, seed=seed)


class Records:
    def __init__(self, text, kernel=False):
        self.rows = []
        for index, line in enumerate(text.splitlines()):
            if kernel:
                pos = line.find('CASKPHYS ')
                if pos < 0:
                    continue
                line = line[pos:]
            parts = line.split(' ', 1)
            if len(parts) == 2 and (parts[0].startswith('PHYS_') or
                                    parts[0] in ('CE_ALLOCATION', 'CE_ACCESS', 'CE_GPU', 'CASKPHYS')):
                self.rows.append((index, parts[0], fields(parts[1])))

    def all(self, prefix):
        return [(i, r) for i, p, r in self.rows if p == prefix]

    def one(self, prefix, **wanted):
        found = [(i, r) for i, p, r in self.rows if p == prefix and
                 all(r.get(k) == str(v) for k, v in wanted.items())]
        require(len(found) == 1, 'Record {} {} mancante/duplicato'.format(prefix, wanted))
        return found[0]


def qualify_kernel(kernel, cases, ioctls, allocations):
    log = Records(kernel, kernel=True)
    all_rows = log.all('CASKPHYS')
    methods = [(i, r) for i, r in all_rows if r.get('stage') == 'methods']
    require(len(methods) == 6, 'Sei submission kernel richieste')
    require([r['request'] for _, r in methods] == [r['request'] for r in ioctls], 'Ordine richieste kernel diverso')
    for c, out in zip(cases, ioctls):
        req = c['request']; pull = c['mode'] == 'PULL'
        request_rows = [r for _, r in all_rows if r.get('request') == req]
        for stage, count in [('map_lookup',3),('query_result',2),('classification',1),('methods',1),('dma_range',1),('return',1)]:
            require(sum(r.get('stage') == stage for r in request_rows) == count, 'Conteggio kernel '+stage)
        executor = number(c, 'executor'); src = number(c, 's'); dst = number(c, 'd')
        def one(stage, **kw):
            return log.one('CASKPHYS', request=req, stage=stage, **kw)
        idx, method = one('methods')
        equal(method, transfer=c['mode'], executor=BDFS[executor], bytes=4,
              p2p=1, privileged=1, no_virtual_fallback=1)
        require(bool(method.get('channel')), 'Canale kernel assente')
        for a, b in [('src_va', 'src'), ('dst_va', 'dst'), ('src_mem', 'source_handle'),
                     ('dst_mem', 'destination_handle'), ('src_off', 'source_offset'),
                     ('dst_off', 'destination_offset'), ('src_phys', 'source_pa'),
                     ('dst_phys', 'destination_pa'), ('class', 'ce_class'),
                     ('src_mode', 'source_mode'), ('dst_mode', 'destination_mode'), ('launch', 'launch')]:
            require(number(method, a, 16) == number(out, b, 16), 'Join metodo/ioctl '+a)
        ci, classification = one('classification')
        equal(classification, executor=BDFS[executor], transfer=c['mode'], stock_hal_unchanged=1,
              vendor_peer_read_support_established=0)
        for a, b in [('src_is_peer', 'source_is_peer'), ('dst_is_peer', 'destination_is_peer'),
                     ('stock_rejects_peer_source', 'stock_rejects_peer_source')]:
            require(classification[a] == out[b], 'Classificatore kernel/ioctl diverso')
        di, dma = one('dma_range')
        equal(dma, executor=BDFS[executor], remote=BDFS[1-executor], peer_reference_held=1)
        require(number(dma, 'dma_start', 16) == 0, 'DMA start inatteso')
        remote_pa = number(out, 'source_pa' if pull else 'destination_pa', 16)
        local_pa = number(out, 'destination_pa' if pull else 'source_pa', 16)
        base = number(dma, 'remote_bar1', 16); size = number(dma, 'remote_bar1_size', 16)
        require(base <= remote_pa <= base+size-4 and remote_pa <= number(dma, 'dma_limit', 16)-3 and
                local_pa <= number(dma, 'local_vram_limit', 16)-3, 'Limiti fisici kernel invalidi')
        ri, ret = one('return')
        equal(ret, operation=1, transfer=int(pull), status=0, flags='77', last_stage='submitted_wait')
        require(ci < idx < di < ri, 'Ordine classificazione/metodi/completamento kernel errato')
        roles = [('source_peer' if pull else 'source_local', executor, src, number(c, 'src', 16)),
                 ('destination_local' if pull else 'destination_peer', executor, dst, number(c, 'dst', 16)),
                 ('source_owner' if pull else 'destination_owner', 1-executor, 1-executor,
                  number(c, 'src' if pull else 'dst', 16))]
        identities = {}
        previous = -1
        for role, requester, owner, va in roles:
            li, lookup = one('map_lookup', role=role)
            equal(lookup, requester=BDFS[requester], owner=BDFS[owner], range_present=1)
            require(number(lookup, 'va', 16) == va, 'VA lookup errato')
            _, bounds = one('map_range', role=role)
            require(number(bounds, 'range_start', 16) == va and number(bounds, 'range_end', 16) == va+SIZE-1, 'Range allocazione kernel diverso')
            gi, guards = one('map_guards', role=role)
            equal(guards, bits='ffff', expected='ffff')
            for name in ('handle','rm_handle','map_gpu','handle_gpu','owner','vidmem','non_egm','recorded','descendant','kind','format','page','start','end','contains','permissions'):
                equal(guards, **{name: 1})
            mi, meta = one('map_meta', role=role)
            equal(meta, recorded=1, device_descendant=1, format=0, sysmem=0, egm=0)
            require(number(meta, 'kind', 16) in (0, 6) and number(meta, 'mapping_type') in (0, 1, 2) and
                    number(meta, 'page_size', 16) >= 4096 and number(meta, 'page_size', 16) % 4096 == 0,
                    'Formato mapping non qualificato')
            ii, identity = one('map_identity', role=role)
            equal(identity, map_gpu=BDFS[requester], handle_gpu=BDFS[requester], owning_gpu=BDFS[owner])
            identities[role] = (identity['user_client'], identity['user_object'])
            require(number(identity, 'user_client', 16) > 0 and number(identity, 'user_object', 16) > 0, 'Identita RM assente')
            geoi, geo = one('map_geometry', role=role)
            require(number(geo, 'node_start', 16) == number(geo, 'origin_start', 16) == va and
                    number(geo, 'node_end', 16) == number(geo, 'origin_end', 16) == va+SIZE-1 and
                    number(geo, 'map_offset', 16) == 0 and number(geo, 'allocation_size', 16) == SIZE,
                    'Geometria mapping cambiata')
            readyi, ready = one('map_ready', role=role)
            equal(ready, offset=0, tracker_status=0)
            require(previous < li < gi < mi < ii < geoi < readyi < ci, 'Ordine mapping kernel errato')
            previous = readyi
            if role.endswith('_owner'):
                continue
            endpoint = 'source' if role.startswith('source_') else 'destination'
            require(number(meta, 'rm_handle', 16) == number(out, endpoint+'_handle', 16), 'Handle query/ioctl diverso')
            qi, query = one('query_result', role=role)
            equal(query, mapping_type=2, offset=0, page='1000', bytes='1000', status=0, written=1, remaining=0)
            require(readyi < qi < ci and number(query, 'base', 16) == number(out, endpoint+'_pa', 16) and
                    number(query, 'base', 16) % 4096 == 0, 'Query PA non qualificata')
        remote_role = 'source_peer' if pull else 'destination_peer'
        owner_role = 'source_owner' if pull else 'destination_owner'
        require(identities[remote_role] == identities[owner_role], 'Oggetto peer/proprietario diverso')


def complete(raw, ccfg, kernel):
    log = Records(raw); lines = raw.splitlines()
    for token in ('WATCHDOG_REBOOT', 'PHYS_CE_RETAINED ', 'PHYS_ABORT ', 'CUDA_ERROR ', 'DRIVER_ERROR ', 'KMSG_MARKER_FAILED '):
        require(token not in raw, 'Errore/blocco '+token)
    require('objects_retained_until_reboot=1' not in kernel and 'WATCHDOG_REBOOT' not in kernel,
            'Kernel incompleto/retained')
    end_i, end = log.one('PHYS_PROGRAM_END')
    equal(end, protocol_complete=1, comparisons=12, physical_cases=6, physical_completed=6,
          sm_cases=6, source_preserved=12, initializations=24, allocations=2,
          direct_route_proven=0, vendor_supported_peer_read=0)
    fail = number(end, 'failures'); require(0 <= fail <= 12, 'Conteggio fallimenti invalido')
    rc = 5 if fail else 0; equal(end, rc=rc)
    for marker in ('NATIVE_TEST_RC='+str(rc), 'SCRIPT_RC='+str(rc), 'PROBE_COMPLETED'):
        require(lines.count(marker) == 1, 'Marker raccolta mancante/duplicato '+marker)
    protocol_i, protocol = log.one('PHYS_PROTOCOL')
    equal(protocol, name='physical-source-bracket-v1', allocations=2, comparisons=12, groups=2,
          physical_cases=6, bytes=4, cupti_used=0, vendor_supported_peer_read=0)
    request_base = number(protocol, 'request_base'); require(0 < request_base < 2**64-12, 'Base request invalida')
    allocs = log.all('CE_ALLOCATION'); require(len(allocs) == 2, 'Due sole allocazioni richieste')
    allocations = []
    for owner, (i, allocation) in enumerate(allocs):
        equal(allocation, owner=owner, mode='SHARED', role='shared', allocation_bytes=SIZE)
        va = number(allocation, 'va', 16); handle = number(allocation, 'handle', 16); gran = number(allocation, 'granularity')
        require(i < protocol_i and va > 0 and handle > 0 and gran > 0 and SIZE % gran == 0 and va % gran == 0,
                'Allocazione invalida')
        require(re.match(r'^[0-9a-f-]{36}$', allocation['nonce']) is not None, 'Nonce invalido')
        allocations.append((va, handle))
    require(allocations[0][0]+SIZE <= allocations[1][0] or allocations[1][0]+SIZE <= allocations[0][0], 'VAs sovrapposti')
    require(allocations[0][1] != allocations[1][1], 'Handle allocazione duplicato')
    require(allocs[0][1]['nonce'] != allocs[1][1]['nonce'], 'Nonce allocazione duplicato')
    identities = log.all('CE_GPU'); require(len(identities) == 26, 'Identita GPU incomplete')
    uuid = {}
    for _, r in identities:
        owner = number(r, 'index'); require(owner in (0, 1), 'Indice GPU invalido')
        equal(r, bdf=BDFS[owner], valid=1)
        require(re.match(r'^[0-9a-f]{32}$', r['uuid']) is not None, 'UUID non canonico')
        uuid.setdefault(owner, r['uuid']); require(uuid[owner] == r['uuid'], 'UUID cambiato')
    require(uuid[0] != uuid[1], 'GPU UUID duplicati')
    accesses = log.all('CE_ACCESS'); require(len(accesses) == 100, 'Controlli accesso incompleti')
    for _, r in accesses:
        owner = number(r, 'owner'); require(owner in (0, 1) and number(r, 'device') in (0, 1), 'Owner/device accesso')
        equal(r, mode='SHARED', role='shared', first=3, last=3, expected=3, allocation_type=1,
              location_type=1, location_id=owner, valid=1)
        require(number(r, 'va', 16) == allocations[owner][0] and number(r, 'last_va', 16) == allocations[owner][0]+SIZE-1,
                'Accesso VA cambiato')
    def access_window(stage, low, high):
        rows = [r for i, r in accesses if low < i < high]
        require(len(rows) == 4 and {(r['owner'], r['device']) for r in rows} == {('0','0'),('0','1'),('1','0'),('1','1')} and
                all(r['stage'] == stage for r in rows), 'Finestra accessi '+stage)
    access_window('created', -1, protocol_i)
    cases = log.all('PHYS_CASE'); data = log.all('PHYS_DATA_RESULT')
    for prefix, count in [('PHYS_CASE',12),('PHYS_DATA_RESULT',12),('PHYS_INIT',24),('PHYS_EXECUTOR',12),
                          ('PHYS_SOURCE_RECHECK',12),('PHYS_IOCTL_RESULT',6),('PHYS_SM_COMPLETE',6),
                          ('PHYS_BAR1',6),('PHYS_GROUP_BEGIN',2),('PHYS_GROUP_END',2),('PHYS_FREE',2)]:
        require(len(log.all(prefix)) == count, 'Conteggio '+prefix)
    selected_i, selected = log.one('PHYS_FD_SELECTED'); equal(selected, matches=1)
    require(allocs[-1][0] < selected_i < protocol_i, 'FD selezionato prima allocazioni')
    successful = [(i, r) for i, r in log.all('PHYS_FD_VALIDATION') if r.get('valid') == '1']
    require(len(successful) == 1, 'Validazione FD non unica')
    _, validated = successful[0]
    equal(validated, request=request_base, rv=0, rmStatus=0, flags=1, fd=selected['original'])
    previous = protocol_i; actual_failures = 0; physical_cases=[]; outputs=[]; classes=[]
    for case_id, (ci, c) in enumerate(cases, 1):
        window_start = previous
        wanted = spec(case_id); seed = wanted.pop('seed'); equal(c, **wanted)
        equal(c, bytes=4, allocations_unchanged=1)
        src = number(c,'s'); dst = number(c,'d'); executor = number(c,'executor')
        require(number(c,'seed',16) == seed, 'Seed non fresco/corretto')
        expected=pattern(seed); sentinel=expected ^ 0xffffffff
        require(number(c,'expected',16) == expected and number(c,'sentinel',16) == sentinel, 'Pattern/sentinel errato')
        for n, (va, handle) in enumerate(allocations):
            require(number(c,'buffer'+str(n),16) == va and number(c,'handle'+str(n),16) == handle, 'Allocazione persistente cambiata')
        require(number(c,'src',16) == allocations[src][0] and number(c,'dst',16) == allocations[dst][0], 'Direzione VA scambiata')
        access_window('before_case', previous, ci)
        gpurows = [r for i,r in identities if previous < i < ci]
        require([r['index'] for r in gpurows] == [str(src),str(dst)], 'Identita per caso mancanti/riordinate')
        ii, init_src=log.one('PHYS_INIT', id=case_id, role='source'); di, init_dst=log.one('PHYS_INIT', id=case_id, role='destination')
        for row, owner, value in [(init_src,src,expected),(init_dst,dst,sentinel)]:
            equal(row, owner=owner, bytes=4, valid=1)
            require(number(row,'va',16) == allocations[owner][0] and number(row,'expected',16) == number(row,'actual',16) == value, 'Init proprietario errata')
        ei, execution=log.one('PHYS_EXECUTOR',id=case_id); equal(execution, device=executor, valid=1)
        require(int(execution['current'],16)>0 and execution['current']==execution['stream_context'] and int(execution['stream'],16)>0, 'Contesto executor invalido')
        si, source=log.one('PHYS_SOURCE_RECHECK',id=case_id); equal(source,owner=src,bytes=4,valid=1)
        require(number(source,'va',16)==allocations[src][0] and number(source,'expected',16)==number(source,'actual',16)==expected, 'Sorgente cambiata dopo copia')
        ri,result=log.one('PHYS_DATA_RESULT',id=case_id)
        equal(result,engine=c['engine'],mode=c['mode'],executor=executor,s=src,d=dst,bytes=4,checked_words=1,direct_route_proven=0)
        require(number(result,'expected',16)==expected and number(result,'sentinel',16)==sentinel, 'Risultato pattern incoerente')
        actual=number(result,'actual',16);require(0<=actual<=0xffffffff,'Payload non quattro byte')
        passed=actual==expected; actual_failures+=not passed
        classification='expected' if passed else 'unchanged_sentinel' if actual==sentinel else 'all_ones' if actual==0xffffffff else 'unexpected'
        equal(result,valid=int(passed),mismatches=int(not passed),first_mismatch=-1 if passed else 0,last_mismatch=-1 if passed else 0,classification=classification)
        classes.append(classification)
        if c['engine']=='UVM_PHYSICAL_CE':
            req=request_base+case_id;equal(c,request=req)
            oi,out=log.one('PHYS_IOCTL_RESULT',request=req);equal(out,transfer=int(c['mode']=='PULL'),remote_mode=max(number(c,'source_mode'),number(c,'destination_mode')),bytes=4,rv=0,rmStatus=0,flags='77',inputs_unchanged=1)
            for key in ('src','dst'):
                require(number(out,key,16)==number(c,key,16),'Indirizzo ioctl errato')
            for key in ('source_mode','destination_mode'):
                require(number(out,key,16)==number(c,key),'Modo fisico errato')
            require(number(out,'ce_class',16)==0xc7b5 and number(out,'launch',16)==0x04003186,'Metodi C7B5 errati')
            for endpoint in ('source','destination'):
                require(number(out,endpoint+'_handle',16)>0 and number(out,endpoint+'_offset',16)==0 and number(out,endpoint+'_pa',16)>0 and number(out,endpoint+'_pa',16)%4096==0,'Indirizzo/handle fisico invalido')
            sip=number(out,'source_is_peer');dip=number(out,'destination_is_peer')
            require(sip in (0,1) and dip in (0,1) and (dip if c['mode']=='PULL' else sip)==0 and number(out,'stock_rejects_peer_source')==sip,'Classificatore errato')
            bars=[(i,r) for i,r in log.all('PHYS_BAR1') if oi<i<si];require(len(bars)==1,'BAR1 per richiesta mancante/duplicato')
            bi,bar=bars[0];role='source' if c['mode']=='PULL' else 'destination';equal(bar,owner=1-executor,role=role,valid=1)
            require(number(bar,'start',16)<=number(bar,'physical',16)<=number(bar,'end',16)-3 and number(bar,'flags',16)&0x200 and number(bar,'physical',16)==number(out,role+'_pa',16),'BAR1 non corrispondente')
            physical_cases.append(c);outputs.append(out)
        else:
            equal(c,request=0);oi,sm=log.one('PHYS_SM_COMPLETE',id=case_id)
            equal(sm,executor=executor,bytes=4,kernel='peer_push_kernel',blocks=1,threads=1,stream_synchronized=1)
            require(number(sm,'src',16)==number(c,'src',16) and number(sm,'dst',16)==number(c,'dst',16),'SM VA errato')
        require(previous<ci<ii<di<ei<oi<si<ri<end_i,'Ordine caso invalido')
        # Four access records are immediately associated with this result, before next case identities.
        nextcase=cases[case_id][0] if case_id<12 else end_i
        after=[i for i,r in accesses if ri<i<nextcase and r.get('stage')=='after_case']
        require(len(after)==4,'Accessi dopo caso mancanti')
        after_end=max(after);access_window('after_case',ri,after_end+1)
        previous=after_end
        if case_id in (1,7):
            gi,g=log.one('PHYS_GROUP_BEGIN',group=(case_id-1)//6+1)
            equal(g,executor=executor,first_case=case_id)
            require(window_start<gi<ci,'Inizio gruppo riordinato')
            if case_id == 7:
                previous_group_end, _ = log.one('PHYS_GROUP_END', group=1)
                require(previous_group_end < gi, 'Gruppi sovrapposti')
        if case_id in (6,12):
            gi,g=log.one('PHYS_GROUP_END',group=case_id//6);equal(g,last_case=case_id)
            require(after_end<gi<(cases[case_id][0] if case_id<12 else end_i),'Fine gruppo riordinato')
    require(actual_failures==fail,'Totale mismatch incoerente')
    for owner,(i,row) in enumerate(log.all('PHYS_FREE')):
        equal(row,owner=owner,valid=1)
        require(previous<i<end_i and number(row,'va',16)==allocations[owner][0] and number(row,'handle',16)==allocations[owner][1],'Rilascio allocazione precoce/diverso')
    for bdf, (_,value) in ccfg.items():
        values=re.findall(r'^(?:PEG_CCFG|TCSS_CCFG) '+re.escape(bdf[5:])+r' ([0-9a-f]+)$',raw,re.M)
        require(len(values)==3 and all(int(v,16)==value for v in values),'CCFG non originale/incompleto')
    qualify_kernel(kernel,physical_cases,outputs,allocations)
    return dict(status='complete_verified',protocol_complete=True,program_rc=rc,comparisons=12,failures=fail,
                physical_completed=6,sm_completed=6,initializations=24,source_preserved=12,
                data_all_comparisons_pass=fail==0,classifications=classes,unexpected_payload_words=classes.count('unexpected'),
                known_synthetic_payload_only='unexpected' not in classes,P2P_solution_claimed=False,
                direct_route_proven=False,CE_method_submission_reported=True,vendor_supported_peer_read=False,
                physical_mapping_hardware_readback=False)


def validate_log(raw, ccfg, kernel=''):
    try:
        return complete(raw, ccfg, kernel)
    except (ValueError, KeyError, TypeError, OverflowError, IndexError) as error:
        return dict(status='incomplete_preserved',protocol_complete=False,qualification_error=str(error),
                    program_rc=None,comparisons=None,failures=None,data_all_comparisons_pass=False,
                    P2P_solution_claimed=False,direct_route_proven=False,logs_are_partial_evidence=True,
                    watchdog_observed='WATCHDOG_REBOOT' in raw or 'WATCHDOG_REBOOT' in kernel,
                    retained_observed='PHYS_CE_RETAINED ' in raw or 'objects_retained_until_reboot=1' in kernel)
