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
#include "protocol.h"
#include "phys_pull_client.h"
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
        "CaskLogicPhysicalPull phase=%s monotonic=%llu.%09llu s=%d d=%d\n",
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
    std::printf("PHYS_FREE owner=%d va=%llx handle=%llx valid=1\n",buffer.owner,(unsigned long long)buffer.address,(unsigned long long)buffer.handle);
}

static void sync_both(){for(int i=0;i<2;++i){CK(cudaSetDevice(i));CK(cudaDeviceSynchronize());}}
static uint8_t gpu_uuids[2][16]{};
static void check_identity(int i){
 const char *expected_bdf[2]={"0000:01:00.0","0000:06:00.0"};
 const char *expected_uuid[2]={std::getenv("CASKLOGIC_GPU0_UUID"),std::getenv("CASKLOGIC_GPU1_UUID")};
 for(const char* uuid:expected_uuid)if(!uuid || std::strlen(uuid)!=32 || std::strspn(uuid,"0123456789abcdef")!=32)throw std::runtime_error("expected_gpu_uuid_required");
 char bdf[32]{},uuid[33]{};cudaDeviceProp p{};CK(cudaGetDeviceProperties(&p,i));CK(cudaDeviceGetPCIBusId(bdf,sizeof(bdf),i));
 for(int j=0;j<16;++j){gpu_uuids[i][j]=static_cast<uint8_t>(p.uuid.bytes[j]);std::snprintf(uuid+2*j,3,"%02x",gpu_uuids[i][j]);}
 bool valid=std::strcmp(bdf,expected_bdf[i])==0 && std::strcmp(uuid,expected_uuid[i])==0;
 std::printf("CE_GPU index=%d bdf=%s uuid=%s name=%s valid=%d\n",i,bdf,uuid,p.name,valid);
 if(!valid)throw std::runtime_error("gpu_identity_mismatch");
}
static uint32_t owner_read(const Buffer&b){uint32_t value=0;CK(cudaSetDevice(b.owner));CK(cudaMemcpy(&value,(void*)b.address,4,cudaMemcpyDeviceToHost));CK(cudaDeviceSynchronize());return value;}
static void init(const Buffer&b,uint32_t value,unsigned id,const char*role){
 CK(cudaSetDevice(b.owner));CK(cudaMemcpy((void*)b.address,&value,4,cudaMemcpyHostToDevice));CK(cudaDeviceSynchronize());
 const uint32_t got=owner_read(b);std::printf("PHYS_INIT id=%u role=%s owner=%d va=%llx bytes=4 expected=%08x actual=%08x valid=%d\n",id,role,b.owner,(unsigned long long)b.address,value,got,value==got);
 if(value!=got)throw std::runtime_error("owner_initialization_failed");
}
static int run(){
 namespace protocol=physical_pull_protocol;
 phys_pull::native_identity();CUCK(cuInit(0));int count=0;CK(cudaGetDeviceCount(&count));if(count!=2)throw std::runtime_error("gpu_count");
 CUcontext contexts[2]{};CUstream streams[2]{};
 for(int i=0;i<2;++i){CK(cudaSetDevice(i));CK(cudaFree(nullptr));CK(cudaDeviceSynchronize());check_identity(i);CUCK(cuCtxGetCurrent(&contexts[i]));if(!contexts[i])throw std::runtime_error("missing_context");CUCK(cuStreamCreate(&streams[i],CU_STREAM_NON_BLOCKING));}
 sync_both();pcie_snapshot("physical_pull_program_baseline");phase("allocations_begin");
 for(int i=0;i<2;++i)allocate(buffers[i],i,2,"shared");
 sync_both();phase("allocations_done");
 const uint64_t request_base=ns_now();if(!request_base || request_base>UINT64_MAX-protocol::CASES)throw std::runtime_error("request_base_range");
 phys_pull::Client client;
 client.discover(phys_pull::request(CASK_PHYS_CE_VALIDATE,request_base,gpu_uuids[1],gpu_uuids[0],gpu_uuids[1],buffers[1].address,buffers[0].address,CASK_PHYS_CE_PUSH,CASK_PHYS_CE_REMOTE_NONCOHERENT));
 std::printf("PHYS_PROTOCOL name=physical-source-bracket-v1 allocations=2 comparisons=12 groups=2 physical_cases=6 bytes=4 request_base=%llu cupti_used=0 vendor_supported_peer_read=0\n",(unsigned long long)request_base);
 unsigned failures=0,comparisons=0,physical_completed=0;
 for(unsigned id=1;id<=protocol::CASES;++id){
  const auto c=protocol::describe(id);const uint32_t expected=protocol::pattern(0,c.seed),sentinel=~expected;
  if(c.step==0)std::printf("PHYS_GROUP_BEGIN group=%u executor=%d first_case=%u\n",c.group,c.executor,id);
  sync_both();check_identity(c.source);check_identity(c.destination);verify_mapping(buffers[c.source],"before_case");verify_mapping(buffers[c.destination],"before_case");
  const uint64_t request_id=c.physical()?request_base+id:0;
  std::printf("PHYS_CASE id=%u group=%u step=%s engine=%s mode=%s executor=%d s=%d d=%d bytes=4 seed=%08x expected=%08x sentinel=%08x src=%llx dst=%llx buffer0=%llx buffer1=%llx handle0=%llx handle1=%llx request=%llu source_mode=%u destination_mode=%u allocations_unchanged=1\n",id,c.group,c.name,c.physical()?"UVM_PHYSICAL_CE":"SM",c.mode,c.executor,c.source,c.destination,c.seed,expected,sentinel,(unsigned long long)buffers[c.source].address,(unsigned long long)buffers[c.destination].address,(unsigned long long)buffers[0].address,(unsigned long long)buffers[1].address,(unsigned long long)buffers[0].handle,(unsigned long long)buffers[1].handle,(unsigned long long)request_id,c.source_mode,c.destination_mode);
  init(buffers[c.source],expected,id,"source");init(buffers[c.destination],sentinel,id,"destination");sync_both();phase("owners_ready",c.source,c.destination);CK(cudaSetDevice(c.executor));
  CUcontext current=nullptr,stream_context=nullptr;CUdevice current_device=-1;CUCK(cuCtxGetCurrent(&current));CUCK(cuCtxGetDevice(&current_device));CUCK(cuStreamGetCtx(streams[c.executor],&stream_context));
  if(current!=contexts[c.executor] || stream_context!=contexts[c.executor] || int(current_device)!=c.executor)throw std::runtime_error("executor_context_mismatch");
  std::printf("PHYS_EXECUTOR id=%u device=%d current=%p stream_context=%p stream=%p valid=1\n",id,c.executor,(void*)current,(void*)stream_context,(void*)streams[c.executor]);
  char label[96];std::snprintf(label,sizeof(label),"physical_pull_case_%u_before",id);pcie_snapshot(label);phase("transfer_begin",c.source,c.destination);
  if(c.physical()){
   const unsigned transfer=c.transfer==protocol::Transfer::PHYSICAL_PULL?CASK_PHYS_CE_PULL:CASK_PHYS_CE_PUSH;
   const unsigned remote_mode=transfer==CASK_PHYS_CE_PULL?c.source_mode:c.destination_mode;
   auto input=phys_pull::request(CASK_PHYS_CE_EXECUTE,request_id,gpu_uuids[c.source],gpu_uuids[c.destination],gpu_uuids[c.executor],buffers[c.source].address,buffers[c.destination].address,transfer,remote_mode);
   const auto result=client.execute(input,1-c.executor);(void)result;++physical_completed;
  }else{
   peer_push_kernel<<<1,1,0,reinterpret_cast<cudaStream_t>(streams[c.executor])>>>(reinterpret_cast<const uint32_t*>(buffers[c.source].address),reinterpret_cast<volatile uint32_t*>(buffers[c.destination].address),1);
   CK(cudaGetLastError());CUCK(cuStreamSynchronize(streams[c.executor]));
   std::printf("PHYS_SM_COMPLETE id=%u executor=%d src=%llx dst=%llx bytes=4 kernel=peer_push_kernel blocks=1 threads=1 stream_synchronized=1\n",id,c.executor,(unsigned long long)buffers[c.source].address,(unsigned long long)buffers[c.destination].address);
  }
  phase("transfer_complete",c.source,c.destination);std::snprintf(label,sizeof(label),"physical_pull_case_%u_after",id);pcie_snapshot(label);
  const uint32_t actual=owner_read(buffers[c.destination]),source_after=owner_read(buffers[c.source]);
  std::printf("PHYS_SOURCE_RECHECK id=%u owner=%d va=%llx bytes=4 expected=%08x actual=%08x valid=%d\n",id,c.source,(unsigned long long)buffers[c.source].address,expected,source_after,source_after==expected);
  if(source_after!=expected)throw std::runtime_error("source_changed_after_transfer");
  const bool passed=actual==expected;++comparisons;failures+=!passed;
  const char*kind=passed?"expected":actual==sentinel?"unchanged_sentinel":actual==0xffffffffU?"all_ones":"unexpected";
  std::printf("PHYS_DATA_RESULT id=%u engine=%s mode=%s executor=%d s=%d d=%d bytes=4 checked_words=1 expected=%08x sentinel=%08x actual=%08x mismatches=%u first_mismatch=%d last_mismatch=%d classification=%s valid=%d direct_route_proven=0\n",id,c.physical()?"UVM_PHYSICAL_CE":"SM",c.mode,c.executor,c.source,c.destination,expected,sentinel,actual,!passed,passed?-1:0,passed?-1:0,kind,passed);
  verify_mapping(buffers[c.source],"after_case");verify_mapping(buffers[c.destination],"after_case");phase("comparison_done",c.source,c.destination);
  if(c.step==5)std::printf("PHYS_GROUP_END group=%u last_case=%u\n",c.group,id);
 }
 sync_both();phase("data_done");if(comparisons!=12 || physical_completed!=6)throw std::runtime_error("comparison_count");
 for(int i=0;i<2;++i)release(buffers[i]);for(int i=0;i<2;++i){CK(cudaSetDevice(i));CUCK(cuStreamDestroy(streams[i]));}
 phase("cleanup_done");const int rc=failures?5:0;
 std::printf("PHYS_PROGRAM_END protocol_complete=1 comparisons=%u failures=%u physical_cases=6 physical_completed=%u sm_cases=6 source_preserved=12 initializations=24 allocations=2 direct_route_proven=0 vendor_supported_peer_read=0 rc=%d\n",comparisons,failures,physical_completed,rc);
 phase("context_exit_begin");return rc;
}
int main(int argc,char**argv){
 (void)argv;setbuf(stdout,nullptr);kmsg_fd=open("/dev/kmsg",O_WRONLY|O_CLOEXEC);int rc=27;
 try{if(argc!=1)throw std::runtime_error("usage_peer_physical_pull_no_arguments");phase("program_start");if(kmsg_fd<0)throw std::runtime_error("kmsg_required");rc=run();}
 catch(const std::exception&e){std::printf("PHYS_ABORT reason=%s protocol_complete=0 direct_route_proven=0\n",e.what());}
 if(kmsg_fd>=0)close(kmsg_fd);return rc;
}
