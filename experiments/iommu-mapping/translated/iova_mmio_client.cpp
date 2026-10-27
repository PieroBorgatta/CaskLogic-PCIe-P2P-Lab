#include <cuda.h>
#include "driver/cask_iova_mmio_ioctl.h"
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstddef>
#include <dirent.h>
#include <fcntl.h>
#include <signal.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <stdexcept>
#include <string>
#include <vector>

static_assert(sizeof(UVM_TEST_CASK_IOVA_MMIO_PARAMS)==96,"IOVA ABI size");
static_assert(offsetof(UVM_TEST_CASK_IOVA_MMIO_PARAMS,mmio_iova)==56,"IOVA input boundary");
static void check(CUresult r,const char *what) {
 if(r!=CUDA_SUCCESS){const char *s=nullptr;cuGetErrorString(r,&s);throw std::runtime_error(std::string(what)+":"+(s?s:"unknown"));}
}
[[noreturn]] static void park() {
 signal(SIGTERM,SIG_IGN);
 std::puts("IOVA_PARKED completion_uncertain=1 resources_retained_until_watchdog=1");std::fflush(nullptr);
 for(;;)pause();
}
static bool equal_inputs(const UVM_TEST_CASK_IOVA_MMIO_PARAMS&a,const UVM_TEST_CASK_IOVA_MMIO_PARAMS&b){return !std::memcmp(&a,&b,56);}
static bool validation_ok(const UVM_TEST_CASK_IOVA_MMIO_PARAMS &in,const UVM_TEST_CASK_IOVA_MMIO_PARAMS &out,int rv){
 return rv==0&&equal_inputs(in,out)&&out.rmStatus==0&&out.result_flags==CASK_IOVA_VALIDATED&&out.domain_type==3&&
 !out.mmio_iova&&!out.mmio_physical&&!out.host_pass_mask&&!out.peer_pass_mask&&!out.completed_mask;
}
int main(){
 setvbuf(stdout,nullptr,_IONBF,0);
 CUcontext contexts[2]{};CUdeviceptr va[2]{};CUmemGenericAllocationHandle handles[2]{};size_t lengths[2]{};
 int owned=-1;bool success=false;
 try {
  if(geteuid()!=0)throw std::runtime_error("root_required");
  std::puts("IOVA_BEGIN abi=1 peer_register_offset=0 peer_reads_only=1 ordinary_peer_access=0 host_staging_for_peer=0");
  check(cuInit(0),"cuInit");int count=0;check(cuDeviceGetCount(&count),"count");if(count!=2)throw std::runtime_error("two_gpus_required");
  UVM_TEST_CASK_IOVA_MMIO_PARAMS request{};request.abi_version=CASK_IOVA_ABI;
  const char *envs[]={"CASKLOGIC_GPU0_UUID","CASKLOGIC_GPU1_UUID"};
  const char *bdfs[]={"0000:01:00.0","0000:06:00.0"};
  for(int index=0;index<2;++index){
   CUdevice device;CUuuid uuid{};char bdf[32]{},hex[33]{};
   check(cuDeviceGet(&device,index),"device");check(cuDeviceGetUuid(&uuid,device),"uuid");check(cuDeviceGetPCIBusId(bdf,sizeof(bdf),device),"bdf");
   for(int k=0;k<16;++k)std::snprintf(hex+2*k,3,"%02x",(unsigned char)uuid.bytes[k]);
   const char *want=std::getenv(envs[index]);if(!want||std::strlen(want)!=32||std::strcmp(want,hex)||std::strcmp(bdf,bdfs[index]))throw std::runtime_error("gpu_identity");
   std::memcpy(request.gpu_uuid[index],uuid.bytes,16);
   check(cuCtxCreate(&contexts[index],0,device),"context");
   CUmemAllocationProp prop{};prop.type=CU_MEM_ALLOCATION_TYPE_PINNED;prop.location.type=CU_MEM_LOCATION_TYPE_DEVICE;prop.location.id=device;
   check(cuMemGetAllocationGranularity(&lengths[index],&prop,CU_MEM_ALLOC_GRANULARITY_MINIMUM),"granularity");
   check(cuMemCreate(&handles[index],lengths[index],&prop,0),"create");check(cuMemAddressReserve(&va[index],lengths[index],0,0,0),"reserve");
   check(cuMemMap(va[index],lengths[index],0,handles[index],0),"map_local");
   CUmemAccessDesc access{};access.location=prop.location;access.flags=CU_MEM_ACCESS_FLAGS_PROT_READWRITE;
   check(cuMemSetAccess(va[index],lengths[index],&access,1),"local_access");
   std::printf("IOVA_GPU index=%d bdf=%s local_allocation_bytes=%zu peer_mapping=0\n",index,bdf,lengths[index]);
  }
  struct stat target{};if(stat("/dev/nvidia-uvm",&target)||!S_ISCHR(target.st_mode))throw std::runtime_error("uvm_stat");
  DIR *directory=opendir("/proc/self/fd");if(!directory)throw std::runtime_error("fds");std::vector<int> fds;
  while(dirent *e=readdir(directory)){
   char *end=nullptr;errno=0;long n=std::strtol(e->d_name,&end,10);if(errno||!end||*end||n<0||n>1048576)continue;
   struct stat s{};if(!fstat((int)n,&s)&&S_ISCHR(s.st_mode)&&s.st_rdev==target.st_rdev)fds.push_back((int)n);
  }
  closedir(directory);int selected=-1;unsigned matches=0;request.request_id=100;
  for(int fd:fds){auto out=request;errno=0;int rv=ioctl(fd,CASK_IOVA_IOCTL,&out);bool valid=validation_ok(request,out,rv);
   std::printf("IOVA_FD fd=%d rv=%d status=%x flags=%x domain=%u valid=%d\n",fd,rv,out.rmStatus,out.result_flags,out.domain_type,valid);
   if(valid){selected=fd;++matches;}}
  if(matches!=1)throw std::runtime_error("uvm_matching_fd_not_unique");
  owned=fcntl(selected,F_DUPFD_CLOEXEC,3);if(owned<0)throw std::runtime_error("duplicate_fd");
  std::printf("IOVA_FD_SELECTED matches=1 candidate_count=%zu\n",fds.size());
  for(unsigned index=0;index<2;++index){
   request.index=index;request.request_id=101+index;request.operation=1;auto out=request;
   struct sigaction ignored{},previous{};ignored.sa_handler=SIG_IGN;sigemptyset(&ignored.sa_mask);
   if(sigaction(SIGTERM,&ignored,&previous))throw std::runtime_error("signal_guard");
   errno=0;int rv=ioctl(owned,CASK_IOVA_IOCTL,&out);int err=errno;
   std::printf("IOVA_IOCTL index=%u request=%llu rv=%d errno=%d status=%x flags=%x domain=%u host_mask=%x peer_mask=%x completed_mask=%x iova=%llx physical=%llx inputs_unchanged=%d\n",
    index,(unsigned long long)request.request_id,rv,err,out.rmStatus,out.result_flags,out.domain_type,out.host_pass_mask,out.peer_pass_mask,out.completed_mask,
    (unsigned long long)out.mmio_iova,(unsigned long long)out.mmio_physical,equal_inputs(request,out));
   if(rv!=0||!equal_inputs(request,out)||(out.result_flags&CASK_IOVA_RETAINED))park();
   if(sigaction(SIGTERM,&previous,nullptr))throw std::runtime_error("signal_restore");
   if(out.rmStatus||out.result_flags!=7||out.domain_type!=3||out.host_pass_mask!=0x2d||out.completed_mask!=0x3f||out.peer_pass_mask>3||!out.mmio_iova||out.mmio_iova==out.mmio_physical)throw std::runtime_error("measurement_not_qualified");
  }
  success=true;
 }
 catch(const std::exception &e){std::printf("IOVA_ERROR reason=%s\n",e.what());}
 // No uncertain operation reaches here. Context destruction owns partial local
 // VMM resources on an ordinary pre-submission failure. No peer map exists.
 if(owned>=0)close(owned);
 for(int i=1;i>=0;--i)if(contexts[i]){
  cuCtxSetCurrent(contexts[i]);
  if(va[i]){cuMemUnmap(va[i],lengths[i]);cuMemAddressFree(va[i],lengths[i]);}
  if(handles[i])cuMemRelease(handles[i]);
  cuCtxDestroy(contexts[i]);
 }
 std::printf("IOVA_END protocol_complete=%d p2p_solution_claimed=0\n",success);
 return success?0:20;
}
