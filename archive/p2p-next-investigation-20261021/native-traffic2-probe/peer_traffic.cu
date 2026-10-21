#include <cuda.h>
#include <cuda_runtime.h>
#include <algorithm>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <time.h>
#include <unistd.h>
#include <vector>
#include "pcie_diag.h"
#include "nvml_sampler.h"
#include <stdexcept>
#include <string>

// CPU initializes and checks buffers. Only this kernel carries the payload
// between GPUs: its source belongs to the executing GPU, its destination to peer.
__global__ void peer_push_kernel(const uint32_t *local_source,
                                 volatile uint32_t *peer_destination,
                                 size_t words, unsigned passes) {
    bool wrote = false;
    for (unsigned pass=0; pass<passes; ++pass)
    for (size_t i = blockIdx.x * blockDim.x + threadIdx.x;
         i < words; i += gridDim.x * blockDim.x) {
        peer_destination[i] = local_source[i];
        wrote = true;
    }
    if (wrote) __threadfence_system();
}

static int kmsg_fd = -1;
static uint64_t ns_now() {
    timespec t{};
    if (clock_gettime(CLOCK_MONOTONIC, &t)) {
        std::printf("FATAL clock_gettime errno=%d\n", errno);
        throw std::runtime_error("clock_gettime");
    }
    return uint64_t(t.tv_sec) * 1000000000ULL + uint64_t(t.tv_nsec);
}
static void phase(const char *name, int source=-1, int destination=-1) {
    const uint64_t ns = ns_now();
    char line[256];
    const int n = std::snprintf(line, sizeof(line),
        "CaskLogicTraffic phase=%s monotonic=%llu.%09llu s=%d d=%d\n",
        name, (unsigned long long)(ns/1000000000ULL),
        (unsigned long long)(ns%1000000000ULL), source, destination);
    std::fputs(line, stdout);
    if (kmsg_fd >= 0 && n > 0 && size_t(n) < sizeof(line)) {
        const ssize_t result = write(kmsg_fd, line, size_t(n));
        if (result != n) std::printf("KMSG_MARKER_FAILED errno=%d\n", errno);
    }
}
static void runtime_check(cudaError_t value, const char *call, int line) {
    if (value == cudaSuccess) return;
    std::printf("CUDA_ERROR call=%s line=%d code=%d error=%s\n", call, line, int(value), cudaGetErrorString(value));
    phase("cuda_error");
    throw std::runtime_error("cuda_failure");
}
static void driver_check(CUresult value, const char *call, int line) {
    if (value == CUDA_SUCCESS) return;
    const char *message = "unknown";
    cuGetErrorString(value, &message);
    std::printf("DRIVER_ERROR call=%s line=%d code=%d error=%s\n", call, line, int(value), message);
    phase("driver_error");
    throw std::runtime_error("driver_failure");
}
#define CK(call) runtime_check((call), #call, __LINE__)
#define CUCK(call) driver_check((call), #call, __LINE__)

struct Buffer {
    CUdeviceptr address = 0;
    CUmemGenericAllocationHandle handle = 0;
    size_t allocation_bytes = 0;
    size_t granularity = 0;
    int owner = -1;
    const char *role = nullptr;
};
static constexpr size_t MAX_BYTES = 8ULL * 1024 * 1024;
static Buffer send_buffer[2], receive_buffer[2];

