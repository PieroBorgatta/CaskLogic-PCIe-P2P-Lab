#include <cuda_runtime.h>
#include <cuda.h>
#include <map>
#include <unistd.h>
#include <ctime>
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
int main(){int failures=0;setbuf(stdout,NULL);int count=0;CK(cudaGetDeviceCount(&count));printf("GPU count %d\n",count);if(count!=2)return 3;
for(int s=0;s<2;s++){int d=1-s,can=0;CK(cudaDeviceCanAccessPeer(&can,d,s));printf("PEER %d -> %d can %d\n",s,d,can);if(!can)return 4;CK(cudaSetDevice(d));}
for(size_t bytes:{size_t(4)})for(int s=0;s<2;s++){
 int d=1-s;size_t n=bytes/4;unsigned *src,*dst;std::vector<unsigned> h(n),out(n);for(size_t i=0;i<n;i++)h[i]=(unsigned)i*1103515245u+12345u;
 CK(cudaSetDevice(s));alloc_peer(&src,bytes,s);CK(cudaMemcpy(src,h.data(),bytes,cudaMemcpyHostToDevice));CK(cudaSetDevice(d));alloc_peer(&dst,bytes,d);CK(cudaMemset(dst,0,bytes));{ FILE *f=fopen("/trial/config-gate-ready","w");fprintf(f,"%d",s);fclose(f);time_t start=time(NULL);for(;;){f=fopen("/trial/config-gate-go","r");if(f){int v=-1;fscanf(f,"%d",&v);fclose(f);if(v==s)break;}if(time(NULL)-start>20){printf("GATE_TIMEOUT\n");exit(8);}usleep(20000);} }printf("START peer_read src %d dst %d bytes %zu\n",s,d,bytes);peer_read<<<256,256>>>(src,dst,n);CK(cudaGetLastError());CK(cudaDeviceSynchronize());CK(cudaMemcpy(out.data(),dst,bytes,cudaMemcpyDeviceToHost));bool good=true;for(size_t i=0;i<n;i++)if(out[i]!=(h[i]^0x12345678u)){printf("CORRUPTION read i %zu got %08x expected %08x\n",i,out[i],h[i]^0x12345678u);good=false;failures++;break;}printf("REMOTE_READ s=%d d=%d bytes=%zu valid=%d\n",s,d,bytes,good);

 CK(cudaSetDevice(s));CK(cudaMemset(src,0,bytes));CK(cudaSetDevice(d));printf("START peer_write src %d dst %d bytes %zu\n",d,s,bytes);peer_write<<<256,256>>>(src,n,98765u);CK(cudaGetLastError());CK(cudaDeviceSynchronize());CK(cudaSetDevice(s));CK(cudaMemcpy(out.data(),src,bytes,cudaMemcpyDeviceToHost));good=true;for(size_t i=0;i<n;i++)if(out[i]!=(((unsigned)i*1664525u+98765u)^0xa5a5a5a5u)){printf("CORRUPTION write i %zu got %08x\n",i,out[i]);good=false;failures++;break;}printf("REMOTE_WRITE s=%d d=%d bytes=%zu valid=%d\n",d,s,bytes,good);free_peer(src);CK(cudaSetDevice(d));free_peer(dst);}
printf("TOTAL_FAILURES %d\n",failures);return failures?5:0;}
