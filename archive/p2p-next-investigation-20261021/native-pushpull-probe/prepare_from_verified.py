#!/usr/bin/env python3
"""Crea solo il nuovo candidato locale a partire dai sorgenti CE immutati."""
from pathlib import Path
import hashlib,json
D=Path(__file__).resolve().parent
OLD=D.parent.parent/'p2p-tcss-bit-tests-20261021'/'native-ce-probe'
expected={'peer_ce_cupti.cu':'89f1639244b589ef89dfb3231c84b278b5c8caedef5c74e9d76d5a16da3d309c','cupti_trace.h':'0de1f3097fbe22c775d4c603615cfd9f0a69c328e9e7da55d50389e60ed5b468','pcie_diag.h':'4820c6c0f296c9af7bb75403885f860a3f8d1837d0aed1e625143258001358ae'}
def sha(x):return hashlib.sha256(x).hexdigest()
for n,h in expected.items():assert sha((OLD/n).read_bytes())==h,n
def swap(t,a,b,count=1):
 assert t.count(a)==count,(a,t.count(a),count)
 return t.replace(a,b)
h=(OLD/'cupti_trace.h').read_text()
h=swap(h,'bool ce=false;int source=-1,destination=-1;','bool ce=false;int source=-1,destination=-1,executor=-1;const char *mode=nullptr;')
h=swap(h,'stream_id=0,target_device=0;','stream_id=0,target_device=0,source_device=0;')
h=swap(h,'cases.reserve(12);','cases.reserve(24);')
h=swap(h,'int source,int destination,CUcontext context,CUcontext target,CUstream stream,','int source,int destination,int executor,const char *mode,CUcontext context,CUcontext source_context,CUcontext target,CUstream stream,')
h=swap(h,'c.destination=destination;c.stream=stream;','c.destination=destination;c.executor=executor;c.mode=mode;c.stream=stream;')
h=swap(h,'check(cuptiGetDeviceId(context,&c.device),"device_id");','check(cuptiGetDeviceId(context,&c.device),"device_id");check(cuptiGetDeviceId(source_context,&c.source_device),"source_device_id");')
h=swap(h,'engine=%s s=%d d=%d device=%u target_device=%u','engine=%s mode=%s s=%d d=%d executor=%d device=%u source_device=%u target_device=%u')
h=swap(h,'ce?"CE_REQUEST":"SM",source,destination,c.device,c.target_device,','ce?"CE_REQUEST":"SM",mode,source,destination,executor,c.device,c.source_device,c.target_device,')
h=swap(h,'cases.size()==12;','cases.size()==24;')
h=swap(h,'r.src_device!=c.device || r.dst_device!=c.target_device','r.src_device!=c.source_device || r.dst_device!=c.target_device')
h=swap(h,'engine=%s copies=%u','engine=%s mode=%s executor=%d copies=%u')
h=swap(h,'c.ce?"CE_REQUEST":"SM",copies,kernels,','c.ce?"CE_REQUEST":"SM",c.mode,c.executor,copies,kernels,')
s=(OLD/'peer_ce_cupti.cu').read_text()
s=swap(s,'// CPU initializes and checks buffers. Only this kernel carries the payload\n// between GPUs: its source belongs to the executing GPU, its destination to peer.','// CPU initializes and checks each owner. The unchanged transfer kernel uses\n// local source / peer target for PUSH, peer source / local target for PULL.\n// Its legacy symbol is retained so its generated operation remains comparable.')
s=swap(s,'    const char *role = nullptr;','    const char *role = nullptr;\n    int mode = -1;')
s=swap(s,'static Buffer send_buffer[2], receive_buffer[2];','static Buffer send_buffer[2][2], receive_buffer[2][2];\nstatic const char *mode_name(int mode){if(mode<0 || mode>1)throw std::runtime_error("mode_range");return mode==0?"PUSH":"PULL";}\nstatic bool shared_buffer(const Buffer &b){return (b.mode==0 && !std::strcmp(b.role,"receive")) || (b.mode==1 && !std::strcmp(b.role,"send"));}')
s=swap(s,'stage=%s owner=%d role=%s va=','stage=%s owner=%d mode=%s role=%s va=')
s=swap(s,'nonce,stage,b.owner,b.role,','nonce,stage,b.owner,mode_name(b.mode),b.role,')
s=swap(s,'(!std::strcmp(b.role,"send") && i!=b.owner)?','(!shared_buffer(b) && i!=b.owner)?')
s=swap(s,'stage=%s owner=%d role=%s device=','stage=%s owner=%d mode=%s role=%s device=')
s=swap(s,'stage,b.owner,b.role,i,','stage,b.owner,mode_name(b.mode),b.role,i,')
s=swap(s,'static void allocate(Buffer &buffer,int owner,const char *role){','static void allocate(Buffer &buffer,int owner,int mode,const char *role){')
s=swap(s,'buffer.owner=owner;buffer.role=role;','buffer.owner=owner;buffer.mode=mode;buffer.role=role;')
s=swap(s,'(!std::strcmp(role,"send") && i!=owner)?','(!shared_buffer(buffer) && i!=owner)?')
s=swap(s,'nonce=%s owner=%d role=%s va=','nonce=%s owner=%d mode=%s role=%s va=')
s=swap(s,'nonce,owner,role,','nonce,owner,mode_name(mode),role,')
s=swap(s,'for(int i=0;i<2;++i){allocate(send_buffer[i],i,"send");allocate(receive_buffer[i],i,"receive");}','for(int mode=0;mode<2;++mode)for(int i=0;i<2;++i){allocate(send_buffer[mode][i],i,mode,"send");allocate(receive_buffer[mode][i],i,mode,"receive");}')
start=s.index(' for(int source=0;source<2;++source){int destination=1-source;')
end=s.index(' sync_both();phase("data_done");',start)
body=s[start:end]
body=swap(body,' for(int source=0;source<2;++source){int destination=1-source;',' for(int mode=0;mode<2;++mode){\n  std::printf("CE_MODE_BEGIN mode=%s first_case=%llu\\n",mode_name(mode),(unsigned long long)(id+1));\n  for(int source=0;source<2;++source){int destination=1-source;const int executor=mode==0?source:destination;')
body=body.replace('send_buffer[source]','send_buffer[mode][source]').replace('receive_buffer[destination]','receive_buffer[mode][destination]')
body=swap(body,'bool ce=engine==1;++id;','bool ce=mode==0?engine==1:engine==0;++id;')
body=swap(body,'CE_CASE id=%llu engine=%s s=%d d=%d','CE_CASE id=%llu engine=%s mode=%s executor=%d s=%d d=%d')
body=swap(body,'(unsigned long long)id,ce?"CE_REQUEST":"SM",source,destination,bytes,seed,','(unsigned long long)id,ce?"CE_REQUEST":"SM",mode_name(mode),executor,source,destination,bytes,seed,')
body=swap(body,'CK(cudaSetDevice(source));','CK(cudaSetDevice(executor));')
body=body.replace('streams[source]','streams[executor]').replace('contexts[source]','contexts[executor]')
body=swap(body,'int(current_device)!=source','int(current_device)!=executor')
body=swap(body,'(unsigned long long)id,source,(void*)current','(unsigned long long)id,executor,(void*)current')
body=swap(body,'ce_trace::begin(id,ce,source,destination,contexts[executor],contexts[destination],','ce_trace::begin(id,ce,source,destination,executor,mode_name(mode),contexts[executor],contexts[source],contexts[destination],')
body=swap(body,'CE_DATA_RESULT id=%llu engine=%s s=%d d=%d','CE_DATA_RESULT id=%llu engine=%s mode=%s executor=%d s=%d d=%d')
body=swap(body,'(unsigned long long)id,ce?"CE_REQUEST":"SM",source,destination,bytes,words,','(unsigned long long)id,ce?"CE_REQUEST":"SM",mode_name(mode),executor,source,destination,bytes,words,')
body+='  std::printf("CE_MODE_END mode=%s last_case=%llu\\n",mode_name(mode),(unsigned long long)id);\n }\n'
s=s[:start]+body+s[end:]
s=swap(s,'comparisons!=12 || trace.ce_cases!=6','comparisons!=24 || trace.ce_cases!=12')
s=swap(s,'for(int i=0;i<2;++i){release(send_buffer[i]);release(receive_buffer[i]);CK(cudaSetDevice(i));CUCK(cuStreamDestroy(streams[i]));}','for(int mode=0;mode<2;++mode)for(int i=0;i<2;++i){release(send_buffer[mode][i]);release(receive_buffer[mode][i]);}\n for(int i=0;i<2;++i){CK(cudaSetDevice(i));CUCK(cuStreamDestroy(streams[i]));}')
s=swap(s,'trace.ce_observed!=6 || trace.sm_observed!=6','trace.ce_observed!=12 || trace.sm_observed!=12')
(D/'peer_pushpull_cupti.cu').write_text(s);(D/'cupti_trace.h').write_text(h);(D/'pcie_diag.h').write_bytes((OLD/'pcie_diag.h').read_bytes())
out={n:sha((D/n).read_bytes()) for n in ['peer_pushpull_cupti.cu','cupti_trace.h','pcie_diag.h']}
(D/'source-provenance.json').write_text(json.dumps({'parent_files':expected,'candidate_files':out,'candidate_only':True,'hardware_or_remote':False,'changes':'Two disjoint PUSH/PULL buffer sets; destination execution for PULL; CUPTI source device separated from executor; 24 cases, no source file changed.'},indent=2)+'\n')
print(json.dumps(out,indent=2))
