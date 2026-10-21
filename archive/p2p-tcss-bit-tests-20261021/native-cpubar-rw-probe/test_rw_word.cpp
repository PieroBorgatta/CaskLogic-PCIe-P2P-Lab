#include "cpubar_rw.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <sys/mman.h>
#include <unistd.h>
static unsigned cases=0;
#define CHECK(x) do{++cases;if(!(x)){fprintf(stderr,"FAILED line %d: %s\n",__LINE__,#x);return 1;}}while(0)
int main(){
 cpubar::Identity id;id.start=0x4600000000ULL;id.end=id.start+0x10000000-1;
 cpubar::Window w;w.bar=id.start;w.bar_size=0x10000000;w.offset=0x600000;w.physical=id.start+w.offset;w.size=0x200000;
 std::string err;cpubar::U off=0,delta=0;
 CHECK(cpubar::rw_bounds(id,w,4096,off,delta,err));CHECK(off==w.offset&&delta==0);
 for(unsigned n=1;n<4;n++){auto bad=w;bad.offset+=n;bad.physical+=n;CHECK(!cpubar::rw_bounds(id,bad,4096,off,delta,err));}
 for(auto page:{0ULL,1ULL,2ULL,3ULL,4095ULL,4097ULL}) CHECK(!cpubar::rw_bounds(id,w,page,off,delta,err));
 for(auto change:{0,1,2,3,4,5,6,7}){auto bad=w;
  switch(change){case 0:bad.bar++;break;case 1:bad.bar_size--;break;case 2:bad.physical++;break;case 3:bad.size=3;break;case 4:bad.offset=bad.bar_size;bad.physical=id.start+bad.offset;break;case 5:bad.offset=UINT64_MAX-3;break;case 6:bad.bar_size=0;break;case 7:bad.bar_size=2;break;}
  CHECK(!cpubar::rw_bounds(id,bad,4096,off,delta,err));}
 for(auto x:{cpubar::U(0),cpubar::U(4),cpubar::U(4092),cpubar::U(4096),w.bar_size-4}){auto good=w;good.offset=x;good.physical=id.start+x;CHECK(cpubar::rw_bounds(id,good,4096,off,delta,err));CHECK(delta<=4092);}
 auto bad_id=id;bad_id.start=0;CHECK(!cpubar::rw_bounds(bad_id,w,4096,off,delta,err));
 bad_id=id;bad_id.end=id.start-1;CHECK(!cpubar::rw_bounds(bad_id,w,4096,off,delta,err));
 const size_t page=static_cast<size_t>(sysconf(_SC_PAGESIZE));
 void *mem=mmap(nullptr,page,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);CHECK(mem!=MAP_FAILED);
 auto *words=static_cast<uint32_t*>(mem);for(size_t i=0;i<page/4;i++)words[i]=0x2468acdfu;
 uint32_t value=0;err.clear();
 CHECK(cpubar::guarded_write(words+1,0x37b95a61,err));CHECK(cpubar::guarded_read(words+1,value,err));CHECK(value==0x37b95a61);
 for(size_t i=0;i<page/4;i++)if(i!=1)CHECK(words[i]==0x2468acdfu);
 CHECK(cpubar::guarded_write(words+1,0x2468acdf,err));CHECK(words[1]==0x2468acdf);
 CHECK(mprotect(mem,page,PROT_READ)==0);err.clear();CHECK(!cpubar::guarded_write(words+1,0x11223344,err));CHECK(err.find("mmio_write_signal_")==0);CHECK(words[1]==0x2468acdf);
 CHECK(mprotect(mem,page,PROT_NONE)==0);err.clear();CHECK(!cpubar::guarded_read(words+1,value,err));CHECK(err.find("mmio_signal_")==0);
 CHECK(mprotect(mem,page,PROT_READ|PROT_WRITE)==0);CHECK(cpubar::guarded_write(words+1,0xa1b2c3d4,err));CHECK(words[1]==0xa1b2c3d4);CHECK(munmap(mem,page)==0);
 printf("PASS %u CPU-only bounds/store/signal cases; anonymous RAM only, no hardware.\n",cases);return 0;
}
