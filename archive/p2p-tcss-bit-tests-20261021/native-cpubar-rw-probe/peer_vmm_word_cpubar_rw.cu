#include <cuda_runtime.h>
#include <cuda.h>
#include <map>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <ctime>
#include <cerrno>
#include <fcntl.h>
#include <unistd.h>
#include "pcie_diag.h"
#include "cpubar_trace.h"
#include "cpubar_rw.h"
#define CK(x) do {auto e=(x);if(e!=cudaSuccess){printf("ERROR %s: %s (%d) line %d\n",#x,cudaGetErrorString(e),(int)e,__LINE__);fflush(stdout);exit(2);}}while(0)
#define CUCK(x) do{CUresult e=(x);if(e!=CUDA_SUCCESS){const char *m;cuGetErrorString(e,&m);printf("DRIVER ERROR %s: %s (%d) line %d\n",#x,m,(int)e,__LINE__);exit(7);}}while(0)
// Same four-byte kernels/data; synchronize each owner before remote access.
// Read-only PCIe snapshots; defer ALL GPU frees until all comparisons finish.
static int kmsg_fd = -1;
static void phase(const char *name, int s = -1, int d = -1) {
 struct timespec t;
 if (clock_gettime(CLOCK_MONOTONIC, &t) != 0) { perror("CLOCK_MONOTONIC"); exit(9); }
 char line[256];
 int n = snprintf(line, sizeof(line), "CaskLogicPeer phase=%s monotonic=%lld.%09ld s=%d d=%d\n", name, (long long)t.tv_sec, t.tv_nsec, s, d);
 fputs(line, stdout);
 if (kmsg_fd >= 0 && n > 0 && n < (int)sizeof(line)) {
   ssize_t written = write(kmsg_fd, line, (size_t)n);
   if (written != n) printf("KMSG_MARKER_FAILED errno=%d\n", errno);
 }
}
static void verify_owner_word(const char *stage, int owner, const unsigned *ptr, unsigned expected) {
 unsigned observed=0;
 CK(cudaMemcpy(&observed,ptr,sizeof(observed),cudaMemcpyDeviceToHost));
 printf("OWNER_CHECK stage=%s device=%d observed=%08x expected=%08x valid=%d\n",stage,owner,observed,expected,observed==expected);
 if(observed!=expected){phase("owner_validation_failed",owner,-1);exit(10);}
}
std::map<unsigned*,std::pair<CUmemGenericAllocationHandle,size_t>> allocations;
std::vector<std::pair<unsigned*,int>> pending_frees;
// CPU diagnostic metadata belongs only to the current allocation lifetime.
struct CpuBarMeta { cpubar::Query query; cpubar::Identity owner; bool ready=false; std::string reason; };
static std::map<unsigned*,CpuBarMeta> cpu_meta;
static unsigned long long cpu_allocation_id=0;
static unsigned cpu_checks_pass=0,cpu_checks_fail=0,cpu_checks_skip=0;
static std::string cuda_uuid(int dev) {
 CUdevice cd;CUuuid id;CUCK(cuDeviceGet(&cd,dev));CUCK(cuDeviceGetUuid(&id,cd));
 char b[64];const auto*u=reinterpret_cast<const unsigned char*>(id.bytes);
 snprintf(b,sizeof(b),"GPU-%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",u[0],u[1],u[2],u[3],u[4],u[5],u[6],u[7],u[8],u[9],u[10],u[11],u[12],u[13],u[14],u[15]);return b;
}
static std::string cuda_bdf(int dev) {char b[64]={};CK(cudaDeviceGetPCIBusId(b,sizeof(b),dev));std::string s=b;for(char&c:s)c=static_cast<char>(std::tolower(static_cast<unsigned char>(c)));return s;}
static bool cpu_marker(const std::string&line) {
 printf("%s\n",line.c_str());if(kmsg_fd<0)return false;const std::string record=line+"\n";
 return write(kmsg_fd,record.data(),record.size())==static_cast<ssize_t>(record.size());
}
static CpuBarMeta cpu_begin(int dev,CUdeviceptr va,size_t size) {
 CpuBarMeta m;m.query.va=va;m.query.size=size;m.query.owner_bdf=cuda_bdf(dev);m.query.requester_bdf=cuda_bdf(1-dev);
 m.query.owner_uuid=cuda_uuid(dev);m.query.requester_uuid=cuda_uuid(1-dev);
 cpubar::Identity requester;
 if(!cpubar::identity(m.query.owner_bdf,m.query.owner_uuid,m.owner,m.reason)||!cpubar::identity(m.query.requester_bdf,m.query.requester_uuid,requester,m.reason))return m;
 std::ifstream f("/proc/sys/kernel/random/uuid");std::string nonce;
 if(!std::getline(f,nonce)||!cpubar::uuid_ok("GPU-"+nonce)){m.reason="fresh_nonce_unavailable";return m;}
 std::ostringstream prefix;prefix<<"CaskLogicCPUBAR token="<<nonce<<" alloc="<<++cpu_allocation_id;
 m.query.begin=prefix.str()+" phase=begin";m.query.end=prefix.str()+" phase=end";
 printf("CPUBAR_ALLOCATION token=%s owner=%d owner_bdf=%s owner_uuid=%s requester_bdf=%s requester_uuid=%s gpu_va=%llx size=%llx useful=4\n",nonce.c_str(),dev,m.query.owner_bdf.c_str(),m.query.owner_uuid.c_str(),m.query.requester_bdf.c_str(),m.query.requester_uuid.c_str(),(unsigned long long)va,(unsigned long long)size);
 m.ready=cpu_marker(m.query.begin);if(!m.ready)m.reason="begin_marker_write_failed";return m;
}
static bool current_window(const CpuBarMeta&m,cpubar::Window&w,std::string&error) {
 std::string log;if(!cpubar::read_kernel_log(log,error))return false;
 return cpubar::resolve(log,m.query,w,error);
}
static bool same_window(const cpubar::Window&a,const cpubar::Window&b) {
 return a.id==b.id&&a.offset==b.offset&&a.physical==b.physical&&a.dma==b.dma&&a.bar==b.bar&&a.bar_size==b.bar_size&&a.size==b.size;
}
static void cpu_bar_check(unsigned*ptr,int owner) {
 auto it=cpu_meta.find(ptr);std::string error;
 if(it==cpu_meta.end()||!it->second.ready){printf("CPUBAR_RESULT owner=%d gpu_va=%p status=SKIP reason=%s\n",owner,(void*)ptr,it==cpu_meta.end()?"metadata_missing":it->second.reason.c_str());++cpu_checks_skip;return;}
 const CpuBarMeta&m=it->second;cpubar::Window w;cpubar::ReadOnlyWord word;
 if(!current_window(m,w,error)||!word.open(m.owner,w,error)){printf("CPUBAR_RESULT owner=%d gpu_va=%p status=SKIP reason=%s\n",owner,(void*)ptr,error.c_str());++cpu_checks_skip;return;}
 printf("CPUBAR_MATCH owner=%d bdf=%s gpu_va=%llx window_id=%llu bar=%llx bar_offset=%llx physical=%llx dma=%llx mapping=O_RDONLY_PROT_READ\n",owner,m.owner.bdf.c_str(),(unsigned long long)m.query.va,(unsigned long long)w.id,(unsigned long long)w.bar,(unsigned long long)w.offset,(unsigned long long)w.physical,(unsigned long long)w.dma);
 CK(cudaSetDevice(owner));bool good=true,complete=true;const uint32_t patterns[2]={0x00003039u,0x6b2d91e7u};
 for(unsigned i=0;i<2;++i){
  CK(cudaMemcpy(ptr,&patterns[i],sizeof(patterns[i]),cudaMemcpyHostToDevice));CK(cudaDeviceSynchronize());verify_owner_word(i?"cpubar_pattern_2":"cpubar_pattern_1",owner,ptr,patterns[i]);
  cpubar::Window current;cpubar::Identity identity;
  if(!current_window(m,current,error)||!same_window(w,current)||!cpubar::identity(m.owner.bdf,m.owner.uuid,identity,error)||!cpubar::same_identity(identity,m.owner)){
   if(error.empty())error="mapping_or_identity_changed";complete=false;break;
  }
  phase(i?"cpubar_read_2_begin":"cpubar_read_1_begin",owner,-1);pcie_snapshot(i?"cpubar_read_2_before":"cpubar_read_1_before");uint32_t observed=0;
  bool ok=word.read(observed,error);pcie_snapshot(i?"cpubar_read_2_after":"cpubar_read_1_after");phase(i?"cpubar_read_2_done":"cpubar_read_1_done",owner,-1);
  if(!ok){complete=false;break;}
  printf("CPUBAR_READ owner=%d window_id=%llu pattern=%u observed=%08x expected=%08x valid=%d\n",owner,(unsigned long long)w.id,i+1,observed,patterns[i],observed==patterns[i]);good=good&&(observed==patterns[i]);
 }
 word.close();const uint32_t restore=12345u;CK(cudaMemcpy(ptr,&restore,sizeof(restore),cudaMemcpyHostToDevice));CK(cudaDeviceSynchronize());verify_owner_word("cpubar_restored",owner,ptr,restore);
 printf("CPUBAR_RESULT owner=%d gpu_va=%p status=%s reason=%s restored=1\n",owner,(void*)ptr,!complete?"SKIP":good?"PASS":"FAIL",!complete?error.c_str():good?"two_patterns_match":"word_mismatch");
 if(!complete)++cpu_checks_skip;else if(good)++cpu_checks_pass;else ++cpu_checks_fail;
}

