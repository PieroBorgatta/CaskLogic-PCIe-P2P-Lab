#include "pci_attrs.h"
#include <cassert>
#include <iostream>
int main(){
 unsigned cases=0;
 for(unsigned old=0;old<65536;++old)for(unsigned bits:{0u,0x10u,0x800u,0x810u}){
  uint16_t value=pciattrs::target(old,bits);
  assert((value&pciattrs::MASK)==bits);assert(pciattrs::preserves_other_bits(old,value));++cases;
 }
 std::array<unsigned char,256>b{};
 b[0]=0xde;b[1]=0x10;b[2]=0xb0;b[3]=0x28;b[4]=6;b[6]=0x10;b[0x0b]=3;b[0x34]=0x78;b[0x78]=0x10;b[0x7a]=2;b[0x80]=0x30;b[0x81]=0x29;
 auto baseline=b;std::string error;pciattrs::Snapshot s;
 assert(pciattrs::decode(b.data(),b.size(),0x28b010de,s,error));assert(s.cap==0x78&&s.control==0x2930&&s.status==0);++cases;
 auto bad=[&](unsigned at,unsigned val){b=baseline;b[at]=val;error.clear();assert(!pciattrs::decode(b.data(),b.size(),0x28b010de,s,error));assert(!error.empty());++cases;};
 bad(0,0xff);bad(0xb,2);bad(0xe,1);bad(4,0);bad(6,0);bad(0x34,0x39);bad(0x34,0x41);bad(0x79,0x78);bad(0x7a,0x42);bad(0x7a,0);bad(0x7a,3);
 b=baseline;assert(!pciattrs::decode(b.data(),255,0x28b010de,s,error));++cases;
 b=baseline;b[0x79]=0x90;b[0x90]=0x10;b[0x92]=2;assert(!pciattrs::decode(b.data(),256,0x28b010de,s,error));++cases;
 b=baseline;b[0x34]=0xf8;b[0xf8]=0x10;b[0xfa]=2;assert(!pciattrs::decode(b.data(),256,0x28b010de,s,error));++cases;
 // A non-PCIe capability chained before the unique endpoint capability is valid.
 b=baseline;b[0x34]=0x40;b[0x40]=1;b[0x41]=0x78;assert(pciattrs::decode(b.data(),256,0x28b010de,s,error));++cases;
 // Transactions Pending is observable, never cleared by the decoder.
 b=baseline;b[0x82]=0x20;assert(pciattrs::decode(b.data(),256,0x28b010de,s,error));assert(s.status&0x20);assert(b[0x82]==0x20);++cases;
 std::cout<<"PASS "<<cases<<" pure decoder/mask cases; no PCI files or MMIO opened\n";
}
