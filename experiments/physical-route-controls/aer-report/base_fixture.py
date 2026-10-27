"""Fixture CPU sintetiche: nessun contenuto VRAM, dispositivo o SSH."""
import copy
import re
import unittest
import base_log_validation as v


def row(prefix, **kwargs):
    return prefix+' '+' '.join(k+'='+str(value) for k,value in kwargs.items())


def fixture(all_pass=False):
    raw=[]; kernel=[]; va=[0x700000000000,0x700001000000]; handles=[0x100,0x200]
    uuids=['1'*32,'2'*32]; base=1000000; obj=[0x500,0x600]
    def emit(prefix, **kwargs): raw.append(row(prefix,**kwargs))
    def gpu(owner): emit('CE_GPU',index=owner,bdf=v.BDFS[owner],uuid=uuids[owner],name='synthetic',valid=1)
    def access(stage, owner):
        for device in (0,1):
            emit('CE_ACCESS',stage=stage,owner=owner,mode='SHARED',role='shared',device=device,va=format(va[owner],'x'),last_va=format(va[owner]+v.SIZE-1,'x'),first=3,last=3,expected=3,allocation_type=1,location_type=1,location_id=owner,valid=1)
    for owner in (0,1): gpu(owner)
    for owner in (0,1):
        emit('CE_ALLOCATION',nonce=str(owner)*8+'-'+str(owner)*4+'-'+str(owner)*4+'-'+str(owner)*4+'-'+str(owner)*12,owner=owner,mode='SHARED',role='shared',va=format(va[owner],'x'),handle=format(handles[owner],'x'),allocation_bytes=v.SIZE,granularity=65536)
        access('created',owner)
    emit('PHYS_FD_VALIDATION',fd=17,request=base,rv=0,errno=0,rmStatus=0,flags=1,valid=1)
    emit('PHYS_FD_SELECTED',original=17,retained_fd=20,candidates=1,matches=1)
    emit('PHYS_PROTOCOL',name='physical-source-bracket-v1',allocations=2,comparisons=12,groups=2,physical_cases=6,bytes=4,request_base=base,cupti_used=0,vendor_supported_peer_read=0)
    failures=0
    for case_id in range(1,13):
        c=v.spec(case_id); seed=c['seed']; expected=v.pattern(seed); sentinel=expected^0xffffffff
        src=c['s']; dst=c['d']; executor=c['executor']; pull=c['mode']=='PULL'; physical=c['engine']=='UVM_PHYSICAL_CE'
        if case_id in (1,7): emit('PHYS_GROUP_BEGIN',group=c['group'],executor=executor,first_case=case_id)
        for owner in (src,dst): gpu(owner);access('before_case',owner)
        c=dict(c);c['seed']=format(seed,'08x');c.update(bytes=4,expected=format(expected,'08x'),sentinel=format(sentinel,'08x'),src=format(va[src],'x'),dst=format(va[dst],'x'),buffer0=format(va[0],'x'),buffer1=format(va[1],'x'),handle0=format(handles[0],'x'),handle1=format(handles[1],'x'),request=base+case_id if physical else 0,allocations_unchanged=1)
        emit('PHYS_CASE',**c)
        for role,owner,value in [('source',src,expected),('destination',dst,sentinel)]: emit('PHYS_INIT',id=case_id,role=role,owner=owner,va=format(va[owner],'x'),bytes=4,expected=format(value,'08x'),actual=format(value,'08x'),valid=1)
        emit('PHYS_EXECUTOR',id=case_id,device=executor,current='0x1234',stream_context='0x1234',stream='0x2345',valid=1)
        if physical:
            req=c['request']; remote=1-executor; remote_base=[0x4000000000,0x4600000000][remote]; remote_pa=remote_base+0x400000; local_pa=0x800000
            src_pa=remote_pa if pull else local_pa;dst_pa=local_pa if pull else remote_pa
            source_handle=0x1000+executor*0x100+src;dest_handle=0x1000+executor*0x100+dst
            out=dict(request=req,transfer=int(pull),remote_mode=max(c['source_mode'],c['destination_mode']),src=c['src'],dst=c['dst'],bytes=4,rv=0,errno=0,rmStatus=0,flags='77',source_pa=format(src_pa,'x'),destination_pa=format(dst_pa,'x'),source_offset=0,destination_offset=0,source_handle=format(source_handle,'x'),destination_handle=format(dest_handle,'x'),ce_class='c7b5',launch='4003186',source_mode=c['source_mode'],destination_mode=c['destination_mode'],source_is_peer=int(pull),destination_is_peer=int(not pull),stock_rejects_peer_source=int(pull),inputs_unchanged=1)
            emit('PHYS_IOCTL_RESULT',**out)
            emit('PHYS_BAR1',owner=remote,role='source' if pull else 'destination',start=format(remote_base,'x'),end=format(remote_base+0x10000000-1,'x'),flags='200',physical=format(remote_pa,'x'),valid=1)
            def k(stage, **kwargs): kernel.append(row('CASKPHYS',request=req,stage=stage,**kwargs))
            roles=[('source_peer' if pull else 'source_local',executor,src,source_handle),('destination_local' if pull else 'destination_peer',executor,dst,dest_handle),('source_owner' if pull else 'destination_owner',remote,remote,0x1000+remote*0x100+remote)]
            for role,requester,owner,handle in roles:
                addr=va[owner]
                k('map_lookup',role=role,va=format(addr,'x'),requester=v.BDFS[requester],owner=v.BDFS[owner],range_present=1)
                k('map_range',role=role,range_start=format(addr,'x'),range_end=format(addr+v.SIZE-1,'x'))
                guards={name:1 for name in ('handle','rm_handle','map_gpu','handle_gpu','owner','vidmem','non_egm','recorded','descendant','kind','format','page','start','end','contains','permissions')}
                k('map_guards',role=role,bits='ffff',expected='ffff',**guards)
                k('map_meta',role=role,recorded=1,device_descendant=1,kind=6,format=0,mapping_type=0,page_size='200000',sysmem=0,egm=0,rm_handle=format(handle,'x'))
                k('map_identity',role=role,map_gpu=v.BDFS[requester],handle_gpu=v.BDFS[requester],owning_gpu=v.BDFS[owner],user_client='41',user_object=format(obj[owner],'x'))
                k('map_geometry',role=role,node_start=format(addr,'x'),node_end=format(addr+v.SIZE-1,'x'),origin_start=format(addr,'x'),origin_end=format(addr+v.SIZE-1,'x'),map_offset=0,allocation_size=format(v.SIZE,'x'))
                k('map_ready',role=role,offset=0,tracker_status=0)
            for role,_,owner,_ in roles[:2]:
                pa=src_pa if role.startswith('source') else dst_pa
                k('query_result',role=role,mapping_type=2,offset=0,page='1000',bytes='1000',status=0,written=1,remaining=0,base=format(pa,'x'))
            k('classification',executor=v.BDFS[executor],transfer=c['mode'],src_is_peer=int(pull),dst_is_peer=int(not pull),stock_rejects_peer_source=int(pull),stock_hal_unchanged=1,vendor_peer_read_support_established=0)
            k('methods',transfer=c['mode'],executor=v.BDFS[executor],src='synthetic_source',dst='synthetic_destination',src_va=c['src'],dst_va=c['dst'],src_mem=out['source_handle'],dst_mem=out['destination_handle'],src_off=0,dst_off=0,src_phys=out['source_pa'],dst_phys=out['destination_pa'],bytes=4,**{'class':'c7b5'},channel='synthetic_channel',p2p=1,privileged=1,src_mode=c['source_mode'],dst_mode=c['destination_mode'],launch='4003186',no_virtual_fallback=1)
            k('dma_range',executor=v.BDFS[executor],remote=v.BDFS[remote],dma_start=0,dma_limit='ffffffffffff',remote_bar1=format(remote_base,'x'),remote_bar1_size='10000000',local_vram_limit='ffffffff',peer_reference_held=1)
            k('return',operation=1,transfer=int(pull),status=0,flags='77',last_stage='submitted_wait')
        else: emit('PHYS_SM_COMPLETE',id=case_id,executor=executor,src=c['src'],dst=c['dst'],bytes=4,kernel='peer_push_kernel',blocks=1,threads=1,stream_synchronized=1)
        emit('PHYS_SOURCE_RECHECK',id=case_id,owner=src,va=c['src'],bytes=4,expected=format(expected,'08x'),actual=format(expected,'08x'),valid=1)
        actual=expected if all_pass or (executor==1 and not pull) else 0xffffffff if pull else sentinel
        passed=actual==expected;failures+=not passed
        classification='expected' if passed else 'all_ones' if pull else 'unchanged_sentinel'
        emit('PHYS_DATA_RESULT',id=case_id,engine=c['engine'],mode=c['mode'],executor=executor,s=src,d=dst,bytes=4,checked_words=1,expected=c['expected'],sentinel=c['sentinel'],actual=format(actual,'08x'),mismatches=int(not passed),first_mismatch=-1 if passed else 0,last_mismatch=-1 if passed else 0,classification=classification,valid=int(passed),direct_route_proven=0)
        for owner in (src,dst): access('after_case',owner)
        if case_id in (6,12): emit('PHYS_GROUP_END',group=c['group'],last_case=case_id)
    for owner in (0,1): emit('PHYS_FREE',owner=owner,va=format(va[owner],'x'),handle=format(handles[owner],'x'),valid=1)
    rc=5 if failures else 0
    emit('PHYS_PROGRAM_END',protocol_complete=1,comparisons=12,failures=failures,physical_cases=6,physical_completed=6,sm_cases=6,source_preserved=12,initializations=24,allocations=2,direct_route_proven=0,vendor_supported_peer_read=0,rc=rc)
    raw.extend(['NATIVE_TEST_RC='+str(rc),'SCRIPT_RC='+str(rc),'PROBE_COMPLETED'])
    ccfg={'0000:00:01.0':(0x460d8086,0x04008077),'0000:00:07.0':(0x466e8086,0x0e009077)}
    for _ in range(3): raw.extend(['PEG_CCFG 00:01.0 04008077','TCSS_CCFG 00:07.0 0e009077'])
    return '\n'.join(raw)+'\n',ccfg,'\n'.join(kernel)+'\n'
