#include "pci_attrs.h"
#include <map>
#include <stdexcept>
#include <signal.h>
using cudaError_t=int;
enum {cudaSuccess=0,cudaMemcpyHostToDevice=1,cudaMemcpyDeviceToHost=2};
static int cudaGetDeviceCount(int*p){*p=2;return 0;}
static int cudaSetDevice(int){return 0;}
static int cudaFree(void*){return 0;}
static int cudaDeviceSynchronize(){return 0;}
static int cudaDeviceCanAccessPeer(int*p,int,int){*p=1;return 0;}
static int cudaMemcpy(void*,const void*,size_t,int){return 0;}
static int cudaMemset(void*,int,size_t){return 0;}
static int cudaGetLastError(){return 0;}
#define CK(x) do {if((x)!=cudaSuccess)throw std::runtime_error("cuda");}while(0)
static int kmsg_fd=-1;
static void phase(const char*,int=-1,int=-1){}
static void pcie_snapshot(const char*){}
static std::string cuda_bdf(int){return "";}
static std::string cuda_uuid(int){return "";}
static void alloc_peer(unsigned**,size_t,int){}
static void free_peer(unsigned*){}
static void verify_owner_word(const char*,int,const unsigned*,unsigned){}
static void cpu_bar_check(unsigned*,int){}
static void cpu_bar_postwrite(unsigned*,int,int,unsigned){}
static void peer_read(const unsigned*,unsigned*,size_t){}
static void peer_write(unsigned*,size_t,unsigned){}
static std::vector<std::pair<unsigned*,int>> pending_frees;
static unsigned cpu_post_pass=0,cpu_post_fail=0,cpu_post_skip=0,cpu_checks_pass=0,cpu_checks_fail=0,cpu_checks_skip=0;
