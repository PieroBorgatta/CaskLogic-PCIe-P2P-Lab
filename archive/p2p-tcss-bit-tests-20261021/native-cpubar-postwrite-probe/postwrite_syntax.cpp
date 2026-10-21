#include "cpubar_trace.h"
#include "pcie_diag.h"
struct CpuBarMeta { cpubar::Query query; cpubar::Identity owner; bool ready=false; std::string reason; };
static std::map<unsigned*,CpuBarMeta> cpu_meta;
extern bool current_window(const CpuBarMeta&,cpubar::Window&,std::string&);
extern bool same_window(const cpubar::Window&,const cpubar::Window&);
extern void phase(const char*,int,int);
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

int main(){auto function=&cpu_bar_postwrite;(void)function;}