static void allocation_marker(const char *nonce,const char *stage,const Buffer &b){
 char line[512];const int n=std::snprintf(line,sizeof(line),"CaskLogicTrafficAllocation nonce=%s stage=%s owner=%d role=%s va=%llx bytes=%zu\n",nonce,stage,b.owner,b.role,(unsigned long long)b.address,b.allocation_bytes);
 std::fputs(line,stdout);if(kmsg_fd<0 || n<=0 || size_t(n)>=sizeof(line) || write(kmsg_fd,line,size_t(n))!=n)throw std::runtime_error("allocation_marker_failed");
}
static void verify_mapping(const Buffer &b,const char *stage){
 CUmemAllocationProp p{};CUCK(cuMemGetAllocationPropertiesFromHandle(&p,b.handle));
 bool prop_ok=p.type==CU_MEM_ALLOCATION_TYPE_PINNED && p.location.type==CU_MEM_LOCATION_TYPE_DEVICE && p.location.id==b.owner;
 if(!prop_ok)throw std::runtime_error("allocation_property_changed");
 for(int i=0;i<2;++i){CUmemLocation loc{};loc.type=CU_MEM_LOCATION_TYPE_DEVICE;loc.id=i;
  unsigned long long first=0,last=0;CUCK(cuMemGetAccess(&first,&loc,b.address));CUCK(cuMemGetAccess(&last,&loc,b.address+b.allocation_bytes-1));
  unsigned long long expected=(!std::strcmp(b.role,"send") && i!=b.owner)?CU_MEM_ACCESS_FLAGS_PROT_NONE:CU_MEM_ACCESS_FLAGS_PROT_READWRITE;
  std::printf("TRAFFIC_ACCESS stage=%s owner=%d role=%s device=%d va=%llx last_va=%llx first=%llu last=%llu expected=%llu allocation_type=%d location_type=%d location_id=%d valid=%d\n",stage,b.owner,b.role,i,(unsigned long long)b.address,(unsigned long long)(b.address+b.allocation_bytes-1),first,last,expected,int(p.type),int(p.location.type),p.location.id,first==expected && last==expected);
  if(first!=expected || last!=expected)throw std::runtime_error("vmm_access_mismatch");
 }
}
static void allocate(Buffer &buffer,int owner,const char *role){
 CK(cudaSetDevice(owner));CUmemAllocationProp prop{};prop.type=CU_MEM_ALLOCATION_TYPE_PINNED;prop.location.type=CU_MEM_LOCATION_TYPE_DEVICE;prop.location.id=owner;
 CUCK(cuMemGetAllocationGranularity(&buffer.granularity,&prop,CU_MEM_ALLOC_GRANULARITY_MINIMUM));
 if(!buffer.granularity || MAX_BYTES%buffer.granularity)throw std::runtime_error("allocation_granularity");
 buffer.owner=owner;buffer.role=role;buffer.allocation_bytes=MAX_BYTES;
 CUCK(cuMemAddressReserve(&buffer.address,MAX_BYTES,0,0,0));CUCK(cuMemCreate(&buffer.handle,MAX_BYTES,&prop,0));CUCK(cuMemMap(buffer.address,MAX_BYTES,0,buffer.handle,0));
 char nonce[64]{};FILE *file=std::fopen("/proc/sys/kernel/random/uuid","r");if(!file || !std::fgets(nonce,sizeof(nonce),file)){if(file)std::fclose(file);throw std::runtime_error("allocation_nonce");}std::fclose(file);nonce[std::strcspn(nonce,"\r\n")]=0;if(std::strlen(nonce)!=36)throw std::runtime_error("nonce_length");
 allocation_marker(nonce,"begin",buffer);
 CUmemAccessDesc access[2]{};for(int i=0;i<2;++i){access[i].location.type=CU_MEM_LOCATION_TYPE_DEVICE;access[i].location.id=i;access[i].flags=(!std::strcmp(role,"send") && i!=owner)?CU_MEM_ACCESS_FLAGS_PROT_NONE:CU_MEM_ACCESS_FLAGS_PROT_READWRITE;}
 CUCK(cuMemSetAccess(buffer.address,MAX_BYTES,access,2));
 allocation_marker(nonce,"end",buffer);
 std::printf("TRAFFIC_ALLOCATION nonce=%s owner=%d role=%s va=%llx handle=%llx allocation_bytes=%zu granularity=%zu\n",nonce,owner,role,(unsigned long long)buffer.address,(unsigned long long)buffer.handle,MAX_BYTES,buffer.granularity);
 verify_mapping(buffer,"created");
}
static void release(Buffer &buffer) {
    CK(cudaSetDevice(buffer.owner));
    phase("allocation_free_begin", buffer.owner);
    CUCK(cuMemUnmap(buffer.address, buffer.allocation_bytes));
    CUCK(cuMemRelease(buffer.handle));
    CUCK(cuMemAddressFree(buffer.address, buffer.allocation_bytes));
    phase("allocation_free_done", buffer.owner);
}

