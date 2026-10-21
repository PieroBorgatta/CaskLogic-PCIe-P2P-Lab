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
#include "cupti_trace.h"
#include "payload_capture.h"
#include <stdexcept>
#include <string>

// CPU initializes and checks each owner. The unchanged transfer kernel uses
// local source / peer target for PUSH, peer source / local target for PULL.
// Its legacy symbol is retained so its generated operation remains comparable.
__global__ void peer_push_kernel(const uint32_t *local_source,
                                 volatile uint32_t *peer_destination,
                                 size_t words) {
    bool wrote = false;
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
        std::exit(20);
    }
    return uint64_t(t.tv_sec) * 1000000000ULL + uint64_t(t.tv_nsec);
}
static void phase(const char *name, int source=-1, int destination=-1) {
    const uint64_t ns = ns_now();
    char line[256];
    const int n = std::snprintf(line, sizeof(line),
        "CaskLogicCE phase=%s monotonic=%llu.%09llu s=%d d=%d\n",
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
    std::exit(21);
}
static void driver_check(CUresult value, const char *call, int line) {
    if (value == CUDA_SUCCESS) return;
    const char *message = "unknown";
    cuGetErrorString(value, &message);
    std::printf("DRIVER_ERROR call=%s line=%d code=%d error=%s\n", call, line, int(value), message);
    phase("driver_error");
    std::exit(22);
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
    int mode = -1;
};
static constexpr size_t MAX_BYTES = 8ULL * 1024 * 1024;
static Buffer buffers[2];
static const char *mode_name(int mode){if(mode<0 || mode>2)throw std::runtime_error("mode_range");return mode==2?"SHARED":mode==0?"PUSH":"PULL";}
static bool shared_buffer(const Buffer &b){return b.mode==2 && !std::strcmp(b.role,"shared");}

static void allocation_marker(const char *nonce,const char *stage,const Buffer &b){
 char line[512];const int n=std::snprintf(line,sizeof(line),"CaskLogicCEAllocation nonce=%s stage=%s owner=%d mode=%s role=%s va=%llx bytes=%zu\n",nonce,stage,b.owner,mode_name(b.mode),b.role,(unsigned long long)b.address,b.allocation_bytes);
 std::fputs(line,stdout);if(kmsg_fd<0 || n<=0 || size_t(n)>=sizeof(line) || write(kmsg_fd,line,size_t(n))!=n)throw std::runtime_error("allocation_marker_failed");
}
static void verify_mapping(const Buffer &b,const char *stage){
 CUmemAllocationProp p{};CUCK(cuMemGetAllocationPropertiesFromHandle(&p,b.handle));
 bool prop_ok=p.type==CU_MEM_ALLOCATION_TYPE_PINNED && p.location.type==CU_MEM_LOCATION_TYPE_DEVICE && p.location.id==b.owner;
 if(!prop_ok)throw std::runtime_error("allocation_property_changed");
 for(int i=0;i<2;++i){CUmemLocation loc{};loc.type=CU_MEM_LOCATION_TYPE_DEVICE;loc.id=i;
  unsigned long long first=0,last=0;CUCK(cuMemGetAccess(&first,&loc,b.address));CUCK(cuMemGetAccess(&last,&loc,b.address+b.allocation_bytes-1));
  unsigned long long expected=(!shared_buffer(b) && i!=b.owner)?CU_MEM_ACCESS_FLAGS_PROT_NONE:CU_MEM_ACCESS_FLAGS_PROT_READWRITE;
  std::printf("CE_ACCESS stage=%s owner=%d mode=%s role=%s device=%d va=%llx last_va=%llx first=%llu last=%llu expected=%llu allocation_type=%d location_type=%d location_id=%d valid=%d\n",stage,b.owner,mode_name(b.mode),b.role,i,(unsigned long long)b.address,(unsigned long long)(b.address+b.allocation_bytes-1),first,last,expected,int(p.type),int(p.location.type),p.location.id,first==expected && last==expected);
  if(first!=expected || last!=expected)throw std::runtime_error("vmm_access_mismatch");
 }
}
static void allocate(Buffer &buffer,int owner,int mode,const char *role){
 CK(cudaSetDevice(owner));CUmemAllocationProp prop{};prop.type=CU_MEM_ALLOCATION_TYPE_PINNED;prop.location.type=CU_MEM_LOCATION_TYPE_DEVICE;prop.location.id=owner;
 CUCK(cuMemGetAllocationGranularity(&buffer.granularity,&prop,CU_MEM_ALLOC_GRANULARITY_MINIMUM));
 if(!buffer.granularity || MAX_BYTES%buffer.granularity)throw std::runtime_error("allocation_granularity");
 buffer.owner=owner;buffer.mode=mode;buffer.role=role;buffer.allocation_bytes=MAX_BYTES;
 CUCK(cuMemAddressReserve(&buffer.address,MAX_BYTES,0,0,0));CUCK(cuMemCreate(&buffer.handle,MAX_BYTES,&prop,0));CUCK(cuMemMap(buffer.address,MAX_BYTES,0,buffer.handle,0));
 char nonce[64]{};FILE *file=std::fopen("/proc/sys/kernel/random/uuid","r");if(!file || !std::fgets(nonce,sizeof(nonce),file)){if(file)std::fclose(file);throw std::runtime_error("allocation_nonce");}std::fclose(file);nonce[std::strcspn(nonce,"\r\n")]=0;if(std::strlen(nonce)!=36)throw std::runtime_error("nonce_length");
 allocation_marker(nonce,"begin",buffer);
 CUmemAccessDesc access[2]{};for(int i=0;i<2;++i){access[i].location.type=CU_MEM_LOCATION_TYPE_DEVICE;access[i].location.id=i;access[i].flags=(!shared_buffer(buffer) && i!=owner)?CU_MEM_ACCESS_FLAGS_PROT_NONE:CU_MEM_ACCESS_FLAGS_PROT_READWRITE;}
 CUCK(cuMemSetAccess(buffer.address,MAX_BYTES,access,2));
 allocation_marker(nonce,"end",buffer);
 std::printf("CE_ALLOCATION nonce=%s owner=%d mode=%s role=%s va=%llx handle=%llx allocation_bytes=%zu granularity=%zu\n",nonce,owner,mode_name(mode),role,(unsigned long long)buffer.address,(unsigned long long)buffer.handle,MAX_BYTES,buffer.granularity);
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
        std::exit(24);
    }
}

