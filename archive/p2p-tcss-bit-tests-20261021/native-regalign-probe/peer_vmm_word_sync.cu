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
void alloc_peer(unsigned **p,size_t bytes,int dev){
 CUmemAllocationProp prop={};prop.type=CU_MEM_ALLOCATION_TYPE_PINNED;prop.location.type=CU_MEM_LOCATION_TYPE_DEVICE;prop.location.id=dev;
 size_t gran;CUCK(cuMemGetAllocationGranularity(&gran,&prop,CU_MEM_ALLOC_GRANULARITY_MINIMUM));size_t size=((bytes+gran-1)/gran)*gran;
 CUdeviceptr address;CUmemGenericAllocationHandle handle;CUCK(cuMemAddressReserve(&address,size,0,0,0));CUCK(cuMemCreate(&handle,size,&prop,0));CUCK(cuMemMap(address,size,0,handle,0));
 CUmemAccessDesc access[2]={};for(int i=0;i<2;i++){access[i].location.type=CU_MEM_LOCATION_TYPE_DEVICE;access[i].location.id=i;access[i].flags=CU_MEM_ACCESS_FLAGS_PROT_READWRITE;}
 CUCK(cuMemSetAccess(address,size,access,2));*p=(unsigned*)address;allocations[*p]={handle,size};
}
void free_peer(unsigned *p){auto v=allocations.at(p);CUCK(cuMemUnmap((CUdeviceptr)p,v.second));CUCK(cuMemRelease(v.first));CUCK(cuMemAddressFree((CUdeviceptr)p,v.second));allocations.erase(p);}
__global__ void peer_read(const volatile unsigned *src,unsigned *dst,size_t n){for(size_t i=blockIdx.x*blockDim.x+threadIdx.x;i<n;i+=gridDim.x*blockDim.x)dst[i]=src[i]^0x12345678u;}
__global__ void peer_write(volatile unsigned *dst,size_t n,unsigned seed){for(size_t i=blockIdx.x*blockDim.x+threadIdx.x;i<n;i+=gridDim.x*blockDim.x)dst[i]=((unsigned)i*1664525u+seed)^0xa5a5a5a5u;__threadfence_system();}
int main(){int failures=0;setbuf(stdout,NULL);kmsg_fd=open("/dev/kmsg",O_WRONLY|O_CLOEXEC);if(kmsg_fd<0)printf("KMSG_UNAVAILABLE errno=%d\n",errno);phase("program_start");int count=0;CK(cudaGetDeviceCount(&count));printf("GPU count %d\n",count);if(count!=2)return 3;pcie_snapshot("baseline");
for(int s=0;s<2;s++){int d=1-s,can=0;CK(cudaDeviceCanAccessPeer(&can,d,s));printf("PEER %d -> %d can %d\n",s,d,can);if(!can)return 4;CK(cudaSetDevice(d));}
for(size_t bytes:{size_t(4)})for(int s=0;s<2;s++){
 int d=1-s;size_t n=bytes/4;unsigned *src,*dst;std::vector<unsigned> h(n),out(n);for(size_t i=0;i<n;i++)h[i]=(unsigned)i*1103515245u+12345u;
 phase("mapping_begin",s,d);CK(cudaSetDevice(s));alloc_peer(&src,bytes,s);pending_frees.push_back({src,s});CK(cudaMemcpy(src,h.data(),bytes,cudaMemcpyHostToDevice));CK(cudaDeviceSynchronize());verify_owner_word("initialized",s,src,h[0]);phase("owner_init_ready",s,d);CK(cudaSetDevice(d));alloc_peer(&dst,bytes,d);pending_frees.push_back({dst,d});CK(cudaMemset(dst,0,bytes));printf("PROBE_PTR s=%d d=%d src=%p dst=%p bytes=%zu\n",s,d,(void*)src,(void*)dst,bytes);phase("mapping_done",s,d);phase("read_begin",s,d);printf("START peer_read src %d dst %d bytes %zu\n",s,d,bytes);pcie_snapshot(s==0?"read_0_to_1_before":"read_1_to_0_before");peer_read<<<256,256>>>(src,dst,n);CK(cudaGetLastError());CK(cudaDeviceSynchronize());pcie_snapshot(s==0?"read_0_to_1_after":"read_1_to_0_after");CK(cudaMemcpy(out.data(),dst,bytes,cudaMemcpyDeviceToHost));bool good=true;for(size_t i=0;i<n;i++)if(out[i]!=(h[i]^0x12345678u)){printf("CORRUPTION read i %zu got %08x expected %08x\n",i,out[i],h[i]^0x12345678u);good=false;failures++;break;}printf("REMOTE_READ s=%d d=%d bytes=%zu valid=%d\n",s,d,bytes,good);phase("read_done",s,d);

 phase("write_begin",d,s);CK(cudaSetDevice(s));CK(cudaMemset(src,0,bytes));CK(cudaDeviceSynchronize());verify_owner_word("zeroed",s,src,0);phase("owner_zero_ready",s,d);CK(cudaSetDevice(d));printf("START peer_write src %d dst %d bytes %zu\n",d,s,bytes);pcie_snapshot(d==0?"write_0_to_1_before":"write_1_to_0_before");peer_write<<<256,256>>>(src,n,98765u);CK(cudaGetLastError());CK(cudaDeviceSynchronize());pcie_snapshot(d==0?"write_0_to_1_after":"write_1_to_0_after");CK(cudaSetDevice(s));CK(cudaMemcpy(out.data(),src,bytes,cudaMemcpyDeviceToHost));good=true;for(size_t i=0;i<n;i++)if(out[i]!=(((unsigned)i*1664525u+98765u)^0xa5a5a5a5u)){printf("CORRUPTION write i %zu got %08x\n",i,out[i]);good=false;failures++;break;}printf("REMOTE_WRITE s=%d d=%d bytes=%zu valid=%d\n",d,s,bytes,good);phase("write_done",d,s);}
printf("TOTAL_FAILURES %d\n",failures);phase("data_done");
phase("cleanup_begin");
for (auto item : pending_frees) { phase("allocation_free_begin",item.second,-1);CK(cudaSetDevice(item.second));free_peer(item.first);phase("allocation_free_done",item.second,-1); }
pending_frees.clear();phase("cleanup_done");phase("context_exit_begin");
if(kmsg_fd>=0)close(kmsg_fd);return failures?5:0;}