static uint32_t word_pattern(size_t index, uint32_t seed) {
    uint32_t x = uint32_t(index) ^ seed;
    x ^= x >> 16;
    x *= 0x7feb352du;
    x ^= x >> 15;
    x *= 0x846ca68bu;
    x ^= x >> 16;
    return x;
}
static size_t compare(const std::vector<uint32_t> &got, const std::vector<uint32_t> &expected,
                      size_t words, const char *stage, int owner, int source, int destination,
                      size_t bytes, int iteration) {
    size_t mismatches = 0, first = words;
    for (size_t i=0; i<words; ++i) {
        if (got[i] != expected[i]) {
            if (first == words) first = i;
            ++mismatches;
        }
    }
    std::printf("FULL_COMPARE stage=%s owner=%d s=%d d=%d bytes=%zu iteration=%d checked_words=%zu mismatches=%zu valid=%d",
        stage, owner, source, destination, bytes, iteration, words, mismatches, mismatches == 0);
    if (mismatches) std::printf(" first_index=%zu first_got=%08x first_expected=%08x", first, got[first], expected[first]);
    std::printf("\n");
    return mismatches;
}
static void init_and_verify(const Buffer &buffer, const std::vector<uint32_t> &value,
                            std::vector<uint32_t> &observed, size_t bytes,
                            const char *stage, int source, int destination, int iteration) {
    CK(cudaSetDevice(buffer.owner));
    CK(cudaMemcpy((void *)buffer.address, value.data(), bytes, cudaMemcpyHostToDevice));
    CK(cudaDeviceSynchronize());
    CK(cudaMemcpy(observed.data(), (void *)buffer.address, bytes, cudaMemcpyDeviceToHost));
    CK(cudaDeviceSynchronize());
    if (compare(observed, value, bytes/sizeof(uint32_t), stage, buffer.owner,
                source, destination, bytes, iteration)) {
        phase("owner_validation_failed", source, destination);
        throw std::runtime_error("owner_validation_failed");
    }
}

