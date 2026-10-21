#include <cuda_runtime.h>
#include <cuda.h>
#include <map>
#include <cstdio>
#include <cstdlib>
#include <vector>
#define CK(x) do {auto e=(x);if(e!=cudaSuccess){printf("ERROR %s: %s (%d) line %d\n",#x,cudaGetErrorString(e),(int)e,__LINE__);fflush(stdout);exit(2);}}while(0)
#define CUCK(x) do{CUresult e=(x);if(e!=CUDA_SUCCESS){const char *m;cuGetErrorString(e,&m);printf("DRIVER ERROR %s: %s (%d) line %d\n",#x,m,(int)e,__LINE__);exit(7);}}while(0)
std::map<unsigned*,std::pair<CUmemGenericAllocationHandle,size_t>> allocations;
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
int main(){setbuf(stdout,NULL);int failures=0,count;CK(cudaGetDeviceCount(&count));if(count!=2)return 9;
for(int s=0;s<2;s++)for(int engine=0;engine<2;engine++){
 int d=1-s;size_t bytes=65536,n=bytes/4;unsigned *src,*dst;std::vector<unsigned> h(n),out(n);for(size_t i=0;i<n;i++)h[i]=(unsigned)i*1103515245u+12345u;
 CK(cudaSetDevice(s));alloc_peer(&src,bytes,s);CK(cudaMemcpy(src,h.data(),bytes,cudaMemcpyHostToDevice));CK(cudaSetDevice(d));alloc_peer(&dst,bytes,d);CK(cudaMemset(dst,0,bytes));CK(cudaDeviceSynchronize());
 int caller=engine?s:d;CK(cudaSetDevice(caller));cudaStream_t stream;CK(cudaStreamCreate(&stream));printf("CE_START source=%d dest=%d caller=%d\n",s,d,caller);CK(cudaMemcpyAsync(dst,src,bytes,cudaMemcpyDeviceToDevice,stream));CK(cudaStreamSynchronize(stream));CK(cudaStreamDestroy(stream));
 CK(cudaSetDevice(d));CK(cudaMemcpy(out.data(),dst,bytes,cudaMemcpyDeviceToHost));bool valid=true;for(size_t i=0;i<n;i++)if(out[i]!=h[i]){printf("CORRUPTION i=%zu got=%08x expected=%08x\n",i,out[i],h[i]);valid=false;break;}
 printf("CE_RESULT source=%d dest=%d caller=%d valid=%d\n",s,d,caller,valid);failures+=!valid;free_peer(dst);CK(cudaSetDevice(s));free_peer(src);
}printf("TOTAL_FAILURES %d\n",failures);return failures?5:0;}