static void sync_both(){for(int i=0;i<2;++i){CK(cudaSetDevice(i));CK(cudaDeviceSynchronize());}}
static void check_identity(int i){
 const char *expected_bdf[2]={"0000:01:00.0","0000:06:00.0"};
 const char *expected_uuid[2]={std::getenv("CASKLOGIC_GPU0_UUID"),std::getenv("CASKLOGIC_GPU1_UUID")};
 for(const char* uuid:expected_uuid) if(!uuid || std::strlen(uuid)!=32 || std::strspn(uuid,"0123456789abcdef")!=32) throw std::runtime_error("expected_gpu_uuid_required");
 char bdf[32]{},uuid[33]{};cudaDeviceProp p{};CK(cudaGetDeviceProperties(&p,i));CK(cudaDeviceGetPCIBusId(bdf,sizeof(bdf),i));
 for(int j=0;j<16;++j)std::snprintf(uuid+2*j,3,"%02x",static_cast<unsigned char>(p.uuid.bytes[j]));
 bool valid=std::strcmp(bdf,expected_bdf[i])==0 && std::strcmp(uuid,expected_uuid[i])==0;
 std::printf("CE_GPU index=%d bdf=%s uuid=%s name=%s valid=%d\n",i,bdf,uuid,p.name,valid);
 if(!valid)throw std::runtime_error("gpu_identity_mismatch");
}
static int run(payload_capture::Capture& capture){
 ce_trace::initialize();CUCK(cuInit(0));int count=0;CK(cudaGetDeviceCount(&count));if(count!=2)throw std::runtime_error("gpu_count");
 CUcontext contexts[2]{};CUstream streams[2]{};
 for(int i=0;i<2;++i){CK(cudaSetDevice(i));CK(cudaFree(nullptr));CK(cudaDeviceSynchronize());check_identity(i);CUCK(cuCtxGetCurrent(&contexts[i]));if(!contexts[i])throw std::runtime_error("missing_context");CUCK(cuStreamCreate(&streams[i],CU_STREAM_NON_BLOCKING));}
 sync_both();pcie_snapshot("ce_program_baseline");phase("allocations_begin");
 for(int i=0;i<2;++i)allocate(buffers[i],i,2,"shared");
 sync_both();phase("allocations_done");
 std::vector<uint32_t> expected(MAX_BYTES/4),poison(MAX_BYTES/4),observed(MAX_BYTES/4);
 const size_t sizes[]={4,65536,1048576};unsigned failures=0,comparisons=0;uint64_t id=0;
 std::printf("SA_PROTOCOL name=same-allocation-bracket-v1 allocations=2 comparisons=36 groups=12\n");
 unsigned group=0;
 for(int executor : {1,0})for(size_t bytes:sizes)for(bool ce : {true,false}){
  ++group;
  const size_t words=bytes/4;
  const uint32_t base_seed=0x6b8b4567u^uint32_t(bytes)^(0x13579bdfu*uint32_t(executor+1))^(ce?0u:0x2468ace0u);
  std::printf("SA_GROUP_BEGIN group=%u executor=%d engine=%s bytes=%zu base_seed=%08x first_case=%llu\n",group,executor,ce?"CE_REQUEST":"SM",bytes,base_seed,(unsigned long long)(id+1));
  for(int step=0;step<3;++step){
   ++id;const int mode=step==1?1:0;
   const char*step_name=step==0?"PUSH_BEFORE":step==1?"PULL":"PUSH_AFTER";
   const int source=mode==0?executor:1-executor,destination=1-source;
   const uint32_t seed=base_seed^(uint32_t(id)*0x9e3779b9u);
   for(size_t j=0;j<words;++j){expected[j]=word_pattern(j,seed);poison[j]=~expected[j];}
    sync_both();check_identity(source);check_identity(destination);
    verify_mapping(buffers[source],"before_case");verify_mapping(buffers[destination],"before_case");
    std::printf("SA_CASE id=%llu group=%u step=%s buffer0=%llx buffer1=%llx handle0=%llx handle1=%llx\n",(unsigned long long)id,group,step_name,(unsigned long long)buffers[0].address,(unsigned long long)buffers[1].address,(unsigned long long)buffers[0].handle,(unsigned long long)buffers[1].handle);
    std::printf("CE_CASE id=%llu engine=%s mode=%s executor=%d s=%d d=%d bytes=%zu seed=%08x src=%llx dst=%llx allocations_unchanged=1\n",(unsigned long long)id,ce?"CE_REQUEST":"SM",mode_name(mode),executor,source,destination,bytes,seed,(unsigned long long)buffers[source].address,(unsigned long long)buffers[destination].address);
    init_and_verify(buffers[source],expected,observed,bytes,"source_initialized",source,destination,int(id));
    init_and_verify(buffers[destination],poison,observed,bytes,"destination_poisoned",source,destination,int(id));
    sync_both();phase("owners_ready",source,destination);CK(cudaSetDevice(executor));
    CUcontext current=nullptr,stream_context=nullptr;CUdevice current_device=-1;
    CUCK(cuCtxGetCurrent(&current));CUCK(cuCtxGetDevice(&current_device));CUCK(cuStreamGetCtx(streams[executor],&stream_context));
    if(current!=contexts[executor] || stream_context!=contexts[executor] || int(current_device)!=executor)throw std::runtime_error("executor_context_mismatch");
    std::printf("CE_EXECUTOR id=%llu device=%d current=%p stream_context=%p stream=%p valid=1\n",(unsigned long long)id,executor,(void*)current,(void*)stream_context,(void*)streams[executor]);
    char label[80];std::snprintf(label,sizeof(label),"ce_case_%llu_before",(unsigned long long)id);pcie_snapshot(label);phase("transfer_begin",source,destination);
    ce_trace::begin(id,ce,source,destination,executor,mode_name(mode),contexts[executor],contexts[source],contexts[destination],streams[executor],buffers[source].address,buffers[destination].address,bytes);
    if(ce){CUCK(cuMemcpyDtoDAsync(buffers[destination].address,buffers[source].address,bytes,streams[executor]));}
    else {unsigned blocks=unsigned(std::min<size_t>(256,(words+255)/256));peer_push_kernel<<<blocks,256,0,reinterpret_cast<cudaStream_t>(streams[executor])>>>(reinterpret_cast<const uint32_t*>(buffers[source].address),reinterpret_cast<volatile uint32_t*>(buffers[destination].address),words);CK(cudaGetLastError());}
    CUCK(cuStreamSynchronize(streams[executor]));ce_trace::end(id);phase("transfer_complete",source,destination);
    std::snprintf(label,sizeof(label),"ce_case_%llu_after",(unsigned long long)id);pcie_snapshot(label);
    CK(cudaSetDevice(destination));CK(cudaMemcpy(observed.data(),reinterpret_cast<void*>(buffers[destination].address),bytes,cudaMemcpyDeviceToHost));CK(cudaDeviceSynchronize());
    size_t mismatch=compare(observed,expected,words,"peer_payload",destination,source,destination,bytes,int(id));++comparisons;failures+=mismatch!=0;
    auto captured=capture.save(id,ce,mode_name(mode),source,destination,executor,bytes,seed,buffers[source].address,buffers[destination].address,observed,expected,poison);
    if(captured.sentinel+captured.other!=mismatch)throw std::runtime_error("payload_capture_compare_mismatch");
    std::printf("CE_DATA_RESULT id=%llu engine=%s mode=%s executor=%d s=%d d=%d bytes=%zu checked_words=%zu mismatches=%zu valid=%d direct_route_proven=0\n",(unsigned long long)id,ce?"CE_REQUEST":"SM",mode_name(mode),executor,source,destination,bytes,words,mismatch,mismatch==0);
    verify_mapping(buffers[source],"after_case");verify_mapping(buffers[destination],"after_case");phase("comparison_done",source,destination);
  }
  std::printf("SA_GROUP_END group=%u last_case=%llu\n",group,(unsigned long long)id);
 }
 sync_both();phase("data_done");ce_trace::Summary trace=ce_trace::finish();
 if(comparisons!=36 || trace.ce_cases!=18)throw std::runtime_error("comparison_count");
 for(int i=0;i<2;++i)release(buffers[i]);
 for(int i=0;i<2;++i){CK(cudaSetDevice(i));CUCK(cuStreamDestroy(streams[i]));}
 phase("cleanup_done");int rc=(!trace.complete || trace.ce_observed!=18 || trace.sm_observed!=18)?6:(failures?5:0);
 std::printf("CE_PROGRAM_END protocol_complete=1 comparisons=%u failures=%u trace_complete=%d ce_cases=%u ce_observed=%u sm_observed=%u dropped=%llu trace_errors=%u direct_route_proven=0 rc=%d\n",comparisons,failures,trace.complete,trace.ce_cases,trace.ce_observed,trace.sm_observed,(unsigned long long)trace.dropped,trace.errors,rc);
 phase("context_exit_begin");return rc;
}
int main(int argc,char** argv){
 setbuf(stdout,nullptr);kmsg_fd=open("/dev/kmsg",O_WRONLY|O_CLOEXEC);int rc=27;
 try{if(argc!=2)throw std::runtime_error("usage_peer_same_allocation_NEW_OUTPUT_DIRECTORY");payload_capture::Capture capture(argv[1]);phase("program_start");if(kmsg_fd<0)throw std::runtime_error("kmsg_required");rc=run(capture);}
 catch(const std::exception&e){std::printf("CE_ABORT reason=%s protocol_complete=0 direct_route_proven=0\n",e.what());}
 if(kmsg_fd>=0)close(kmsg_fd);return rc;
}
