#include "pcie_diag.h"
#include <cstring>
#include <vector>
static void u32(unsigned char*b,unsigned off,unsigned v){for(int i=0;i<4;i++)b[off+i]=(v>>(8*i))&255;}
int main(){
unsigned char b[4096]={};b[0]=0x86;b[1]=0x80;b[2]=0x6e;b[3]=0x46;b[6]=0x10;b[0xe]=1;b[0x34]=0x40;b[0x40]=0x10;b[0x42]=0x42;
u32(b,0x100,0x10001);u32(b,0x104,0x100000);u32(b,0x108,0x1234);u32(b,0x11c,0xdeadbeef);u32(b,0x134,0x6000100);
std::printf("CASE=valid_root");cask_pci_decode(b,4096);std::puts("");
std::printf("CASE=short_header");cask_pci_decode(b,3);std::puts("");
std::printf("CASE=short_ext");cask_pci_decode(b,256);std::puts("");
std::printf("CASE=short_aer");cask_pci_decode(b,0x106);std::puts("");
u32(b,0x100,0x10010001);std::printf("CASE=ext_cycle");cask_pci_decode(b,4096);std::puts("");
u32(b,0x100,0x0fc10001);std::printf("CASE=ext_bad_ptr");cask_pci_decode(b,4096);std::puts("");
u32(b,0x100,0x10110001);std::printf("CASE=ext_unaligned");cask_pci_decode(b,4096);std::puts("");
u32(b,0x100,0x10001);b[0x40]=5;b[0x41]=0x40;std::printf("CASE=std_cycle");cask_pci_decode(b,4096);std::puts("");
b[0x40]=0x10;b[0x41]=0;b[0x42]=2;b[0xe]=0;std::printf("CASE=endpoint");cask_pci_decode(b,4096);std::puts("");
b[0x34]=0xff;std::printf("CASE=std_bad_ptr");cask_pci_decode(b,4096);std::puts("");
b[0]=0xff;b[1]=0xff;std::printf("CASE=unavailable");cask_pci_decode(b,4096);std::puts("");
// ASAN/UBSAN con buffer realmente corto, ogni lunghezza di lettura possibile.
std::freopen("/dev/null","w",stdout);
for(size_t n=0;n<=4096;n++){std::vector<unsigned char> v(n);if(n>0)v[0]=0x86;if(n>1)v[1]=0x80;cask_pci_decode(v.data(),n);}
return 0;
}
