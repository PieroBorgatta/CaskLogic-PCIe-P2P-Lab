#define CASK_COUNTER_NO_MAIN
#include "tb_counter_probe.cpp"
#include <sys/mman.h>
#include <time.h>

namespace mmio_control {
using tb_counter::need;
// Only Memory Space Enable is leased. Bus Master Enable must remain zero.
template<class Backend> class MseLease {
 Backend &b; bool armed=false;uint16_t original=0;
public:
 explicit MseLease(Backend &backend):b(backend) {
  original=b.read_command();need(original==0,"command_not_disabled");
  armed=true;
  try {b.write_command(2);need(b.read_command()==2,"mse_enable_readback");}
  catch(...) {if(!restore())throw std::runtime_error("mse_constructor_restore_failed");throw;}
 }
 MseLease(const MseLease&)=delete;MseLease& operator=(const MseLease&)=delete;
 bool restore() {
  if(!armed)return true;
  uint16_t now=b.read_command();
  if(now==original){armed=false;return true;}
  if(now!=2)return false; // Do not overwrite an unexpected configuration.
  b.write_command(original);if(b.read_command()!=original)return false;
  armed=false;return true;
 }
 ~MseLease(){if(armed)try{if(!restore())std::printf("TB_MMIO_RESTORE_FAILED\n");}catch(...){std::printf("TB_MMIO_RESTORE_FAILED\n");}}
};
struct Pci {
 int fd;
 Pci():fd(open("/sys/bus/pci/devices/0000:06:00.0/config",O_RDWR|O_CLOEXEC|O_NOFOLLOW)) {
  need(fd>=0,"pci_config_open_rw");
  uint32_t id=0,bar=0;uint16_t pm=0;uint8_t pmid=0;
  bool valid=pread(fd,&id,4,0)==4 && id==0x257110de &&
             pread(fd,&bar,4,0x10)==4 && bar==0x60000000 &&
             pread(fd,&pmid,1,0x60)==1 && pmid==1 &&
             pread(fd,&pm,2,0x64)==2 && !(pm&3);
  if(!valid){close(fd);fd=-1;throw std::runtime_error("gpu_bar_identity");}
 }
 uint16_t read_command(){uint16_t x=0;need(pread(fd,&x,2,4)==2,"command_read");return x;}
 void write_command(uint16_t value){need(value==0||value==2,"command_write_mask");need(pwrite(fd,&value,2,4)==2,"command_write_word");}
 ~Pci(){if(fd>=0)close(fd);}
};
struct Mapping {
 void *address=MAP_FAILED;
 Mapping() {
  int fd=open("/sys/bus/pci/devices/0000:06:00.0/resource0",O_RDONLY|O_CLOEXEC|O_NOFOLLOW);
  need(fd>=0,"resource_readonly_open");
  address=mmap(nullptr,4096,PROT_READ,MAP_SHARED,fd,0);close(fd);
  need(address!=MAP_FAILED,"resource_readonly_mmap");
 }
 Mapping(const Mapping&)=delete;Mapping& operator=(const Mapping&)=delete;
 uint32_t read_boot()const{return *static_cast<volatile const uint32_t*>(address);}
 ~Mapping(){if(address!=MAP_FAILED)munmap(address,4096);}
};
inline uint64_t ns(){timespec t{};need(clock_gettime(CLOCK_MONOTONIC,&t)==0,"clock");return uint64_t(t.tv_sec)*1000000000ULL+t.tv_nsec;}
struct Timed {tb_counter::Count value;uint64_t time;};
using Snapshot=std::array<Timed,4>;
inline Snapshot snapshot(){Snapshot s{};for(size_t i=0;i<4;++i){auto &p=tb_counter::points[i];s[i]={tb_counter::decode(tb_counter::read_text(std::string(p.path)+"/counters"),p.index),ns()};}return s;}
inline void show(unsigned group,unsigned reads,const Snapshot &before,const Snapshot &after){
 for(size_t i=0;i<4;++i){
  auto d=tb_counter::delta(before[i].value,after[i].value);
  need(after[i].time>before[i].time,"clock_order");
  std::printf("TB_MMIO_SAMPLE group=%u reads=%u point=%s before=%llu after=%llu delta=%llu dropped_before=%u dropped_after=%u dropped_delta=%u before_ns=%llu after_ns=%llu elapsed_ns=%llu\n",
   group,reads,tb_counter::points[i].name,(unsigned long long)before[i].value.received,
   (unsigned long long)after[i].value.received,(unsigned long long)d.received,
   before[i].value.dropped,after[i].value.dropped,d.dropped,
   (unsigned long long)before[i].time,(unsigned long long)after[i].time,
   (unsigned long long)(after[i].time-before[i].time));
 }
}
inline void run() {
 tb_counter::identity();tb_counter::validate_paths(true);
 need(tb_counter::read_text("/sys/module/thunderbolt/parameters/cask_pcie_counters")=="Y\n","module_parameter");
 Pci pci;
 std::printf("TB_MMIO_COMMAND_BEGIN original=%04x requested=0002 bus_master_enable=0\n",pci.read_command());
 MseLease<Pci> lease(pci);
 std::printf("TB_MMIO_COMMAND_ACTIVE observed=%04x\n",pci.read_command());
 {
  Mapping mapping;need(mapping.read_boot()==0xb76000a1,"initial_boot_register");
  unsigned group=0;
  for(unsigned reads:{0u,64u,16384u,0u}) {
   auto before=snapshot();
   if(!reads)usleep(100000);
   for(unsigned i=0;i<reads;++i)need(mapping.read_boot()==0xb76000a1,"boot_register_changed");
   auto after=snapshot();show(++group,reads,before,after);
   need(pci.read_command()==2,"command_changed_during_control");
   std::printf("TB_MMIO_DATA group=%u reads=%u expected=b76000a1 checked=%u valid=1\n",group,reads,reads);
  }
  need(mapping.read_boot()==0xb76000a1,"final_boot_register");
 }
 need(lease.restore() && pci.read_command()==0,"mse_restore_readback");
 std::printf("TB_MMIO_COMMAND_RESTORED observed=0000 bus_master_enable=0\n");
 tb_counter::validate_paths(true);
}
} // namespace mmio_control

#ifndef CASK_MMIO_NO_MAIN
int main(int argc,char **argv) {
 setbuf(stdout,nullptr);
 try {
  if(argc==2 && !std::strcmp(argv[1],"--verify-restored")) {
   tb_counter::identity();tb_counter::validate_paths(false);
   mmio_control::Pci pci;tb_counter::need(pci.read_command()==0,"restored_command_not_original");
   std::printf("TB_COUNTER_RESTORED original_module=1 four_paths=1 command_original=1\n");return 0;
  }
  tb_counter::need(argc==1,"usage");
  std::printf("TB_MMIO_PROBE_BEGIN version=1 gpu_program_executed=0 mmio_writes=0 command_mask=0002\n");
  mmio_control::run();
  std::printf("TB_MMIO_PROBE_END protocol_complete=1 positive_controls=2 idle_controls=2 points=4 source_reads=16448 command_restored=1\n");return 0;
 }catch(const std::exception &e){std::printf("TB_MMIO_ABORT reason=%s protocol_complete=0\n",e.what());return 27;}
}
#endif