static void sync_both(){for(int i=0;i<2;++i){CK(cudaSetDevice(i));CK(cudaDeviceSynchronize());}}
static void check_identity(int i){
 const char *expected_bdf[2]={"0000:01:00.0","0000:06:00.0"};
 const char *expected_uuid[2]={"00000000000000000000000000000001","00000000000000000000000000000002"};
 char bdf[32]{},uuid[33]{};cudaDeviceProp p{};CK(cudaGetDeviceProperties(&p,i));CK(cudaDeviceGetPCIBusId(bdf,sizeof(bdf),i));
 for(int j=0;j<16;++j)std::snprintf(uuid+2*j,3,"%02x",static_cast<unsigned char>(p.uuid.bytes[j]));
 bool valid=std::strcmp(bdf,expected_bdf[i])==0 && std::strcmp(uuid,expected_uuid[i])==0;
 std::printf("TRAFFIC_GPU index=%d bdf=%s uuid=%s name=%s valid=%d\n",i,bdf,uuid,p.name,valid);
 if(!valid)throw std::runtime_error("gpu_identity_mismatch");
}

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
   std::printf("TRAFFIC_CASE id=%u engine=%s s=%d d=%d executor=%d bytes=%zu batch_copies=%u max_batches=%u target_ns=%llu limit_ns=%llu src=%llx dst=%llx allocations_unchanged=1 ce_observed=0\n",id,engine_name,source,destination,source,PAYLOAD_BYTES,BATCH_COPIES,MAX_BATCHES,(unsigned long long)TARGET_NS,(unsigned long long)LIMIT_NS,(unsigned long long)send_buffer[source].address,(unsigned long long)receive_buffer[destination].address);
   init_and_verify(send_buffer[source],expected,observed,PAYLOAD_BYTES,"source_initialized",source,destination,int(id));
   init_and_verify(receive_buffer[destination],poison,observed,PAYLOAD_BYTES,"destination_poisoned",source,destination,int(id));
   sync_both();CK(cudaSetDevice(source));
   CUcontext current=nullptr,stream_context=nullptr;CUdevice current_device=-1;
   CUCK(cuCtxGetCurrent(&current));CUCK(cuCtxGetDevice(&current_device));CUCK(cuStreamGetCtx(streams[source],&stream_context));
   if(current!=contexts[source]||stream_context!=contexts[source]||int(current_device)!=source)throw std::runtime_error("executor_context_mismatch");
   std::printf("TRAFFIC_EXECUTOR id=%u device=%d current=%p stream_context=%p stream=%p valid=1\n",id,source,(void*)current,(void*)stream_context,(void*)streams[source]);
   char label[80];std::snprintf(label,sizeof(label),"traffic_%u_before",id);pcie_snapshot(label);phase("owners_ready",source,destination);
   traffic::Sampler sampler(nvml);
   std::this_thread::sleep_for(std::chrono::milliseconds(2000));
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
   std::printf("TRAFFIC_WINDOW id=%u engine=%s s=%d d=%d begin_ns=%llu end_ns=%llu sampler_joined_ns=%llu duration_ns=%llu batches=%u submitted_payload_bytes=%llu budget_exhausted=%d no_host_payload_ops_during_window=1\n",id,engine_name,source,destination,(unsigned long long)active_begin,(unsigned long long)active_end,(unsigned long long)joined_before_report,(unsigned long long)(active_end-active_begin),batches,(unsigned long long)(uint64_t(batches)*BATCH_COPIES*PAYLOAD_BYTES),budget_exhausted);
   const bool sample_valid=sampler.report(id,active_begin,active_end);
   bool duration_valid=active_end-active_begin>=TARGET_NS && active_end-active_begin<=LIMIT_NS && !budget_exhausted;
   qualified+=sample_valid&&duration_valid;
   phase("sampler_joined",source,destination);std::snprintf(label,sizeof(label),"traffic_%u_after",id);pcie_snapshot(label);
   CK(cudaSetDevice(destination));CK(cudaMemcpy(observed.data(),reinterpret_cast<void*>(receive_buffer[destination].address),PAYLOAD_BYTES,cudaMemcpyDeviceToHost));CK(cudaDeviceSynchronize());
   const size_t mismatch=compare(observed,expected,PAYLOAD_BYTES/4,"peer_payload",destination,source,destination,PAYLOAD_BYTES,int(id));failures+=mismatch!=0;
   std::printf("TRAFFIC_DATA_RESULT id=%u engine=%s s=%d d=%d bytes=%zu checked_words=%zu mismatches=%zu valid=%d sampling_valid=%d duration_valid=%d ce_observed=0 direct_route_proven=0\n",id,engine_name,source,destination,PAYLOAD_BYTES,PAYLOAD_BYTES/4,mismatch,mismatch==0,sample_valid,duration_valid);
   verify_mapping(send_buffer[source],"after_phase");verify_mapping(receive_buffer[destination],"after_phase");phase("comparison_done",source,destination);
  }
 }
 sync_both();phase("data_done");
 for(int i=0;i<2;++i){release(send_buffer[i]);release(receive_buffer[i]);CK(cudaSetDevice(i));CUCK(cuEventDestroy(events[i]));CUCK(cuStreamDestroy(streams[i]));}
 phase("cleanup_done");int rc=qualified!=4?6:(failures?5:0);
 std::printf("TRAFFIC_PROGRAM_END protocol_complete=1 comparisons=%u failures=%u qualified_windows=%u nvml_only=1 ce_observed=0 direct_route_proven=0 rc=%d\n",id,failures,qualified,rc);
 phase("context_exit_begin");return rc;
}
int main(){
 setbuf(stdout,nullptr);kmsg_fd=open("/dev/kmsg",O_WRONLY|O_CLOEXEC);int rc=27;
 try{phase("program_start");if(kmsg_fd<0)throw std::runtime_error("kmsg_required");rc=run();}
 catch(const std::exception&e){std::printf("TRAFFIC_ABORT reason=%s protocol_complete=0 direct_route_proven=0 rc=27\n",e.what());}
 if(kmsg_fd>=0)close(kmsg_fd);return rc;
}
