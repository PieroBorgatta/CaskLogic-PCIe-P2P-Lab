#pragma once
#include "include/cask_phys_ce_ioctl.h"
#include <cerrno>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dirent.h>
#include <fcntl.h>
#include <stdexcept>
#include <string>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <cpuid.h>
#include <signal.h>
#include <vector>
namespace phys_ce {
static_assert(offsetof(UVM_TEST_CASK_PHYSICAL_CE_PARAMS,source_physical)==72,"ABI input boundary");
inline void native_identity(){
 unsigned a=0,b=0,c=0,d=0;if(!__get_cpuid(0,&a,&b,&c,&d))throw std::runtime_error("cpuid_vendor_unavailable");
 char vendor[13]{};std::memcpy(vendor,&b,4);std::memcpy(vendor+4,&d,4);std::memcpy(vendor+8,&c,4);
 if(std::strcmp(vendor,"GenuineIntel")||!__get_cpuid(1,&a,&b,&c,&d)||a!=0x906a3||(c&(1U<<31)))throw std::runtime_error("native_cpu_identity");
 const char*paths[]={"0000:00:00.0","0000:00:01.0","0000:00:07.0","0000:04:00.0","0000:05:00.0"};
 const uint32_t ids[]={0x46418086,0x460d8086,0x466e8086,0x24611b21,0x24611b21};
 for(unsigned i=0;i<5;++i){std::string path="/sys/bus/pci/devices/"+std::string(paths[i])+"/config";int fd=open(path.c_str(),O_RDONLY|O_CLOEXEC);uint32_t id=0;
 ssize_t n=fd<0?-1:pread(fd,&id,4,0);if(fd>=0)close(fd);
 std::printf("PHYS_NATIVE_PCI bdf=%s id=%08x expected=%08x valid=%d\n",paths[i],id,ids[i],n==4&&id==ids[i]);
 if(n!=4||id!=ids[i])throw std::runtime_error("native_pcie_identity");}
 std::printf("PHYS_NATIVE_CPU vendor=GenuineIntel eax=000906a3 hypervisor=0 valid=1\n");
}
inline bool inputs_equal(const UVM_TEST_CASK_PHYSICAL_CE_PARAMS&a,const UVM_TEST_CASK_PHYSICAL_CE_PARAMS&b){return std::memcmp(&a,&b,72)==0;}
inline bool retained_or_inflight(const UVM_TEST_CASK_PHYSICAL_CE_PARAMS&p){return (p.result_flags&CASK_PHYS_CE_RETAINED)||((p.result_flags&CASK_PHYS_CE_SUBMITTED)&&!(p.result_flags&CASK_PHYS_CE_COMPLETED));}
[[noreturn]] inline void abort_inflight(const UVM_TEST_CASK_PHYSICAL_CE_PARAMS&p){
 struct sigaction ignored{};ignored.sa_handler=SIG_IGN;sigemptyset(&ignored.sa_mask);sigaction(SIGTERM,&ignored,nullptr);
 std::printf("PHYS_CE_RETAINED request=%llu flags=%x rmStatus=%x parked=1 no_exit=1 no_more_gpu_work=1 no_fd_close=1 reboot_required=1\n",(unsigned long long)p.request_id,p.result_flags,p.rmStatus);std::fflush(nullptr);
 // Deliberately never unwind: CUDA atexit/FD-close could remove mappings while
 // the engine is still active. The independent RAM boot watchdog reboots.
 for(;;)pause();
}
inline UVM_TEST_CASK_PHYSICAL_CE_PARAMS request(unsigned op,uint64_t id,const uint8_t*src_uuid,const uint8_t*dst_uuid,uint64_t source,uint64_t destination){
 UVM_TEST_CASK_PHYSICAL_CE_PARAMS p{};p.abi_version=CASK_PHYS_CE_ABI;p.operation=op;p.request_id=id;
 std::memcpy(p.source_uuid,src_uuid,16);std::memcpy(p.destination_uuid,dst_uuid,16);p.source_va=source;p.destination_va=destination;p.bytes=4;return p;
}
inline bool valid_validation(const UVM_TEST_CASK_PHYSICAL_CE_PARAMS&in,const UVM_TEST_CASK_PHYSICAL_CE_PARAMS&out,int rv){return rv==0&&inputs_equal(in,out)&&out.rmStatus==0&&out.result_flags==CASK_PHYS_CE_VALIDATED&&out.reserved_out==0;}
inline bool valid_execution(const UVM_TEST_CASK_PHYSICAL_CE_PARAMS&in,const UVM_TEST_CASK_PHYSICAL_CE_PARAMS&out,int rv){
 // Kernel candidate permits only Ampere DMA COPY A/B; its explicit
 // destination physical aperture is COHERENT_SYSMEM (1), matching the stock SYS helper.
 bool known_class=out.ce_class==0xc6b5||out.ce_class==0xc7b5;
 return rv==0&&inputs_equal(in,out)&&out.rmStatus==0&&out.result_flags==CASK_PHYS_CE_SUCCESS_FLAGS&&out.reserved_out==0&&out.source_rm_handle&&out.destination_rm_handle&&known_class&&out.source_phys_mode==0&&out.destination_phys_mode==1&&out.launch_dma==(out.ce_class==0xc7b5?0x04003186U:0x00003186U)&&!(out.source_physical&3)&&!(out.destination_physical&3)&&out.source_allocation_offset==0&&out.destination_allocation_offset==0;
}
inline bool target_bar1_contains(int owner,uint64_t address){
 const char*bdf[]={"0000:01:00.0","0000:06:00.0"};std::string path="/sys/bus/pci/devices/"+std::string(bdf[owner])+"/resource";FILE*f=std::fopen(path.c_str(),"r");if(!f)return false;
 unsigned long long start=0,end=0,flags=0;bool read=true;for(int i=0;i<2;++i)read&=std::fscanf(f,"%llx %llx %llx",&start,&end,&flags)==3;std::fclose(f);
 bool valid=read&&(flags&0x200)&&start<=end&&address>=start&&address<=end&&end-address>=3;
 std::printf("PHYS_BAR1 owner=%d start=%llx end=%llx flags=%llx destination_physical=%llx valid=%d\n",owner,start,end,flags,(unsigned long long)address,valid);return valid;
}
class Client {
 int fd_=-1;
public:
 ~Client(){if(fd_>=0)close(fd_);}
 void discover(const UVM_TEST_CASK_PHYSICAL_CE_PARAMS&in){
  struct stat device{};if(stat("/dev/nvidia-uvm",&device)||!S_ISCHR(device.st_mode))throw std::runtime_error("uvm_device_stat");
  DIR*dir=opendir("/proc/self/fd");if(!dir)throw std::runtime_error("self_fd_directory");std::vector<int> candidates;
  while(dirent*e=readdir(dir)){char*end=nullptr;errno=0;long n=std::strtol(e->d_name,&end,10);if(errno||!end||*end||n<0||n>1048576)continue;struct stat s{};
   if(!fstat(int(n),&s)&&S_ISCHR(s.st_mode)&&s.st_rdev==device.st_rdev)candidates.push_back(int(n));}
  closedir(dir);int matching=-1;unsigned count=0;
  for(int fd:candidates){auto p=in;errno=0;int rv=ioctl(fd,CASK_PHYS_CE_IOCTL,&p);int error=errno;
   if(retained_or_inflight(p))abort_inflight(p);bool ok=valid_validation(in,p,rv);
   std::printf("PHYS_FD_VALIDATION fd=%d request=%llu rv=%d errno=%d rmStatus=%x flags=%x valid=%d\n",fd,(unsigned long long)in.request_id,rv,error,p.rmStatus,p.result_flags,ok);
   if(ok){matching=fd;++count;}}
  if(count!=1)throw std::runtime_error("uvm_matching_fd_not_unique");
  fd_=fcntl(matching,F_DUPFD_CLOEXEC,3);if(fd_<0)throw std::runtime_error("uvm_fd_duplicate");
  std::printf("PHYS_FD_SELECTED original=%d retained_fd=%d candidates=%zu matches=1\n",matching,fd_,candidates.size());
 }
 UVM_TEST_CASK_PHYSICAL_CE_PARAMS execute(const UVM_TEST_CASK_PHYSICAL_CE_PARAMS&in,int target){
  if(fd_<0||in.operation!=CASK_PHYS_CE_EXECUTE)throw std::runtime_error("phys_client_state");
  struct sigaction ignored{},previous{};ignored.sa_handler=SIG_IGN;sigemptyset(&ignored.sa_mask);
  if(sigaction(SIGTERM,&ignored,&previous))throw std::runtime_error("sigterm_guard_failed_before_submit");
  auto p=in;errno=0;int rv=ioctl(fd_,CASK_PHYS_CE_IOCTL,&p);int error=errno;
  std::printf("PHYS_IOCTL_RESULT request=%llu src=%llx dst=%llx bytes=%u rv=%d errno=%d rmStatus=%x flags=%x source_pa=%llx destination_pa=%llx source_offset=%llx destination_offset=%llx source_handle=%x destination_handle=%x ce_class=%x launch=%x source_mode=%x destination_mode=%x inputs_unchanged=%d\n",(unsigned long long)in.request_id,(unsigned long long)in.source_va,(unsigned long long)in.destination_va,in.bytes,rv,error,p.rmStatus,p.result_flags,(unsigned long long)p.source_physical,(unsigned long long)p.destination_physical,(unsigned long long)p.source_allocation_offset,(unsigned long long)p.destination_allocation_offset,p.source_rm_handle,p.destination_rm_handle,p.ce_class,p.launch_dma,p.source_phys_mode,p.destination_phys_mode,inputs_equal(in,p));
  // Even a syscall error without flags is ambiguous after EXECUTE: retain
  // every userspace resource until the external watchdog, never infer safety.
  if(retained_or_inflight(p)||rv!=0||!inputs_equal(in,p)||!(p.result_flags&CASK_PHYS_CE_COMPLETED))abort_inflight(p);
  if(sigaction(SIGTERM,&previous,nullptr))throw std::runtime_error("sigterm_restore_failed_after_completion");
  if(!valid_execution(in,p,rv))throw std::runtime_error("physical_ce_not_qualified");
  if(!target_bar1_contains(target,p.destination_physical))throw std::runtime_error("physical_target_not_current_bar1");
  return p;
 }
};
} //namespace phys_ce