// Observe the still-live target through the CPU BAR immediately after the writer
// completes. No CUDA call, owner initialization, or MMIO write in this function.
static unsigned cpu_post_pass=0,cpu_post_fail=0,cpu_post_skip=0;
static void cpu_bar_postwrite(unsigned*ptr,int owner,int writer,uint32_t expected) {
 auto it=cpu_meta.find(ptr);std::string error;
 auto skip=[&](const std::string&why){
  printf("CPUBAR_POSTWRITE owner=%d writer=%d gpu_va=%p observed=unavailable expected=%08x status=SKIP reason=%s\n",owner,writer,(void*)ptr,expected,why.c_str());
  ++cpu_post_skip;
 };
 if(it==cpu_meta.end()||!it->second.ready){skip(it==cpu_meta.end()?"metadata_missing":it->second.reason);return;}
 const CpuBarMeta&m=it->second;cpubar::Window w,current;cpubar::Identity identity;cpubar::ReadOnlyWord word;
 if(!current_window(m,w,error)||!word.open(m.owner,w,error)){skip(error);return;}
 // Revalidate the current nonce/handle/window chain and GPU identity after mmap.
 if(!current_window(m,current,error)||!same_window(w,current)||!cpubar::identity(m.owner.bdf,m.owner.uuid,identity,error)||!cpubar::same_identity(identity,m.owner)){
  if(error.empty())error="mapping_or_identity_changed";word.close();skip(error);return;
 }
 char before[64],after[64];
 snprintf(before,sizeof(before),"cpubar_postwrite_owner_%d_before",owner);
 snprintf(after,sizeof(after),"cpubar_postwrite_owner_%d_after",owner);
 phase("cpubar_postwrite_begin",owner,writer);pcie_snapshot(before);
 uint32_t observed=0;bool read_ok=word.read(observed,error);
 pcie_snapshot(after);phase("cpubar_postwrite_done",owner,writer);word.close();
 if(!read_ok){skip(error);return;}
 const bool valid=observed==expected;
 printf("CPUBAR_POSTWRITE owner=%d writer=%d bdf=%s gpu_va=%p window_id=%llu physical=%llx observed=%08x expected=%08x valid=%d status=%s mapping=O_RDONLY_PROT_READ\n",owner,writer,m.owner.bdf.c_str(),(void*)ptr,(unsigned long long)w.id,(unsigned long long)w.physical,observed,expected,valid,valid?"PASS":"FAIL");
 if(valid)++cpu_post_pass;else ++cpu_post_fail;
}

