from pathlib import Path
import hashlib,json,shutil
D=Path(__file__).resolve().parent
B=D.parents[1]/'p2p-tcss-bit-tests-20261021/native-ce-probe'
s=(B/'peer_ce_cupti.cu').read_text()
assert hashlib.sha256(s.encode()).hexdigest()=='89f1639244b589ef89dfb3231c84b278b5c8caedef5c74e9d76d5a16da3d309c'
s=s[:s.index('static int run(){')]
s=s.replace('#include "cupti_trace.h"','#include "nvml_sampler.h"')
s=s.replace('size_t words) {','size_t words, unsigned passes) {',1)
s=s.replace('    for (size_t i = blockIdx.x * blockDim.x + threadIdx.x;', '    for (unsigned pass=0; pass<passes; ++pass)\n    for (size_t i = blockIdx.x * blockDim.x + threadIdx.x;',1)
s=s.replace('CaskLogicCE','CaskLogicTraffic').replace('CE_ACCESS','TRAFFIC_ACCESS').replace('CE_ALLOCATION','TRAFFIC_ALLOCATION').replace('CE_GPU','TRAFFIC_GPU')
s=s.replace('std::exit(20);','throw std::runtime_error("clock_gettime");').replace('std::exit(21);','throw std::runtime_error("cuda_failure");').replace('std::exit(22);','throw std::runtime_error("driver_failure");').replace('std::exit(24);','throw std::runtime_error("owner_validation_failed");')
s+='''
static constexpr size_t PAYLOAD_BYTES=1024*1024;
static constexpr unsigned BATCH_COPIES=64, MAX_BATCHES=4096;
static constexpr uint64_t TARGET_NS=1200000000ULL, LIMIT_NS=5000000000ULL;
static int run(){
 traffic::Client nvml;nvml.initialize();CUCK(cuInit(0));int count=0;CK(cudaGetDeviceCount(&count));if(count!=2)throw std::runtime_error("gpu_count");
 CUcontext contexts[2]{};CUstream streams[2]{};CUevent events[2]{};
 for(int i=0;i<2;++i){CK(cudaSetDevice(i));CK(cudaFree(nullptr));CK(cudaDeviceSynchronize());check_identity(i);CUCK(cuCtxGetCurrent(&contexts[i]));if(!contexts[i])throw std::runtime_error("missing_context");CUCK(cuStreamCreate(&streams[i],CU_STREAM_NON_BLOCKING));CUCK(cuEventCreate(&events[i],CU_EVENT_DISABLE_TIMING));}
 sync_both();pcie_snapshot("traffic_program_baseline");phase("allocations_begin");
 for(int i=0;i<2;++i){allocate(send_buffer[i],i,"send");allocate(receive_buffer[i],i,"receive");}
 sync_both();phase("allocations_done");
 std::vector<uint32_t> expected(PAYLOAD_BYTES/4),poison(PAYLOAD_BYTES/4),observed(PAYLOAD_BYTES/4);
 unsigned id=0,failures=0,qualified=0;
 for(int source=0;source<2;++source){int destination=1-source;
  for(int engine=0;engine<2;++engine){const bool copy=engine==1;++id;const char*engine_name=copy?"CUDA_COPY_REQUEST":"SM";
   sync_both();check_identity(source);check_identity(destination);
   verify_mapping(send_buffer[source],"before_phase");verify_mapping(receive_buffer[destination],"before_phase");
   const uint32_t seed=0x6b8b4567u^uint32_t(PAYLOAD_BYTES)^(0x13579bdfu*uint32_t(source+1));
   for(size_t j=0;j<expected.size();++j){expected[j]=word_pattern(j,seed);poison[j]=~expected[j];}
   std::printf("TRAFFIC_CASE id=%u engine=%s s=%d d=%d executor=%d bytes=%zu batch_copies=%u max_batches=%u target_ns=%llu limit_ns=%llu src=%llx dst=%llx allocations_unchanged=1 ce_observed=0\\n",id,engine_name,source,destination,source,PAYLOAD_BYTES,BATCH_COPIES,MAX_BATCHES,(unsigned long long)TARGET_NS,(unsigned long long)LIMIT_NS,(unsigned long long)send_buffer[source].address,(unsigned long long)receive_buffer[destination].address);
   init_and_verify(send_buffer[source],expected,observed,PAYLOAD_BYTES,"source_initialized",source,destination,int(id));
   init_and_verify(receive_buffer[destination],poison,observed,PAYLOAD_BYTES,"destination_poisoned",source,destination,int(id));
   sync_both();CK(cudaSetDevice(source));
   CUcontext current=nullptr,stream_context=nullptr;CUdevice current_device=-1;
   CUCK(cuCtxGetCurrent(&current));CUCK(cuCtxGetDevice(&current_device));CUCK(cuStreamGetCtx(streams[source],&stream_context));
   if(current!=contexts[source]||stream_context!=contexts[source]||int(current_device)!=source)throw std::runtime_error("executor_context_mismatch");
   std::printf("TRAFFIC_EXECUTOR id=%u device=%d current=%p stream_context=%p stream=%p valid=1\\n",id,source,(void*)current,(void*)stream_context,(void*)streams[source]);
   char label[80];std::snprintf(label,sizeof(label),"traffic_%u_before",id);pcie_snapshot(label);phase("owners_ready",source,destination);
   traffic::Sampler sampler(nvml);
   std::this_thread::sleep_for(std::chrono::milliseconds(200));
   sampler.stage(1);const uint64_t active_begin=ns_now();unsigned batches=0;bool budget_exhausted=false;
   // No H2D/D2H, PCI config snapshot or stdout logging until the final event.
   // One bounded batch is in flight. CUDA COPY is requested, not CE-certified.
   do {
    if(copy){for(unsigned n=0;n<BATCH_COPIES;++n)CUCK(cuMemcpyDtoDAsync(receive_buffer[destination].address,send_buffer[source].address,PAYLOAD_BYTES,streams[source]));}
    else {peer_push_kernel<<<256,256,0,reinterpret_cast<cudaStream_t>(streams[source])>>>(reinterpret_cast<const uint32_t*>(send_buffer[source].address),reinterpret_cast<volatile uint32_t*>(receive_buffer[destination].address),PAYLOAD_BYTES/4,BATCH_COPIES);CK(cudaGetLastError());}
    CUCK(cuEventRecord(events[source],streams[source]));
    for(;;){CUresult q=cuEventQuery(events[source]);if(q==CUDA_SUCCESS)break;if(q!=CUDA_ERROR_NOT_READY)CUCK(q);
     if(ns_now()-active_begin>=LIMIT_NS)throw std::runtime_error("active_event_deadline_exceeded");
     std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    ++batches;
    if(ns_now()-active_begin>=LIMIT_NS){budget_exhausted=true;break;}
   }while(ns_now()-active_begin<TARGET_NS && batches<MAX_BATCHES);
   const uint64_t active_end=ns_now();sampler.stage(2);
   // Event completion is sufficient for prior work in this stream; no further
   // CUDA operation until the sampler has been stopped and joined.
   std::this_thread::sleep_for(std::chrono::milliseconds(100));sampler.stop_join();
   const uint64_t joined_before_report=ns_now();
   std::printf("TRAFFIC_WINDOW id=%u engine=%s s=%d d=%d begin_ns=%llu end_ns=%llu sampler_joined_ns=%llu duration_ns=%llu batches=%u submitted_payload_bytes=%llu budget_exhausted=%d no_host_payload_ops_during_window=1\\n",id,engine_name,source,destination,(unsigned long long)active_begin,(unsigned long long)active_end,(unsigned long long)joined_before_report,(unsigned long long)(active_end-active_begin),batches,(unsigned long long)(uint64_t(batches)*BATCH_COPIES*PAYLOAD_BYTES),budget_exhausted);
   const bool sample_valid=sampler.report(id,active_begin,active_end);
   bool duration_valid=active_end-active_begin>=TARGET_NS && active_end-active_begin<=LIMIT_NS && !budget_exhausted;
   qualified+=sample_valid&&duration_valid;
   phase("sampler_joined",source,destination);std::snprintf(label,sizeof(label),"traffic_%u_after",id);pcie_snapshot(label);
   CK(cudaSetDevice(destination));CK(cudaMemcpy(observed.data(),reinterpret_cast<void*>(receive_buffer[destination].address),PAYLOAD_BYTES,cudaMemcpyDeviceToHost));CK(cudaDeviceSynchronize());
   const size_t mismatch=compare(observed,expected,PAYLOAD_BYTES/4,"peer_payload",destination,source,destination,PAYLOAD_BYTES,int(id));failures+=mismatch!=0;
   std::printf("TRAFFIC_DATA_RESULT id=%u engine=%s s=%d d=%d bytes=%zu checked_words=%zu mismatches=%zu valid=%d sampling_valid=%d duration_valid=%d ce_observed=0 direct_route_proven=0\\n",id,engine_name,source,destination,PAYLOAD_BYTES,PAYLOAD_BYTES/4,mismatch,mismatch==0,sample_valid,duration_valid);
   verify_mapping(send_buffer[source],"after_phase");verify_mapping(receive_buffer[destination],"after_phase");phase("comparison_done",source,destination);
  }
 }
 sync_both();phase("data_done");
 for(int i=0;i<2;++i){release(send_buffer[i]);release(receive_buffer[i]);CK(cudaSetDevice(i));CUCK(cuEventDestroy(events[i]));CUCK(cuStreamDestroy(streams[i]));}
 phase("cleanup_done");int rc=qualified!=4?6:(failures?5:0);
 std::printf("TRAFFIC_PROGRAM_END protocol_complete=1 comparisons=%u failures=%u qualified_windows=%u nvml_only=1 ce_observed=0 direct_route_proven=0 rc=%d\\n",id,failures,qualified,rc);
 phase("context_exit_begin");return rc;
}
int main(){
 setbuf(stdout,nullptr);kmsg_fd=open("/dev/kmsg",O_WRONLY|O_CLOEXEC);int rc=27;
 try{phase("program_start");if(kmsg_fd<0)throw std::runtime_error("kmsg_required");rc=run();}
 catch(const std::exception&e){std::printf("TRAFFIC_ABORT reason=%s protocol_complete=0 direct_route_proven=0 rc=27\\n",e.what());}
 if(kmsg_fd>=0)close(kmsg_fd);return rc;
}
'''
(D/'peer_traffic.cu').write_text(s)
shutil.copyfile(B/'pcie_diag.h',D/'pcie_diag.h')
provenance={'baseline_source':str(B/'peer_ce_cupti.cu'),'baseline_sha256':'89f1639244b589ef89dfb3231c84b278b5c8caedef5c74e9d76d5a16da3d309c','nvml_header':json.loads((D.parent/'nvml-official-package/provenance.json').read_text()),'files':{n:hashlib.sha256((D/n).read_bytes()).hexdigest() for n in ('peer_traffic.cu','nvml_sampler.h','pcie_diag.h','include/nvml.h')},'runtime_tested':False,'remote_operations_by_author':False}
(D/'source-provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
print(json.dumps(provenance['files'],indent=2))
