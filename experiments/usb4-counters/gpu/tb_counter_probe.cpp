// Read-only observer. Counter assignment is done by the opt-in kernel module
// before path activation. No debugfs, PCI configuration or MMIO writes here.
#include <array>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <limits>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unistd.h>

namespace tb_counter {
inline void need(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
inline std::string read_text(const std::string &path) {
 int fd = open(path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
 need(fd >= 0, "open_readonly_failed");
 std::string out; char b[4096];
 for (;;) {
  ssize_t n = read(fd,b,sizeof(b));
  if (n < 0 && errno == EINTR) continue;
  if (n < 0) { close(fd); throw std::runtime_error("read_failed"); }
  if (!n) break;
  out.append(b,size_t(n));
  if (out.size() > 65536) { close(fd); throw std::runtime_error("read_limit"); }
 }
 close(fd); return out;
}
inline uint32_t number(const std::string &s, int base) {
 need(!s.empty() && s[0]!='-' && s[0]!='+', "number_sign");
 size_t used=0; unsigned long long x=std::stoull(s,&used,base);
 need(used==s.size() && x<=UINT32_MAX,"number_range");return uint32_t(x);
}
struct Row {uint32_t relative, id, value;};
inline std::map<uint32_t,Row> parse(const std::string &text, bool regs=false) {
 std::map<uint32_t,Row> out; std::istringstream lines(text); std::string line;
 while (std::getline(lines,line)) {
  if (line.empty() || line[0]=='#') continue;
  std::istringstream in(line);std::string a,b,c,d,e,extra;
  need(bool(in>>a>>b>>c>>d),"short_register_row");
  if(regs) {need(bool(in>>e),"short_adapter_row");number(d,0);}
  need(!(in>>extra),"extra_register_column");
  uint32_t offset=number(a,0);
  need(out.emplace(offset,Row{number(b,10),number(c,0),number(regs?e:d,0)}).second,
       "duplicate_register_offset");
 }
 need(!out.empty(),"empty_register_file");return out;
}
struct Point {const char *name,*path;uint32_t index,type,dw0,dw1;};
static const std::array<Point,4> points{{
 {"HOST_PCIE","/sys/kernel/debug/thunderbolt/0-0/port8",0,0x100101,0x800e0808,0x037ff301},
 {"HOST_LANE","/sys/kernel/debug/thunderbolt/0-0/port1",1,0x000001,0x80804008,0x017ff301},
 {"DOCK_LANE","/sys/kernel/debug/thunderbolt/0-1/port1",1,0x000001,0x80801808,0x017ff301},
 {"DOCK_PCIE","/sys/kernel/debug/thunderbolt/0-1/port3",0,0x100102,0x800e0808,0x037ff301}
}};
inline uint32_t wanted_dw1(const Point &p,bool enabled) {
 return enabled?(p.dw1&~0x00fff000u)|0x00800000u|(p.index<<12):p.dw1;
}
inline void check_path(const Point &p,const std::string &adapter,
                       const std::string &path,bool enabled) {
 auto a=parse(adapter,true),h=parse(path);
 for(unsigned i=0;i<=5;++i)need(a.count(i)==1,"adapter_header_missing");
 uint32_t cs1=a.at(1).value;
 need(((a.at(2).value&0xffffff)==p.type) && ((cs1>>19)&1) &&
      ((cs1>>8)&0x7ff)>p.index && !(cs1&0x00f00000),"adapter_mismatch");
 need(h.count(16) && h.count(17),"hop8_missing");
 need(h.at(16).relative==0 && h.at(16).id==8 &&
      h.at(17).relative==1 && h.at(17).id==8,"hop8_layout");
 need(h.at(16).value==p.dw0 &&
      (h.at(17).value&~0x10000000u)==wanted_dw1(p,enabled),"path_value_changed");
 for(const auto &r:h)if(r.second.relative==1 && r.second.id!=8) {
  need(h.count(r.first-1)==1,"orphan_path_dword");
  if ((h.at(r.first-1).value&0x80000000u) && (r.second.value&0x00800000u))
   need(((r.second.value>>12)&0x7ff)!=p.index,"counter_shared");
 }
}
inline void validate_paths(bool enabled) {
 for(const auto &p:points) {
  std::string base=p.path;
  check_path(p,read_text(base+"/regs"),read_text(base+"/path"),enabled);
  std::printf("TB_COUNTER_PATH point=%s enabled=%d index=%u valid=1\n",p.name,enabled,p.index);
 }
}
struct Count {uint64_t received;uint32_t dropped;};
inline Count decode(const std::string &text,unsigned index) {
 auto rows=parse(text);uint32_t words[3]{};
 for(unsigned i=0;i<3;++i) {
  need(rows.count(3*index+i)==1,"counter_word_missing");
  auto r=rows.at(3*index+i);need(r.relative==i && r.id==index,"counter_layout");
  words[i]=r.value;
 }
 return {uint64_t(words[0])|(uint64_t(words[1])<<32),words[2]};
}
inline Count delta(Count before,Count after) {
 need(before.received!=UINT64_MAX && after.received!=UINT64_MAX &&
      before.dropped!=UINT32_MAX && after.dropped!=UINT32_MAX,"counter_saturated");
 need(after.received>=before.received && after.dropped>=before.dropped,"counter_reset");
 return {after.received-before.received,after.dropped-before.dropped};
}
using Snapshot=std::array<Count,4>;
inline Snapshot snapshot() {
 Snapshot s{};for(size_t i=0;i<points.size();++i)
  s[i]=decode(read_text(std::string(points[i].path)+"/counters"),points[i].index);
 return s;
}
inline void show_delta(const char *stage,unsigned reads,const Snapshot &before,
                       const Snapshot &after,bool require_positive) {
 for(size_t i=0;i<points.size();++i) {
  Count d=delta(before[i],after[i]);
  std::printf("TB_COUNTER_SAMPLE stage=%s reads=%u point=%s before=%llu after=%llu delta=%llu dropped_before=%u dropped_after=%u dropped_delta=%u\n",
   stage,reads,points[i].name,(unsigned long long)before[i].received,
   (unsigned long long)after[i].received,(unsigned long long)d.received,
   before[i].dropped,after[i].dropped,d.dropped);
  need(!d.dropped,"observed_packet_drop");
  if(require_positive)need(d.received>=reads,"positive_control_no_count");
 }
}
inline void identity() {
 need(read_text("/sys/class/dmi/id/board_name")=="AHWSA\n" &&
      read_text("/sys/class/dmi/id/bios_version")=="1.26\n","board_identity");
 need(access("/sys/hypervisor/type",F_OK)!=0,"hypervisor_present");
 need(access("/sys/module/nvidia",F_OK)!=0 && access("/sys/module/nouveau",F_OK)!=0,
      "gpu_driver_present");
 need(read_text("/sys/bus/thunderbolt/devices/0-0/vendor")=="0x8087\n" &&
      read_text("/sys/bus/thunderbolt/devices/0-0/device")=="0x463e\n" &&
      read_text("/sys/bus/thunderbolt/devices/0-1/vendor")=="0xb8\n" &&
      read_text("/sys/bus/thunderbolt/devices/0-1/device")=="0x2463\n","router_identity");
}
inline void cpu_controls() {
 identity();need(read_text("/sys/module/thunderbolt/parameters/cask_pcie_counters")=="Y\n",
                 "counter_module_parameter");validate_paths(true);
 int fd=open("/sys/bus/pci/devices/0000:06:00.0/config",O_RDONLY|O_CLOEXEC|O_NOFOLLOW);
 need(fd>=0,"pci_config_open");
 try {
  for(unsigned n:{0u,64u,1024u}) {
   auto before=snapshot();
   if(!n)usleep(100000);
   for(unsigned i=0;i<n;++i) {
    uint32_t id=0;need(pread(fd,&id,4,0)==4 && id==0x257110de,"pci_identity_read");
   }
   auto after=snapshot();show_delta(n?"CPU_CONFIG_POSITIVE":"IDLE",n,before,after,n!=0);
  }
 }catch(...) {close(fd);throw;}
 close(fd);validate_paths(true);
}
} // namespace tb_counter

#ifndef CASK_COUNTER_NO_MAIN
int main(int argc,char **argv) {
 setbuf(stdout,nullptr);
 try {
  if(argc==2 && !std::strcmp(argv[1],"--verify-restored")) {
   tb_counter::identity();tb_counter::validate_paths(false);
   std::printf("TB_COUNTER_RESTORED original_module=1 four_paths=1\n");return 0;
  }
  tb_counter::need(argc==1,"usage");
  std::printf("TB_COUNTER_PROBE_BEGIN version=1 gpu_program_executed=0 userspace_register_writes=0\n");
  tb_counter::cpu_controls();
  std::printf("TB_COUNTER_PROBE_END protocol_complete=1 positive_controls=2 idle_controls=1 points=4\n");return 0;
 }catch(const std::exception &e) {
  std::printf("TB_COUNTER_ABORT reason=%s protocol_complete=0\n",e.what());return 27;
 }
}
#endif