#include "cpubar_rw_control.inc"

void alloc_peer(unsigned **p,size_t bytes,int dev){
 CUmemAllocationProp prop={};prop.type=CU_MEM_ALLOCATION_TYPE_PINNED;prop.location.type=CU_MEM_LOCATION_TYPE_DEVICE;prop.location.id=dev;
 size_t gran;CUCK(cuMemGetAllocationGranularity(&gran,&prop,CU_MEM_ALLOC_GRANULARITY_MINIMUM));size_t size=((bytes+gran-1)/gran)*gran;
 CUdeviceptr address;CUmemGenericAllocationHandle handle;CUCK(cuMemAddressReserve(&address,size,0,0,0));CpuBarMeta meta=cpu_begin(dev,address,size);CUCK(cuMemCreate(&handle,size,&prop,0));CUCK(cuMemMap(address,size,0,handle,0));
 CUmemAccessDesc access[2]={};for(int i=0;i<2;i++){access[i].location.type=CU_MEM_LOCATION_TYPE_DEVICE;access[i].location.id=i;access[i].flags=CU_MEM_ACCESS_FLAGS_PROT_READWRITE;}
 CUCK(cuMemSetAccess(address,size,access,2));if(meta.ready&&!cpu_marker(meta.query.end)){meta.ready=false;meta.reason="end_marker_write_failed";}*p=(unsigned*)address;allocations[*p]={handle,size};cpu_meta[*p]=meta;
}
void free_peer(unsigned *p){auto v=allocations.at(p);CUCK(cuMemUnmap((CUdeviceptr)p,v.second));CUCK(cuMemRelease(v.first));CUCK(cuMemAddressFree((CUdeviceptr)p,v.second));allocations.erase(p);}
__global__ void peer_read(const volatile unsigned *src,unsigned *dst,size_t n){for(size_t i=blockIdx.x*blockDim.x+threadIdx.x;i<n;i+=gridDim.x*blockDim.x)dst[i]=src[i]^0x12345678u;}
__global__ void peer_write(volatile unsigned *dst,size_t n,unsigned seed){for(size_t i=blockIdx.x*blockDim.x+threadIdx.x;i<n;i+=gridDim.x*blockDim.x)dst[i]=((unsigned)i*1664525u+seed)^0xa5a5a5a5u;__threadfence_system();}
int main(){int failures=0;setbuf(stdout,NULL);kmsg_fd=open("/dev/kmsg",O_WRONLY|O_CLOEXEC);if(kmsg_fd<0)printf("KMSG_UNAVAILABLE errno=%d\n",errno);phase("program_start");int count=0;CK(cudaGetDeviceCount(&count));printf("GPU count %d\n",count);if(count!=2)return 3;pcie_snapshot("baseline");
for(int s=0;s<2;s++){int d=1-s,can=0;CK(cudaDeviceCanAccessPeer(&can,d,s));printf("PEER %d -> %d can %d\n",s,d,can);if(!can)return 4;CK(cudaSetDevice(d));}
for(size_t bytes:{size_t(4)})for(int s=0;s<2;s++){
 int d=1-s;size_t n=bytes/4;unsigned *src,*dst;std::vector<unsigned> h(n),out(n);for(size_t i=0;i<n;i++)h[i]=(unsigned)i*1103515245u+12345u;
 phase("mapping_begin",s,d);CK(cudaSetDevice(s));alloc_peer(&src,bytes,s);pending_frees.push_back({src,s});cpu_rw_targets.push_back({src,s});CK(cudaMemcpy(src,h.data(),bytes,cudaMemcpyHostToDevice));CK(cudaDeviceSynchronize());verify_owner_word("initialized",s,src,h[0]);cpu_bar_check(src,s);phase("owner_init_ready",s,d);CK(cudaSetDevice(d));alloc_peer(&dst,bytes,d);pending_frees.push_back({dst,d});CK(cudaMemset(dst,0,bytes));printf("PROBE_PTR s=%d d=%d src=%p dst=%p bytes=%zu\n",s,d,(void*)src,(void*)dst,bytes);phase("mapping_done",s,d);phase("read_begin",s,d);printf("START peer_read src %d dst %d bytes %zu\n",s,d,bytes);pcie_snapshot(s==0?"read_0_to_1_before":"read_1_to_0_before");peer_read<<<256,256>>>(src,dst,n);CK(cudaGetLastError());CK(cudaDeviceSynchronize());pcie_snapshot(s==0?"read_0_to_1_after":"read_1_to_0_after");CK(cudaMemcpy(out.data(),dst,bytes,cudaMemcpyDeviceToHost));bool good=true;for(size_t i=0;i<n;i++)if(out[i]!=(h[i]^0x12345678u)){printf("CORRUPTION read i %zu got %08x expected %08x\n",i,out[i],h[i]^0x12345678u);good=false;failures++;break;}printf("REMOTE_READ s=%d d=%d bytes=%zu valid=%d\n",s,d,bytes,good);phase("read_done",s,d);

 phase("write_begin",d,s);CK(cudaSetDevice(s));CK(cudaMemset(src,0,bytes));CK(cudaDeviceSynchronize());verify_owner_word("zeroed",s,src,0);phase("owner_zero_ready",s,d);CK(cudaSetDevice(d));printf("START peer_write src %d dst %d bytes %zu\n",d,s,bytes);pcie_snapshot(d==0?"write_0_to_1_before":"write_1_to_0_before");peer_write<<<256,256>>>(src,n,98765u);CK(cudaGetLastError());CK(cudaDeviceSynchronize());pcie_snapshot(d==0?"write_0_to_1_after":"write_1_to_0_after");cpu_bar_postwrite(src,s,d,98765u^0xa5a5a5a5u);CK(cudaSetDevice(s));CK(cudaMemcpy(out.data(),src,bytes,cudaMemcpyDeviceToHost));good=true;for(size_t i=0;i<n;i++)if(out[i]!=(((unsigned)i*1664525u+98765u)^0xa5a5a5a5u)){printf("CORRUPTION write i %zu got %08x\n",i,out[i]);good=false;failures++;break;}printf("REMOTE_WRITE s=%d d=%d bytes=%zu valid=%d\n",d,s,bytes,good);phase("write_done",d,s);}
printf("CPUBAR_POSTWRITE_SUMMARY pass=%u fail=%u skip=%u\n",cpu_post_pass,cpu_post_fail,cpu_post_skip);printf("CPUBAR_SUMMARY pass=%u fail=%u skip=%u\n",cpu_checks_pass,cpu_checks_fail,cpu_checks_skip);printf("TOTAL_FAILURES %d\n",failures);phase("data_done");
phase("cpu_rw_controls_begin");
for (auto item : cpu_rw_targets) cpu_bar_rw_check(item.first,item.second);
printf("CPUBAR_RW_SUMMARY pass=%u fail=%u skip=%u halted=%d p2p_failures_unchanged=%d\n",cpu_rw_pass,cpu_rw_fail,cpu_rw_skip,cpu_rw_halt,failures);
phase("cpu_rw_controls_done");
phase("cleanup_begin");
for (auto item : pending_frees) { phase("allocation_free_begin",item.second,-1);CK(cudaSetDevice(item.second));free_peer(item.first);phase("allocation_free_done",item.second,-1); }
pending_frees.clear();phase("cleanup_done");phase("context_exit_begin");
if(kmsg_fd>=0)close(kmsg_fd);return failures?5:0;}
