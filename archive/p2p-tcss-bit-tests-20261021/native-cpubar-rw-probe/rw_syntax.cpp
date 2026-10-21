#include "cpubar_trace.h"
#include "cpubar_rw.h"
using cudaError_t=int;
static const int cudaSuccess=0,cudaMemcpyDeviceToHost=2;
static int cudaSetDevice(int){return 0;}
static int cudaDeviceSynchronize(){return 0;}
static int cudaMemcpy(void*,const void*,size_t,int){return 0;}
struct CpuBarMeta { cpubar::Query query; cpubar::Identity owner; bool ready=false; std::string reason; };
static std::map<unsigned*,CpuBarMeta> cpu_meta;
static bool current_window(const CpuBarMeta&,cpubar::Window&,std::string&){return false;}
static bool same_window(const cpubar::Window&a,const cpubar::Window&b){return a.id==b.id;}
static void phase(const char*,int=-1,int=-1){}
static void pcie_snapshot(const char*){}
#include "cpubar_rw_control.inc"
int main(){cpu_bar_rw_check(nullptr,0);return 0;}
