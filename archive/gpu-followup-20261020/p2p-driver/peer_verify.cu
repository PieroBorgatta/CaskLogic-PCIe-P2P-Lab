#include <cuda_runtime.h>
#include <cstdio>
#include <cstdlib>
#include <vector>
#define CK(x) do {auto e=(x);if(e!=cudaSuccess){printf("ERROR %s: %s (%d) line %d\n",#x,cudaGetErrorString(e),(int)e,__LINE__);fflush(stdout);exit(2);}}while(0)
__global__ void peer_read(const unsigned *src,unsigned *dst,size_t n){for(size_t i=blockIdx.x*blockDim.x+threadIdx.x;i<n;i+=gridDim.x*blockDim.x)dst[i]=src[i]^0x12345678u;}
__global__ void peer_write(unsigned *dst,size_t n,unsigned seed){for(size_t i=blockIdx.x*blockDim.x+threadIdx.x;i<n;i+=gridDim.x*blockDim.x)dst[i]=((unsigned)i*1664525u+seed)^0xa5a5a5a5u;}
int main(){setbuf(stdout,NULL);int count=0;CK(cudaGetDeviceCount(&count));printf("GPU count %d\n",count);if(count!=2)return 3;
for(int s=0;s<2;s++){int d=1-s,can=0;CK(cudaDeviceCanAccessPeer(&can,d,s));printf("PEER %d -> %d can %d\n",s,d,can);if(!can)return 4;CK(cudaSetDevice(d));CK(cudaDeviceEnablePeerAccess(s,0));}
for(size_t bytes:{size_t(65536),size_t(1048576),size_t(16777216),size_t(67108864)})for(int s=0;s<2;s++){
 int d=1-s;size_t n=bytes/4;unsigned *src,*dst;std::vector<unsigned> h(n),out(n);for(size_t i=0;i<n;i++)h[i]=(unsigned)i*1103515245u+12345u;
 CK(cudaSetDevice(s));CK(cudaMalloc(&src,bytes));CK(cudaMemcpy(src,h.data(),bytes,cudaMemcpyHostToDevice));CK(cudaSetDevice(d));CK(cudaMalloc(&dst,bytes));CK(cudaMemset(dst,0,bytes));printf("START peer_read src %d dst %d bytes %zu\n",s,d,bytes);peer_read<<<256,256>>>(src,dst,n);CK(cudaGetLastError());CK(cudaDeviceSynchronize());CK(cudaMemcpy(out.data(),dst,bytes,cudaMemcpyDeviceToHost));for(size_t i=0;i<n;i++)if(out[i]!=(h[i]^0x12345678u)){printf("CORRUPTION read i %zu got %08x expected %08x\n",i,out[i],h[i]^0x12345678u);return 5;}printf("PASS direct SM remote read %zu bytes\n",bytes);
 CK(cudaSetDevice(s));CK(cudaMemset(src,0,bytes));CK(cudaSetDevice(d));printf("START peer_write src %d dst %d bytes %zu\n",d,s,bytes);peer_write<<<256,256>>>(src,n,98765u);CK(cudaGetLastError());CK(cudaDeviceSynchronize());CK(cudaSetDevice(s));CK(cudaMemcpy(out.data(),src,bytes,cudaMemcpyDeviceToHost));for(size_t i=0;i<n;i++)if(out[i]!=(((unsigned)i*1664525u+98765u)^0xa5a5a5a5u)){printf("CORRUPTION write i %zu got %08x\n",i,out[i]);return 6;}printf("PASS direct SM remote write %zu bytes\n",bytes);CK(cudaFree(src));CK(cudaSetDevice(d));CK(cudaFree(dst));}
printf("ALL_DIRECT_PEER_TESTS_PASSED\n");return 0;}
