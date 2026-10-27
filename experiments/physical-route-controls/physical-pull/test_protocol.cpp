#include "protocol.h"
#include <cassert>
#include <set>
#include <cstdio>
int main(){
 using namespace physical_pull_protocol;
 std::set<uint32_t> seeds,expected;
 unsigned physical=0,push=0,pull=0;
 for(unsigned id=1;id<=CASES;++id){
  const auto c=describe(id);assert(c.id==id);assert(c.executor==(id<=6?1:0));
  assert(c.source!=c.destination);assert(c.source>=0&&c.source<=1);assert(c.destination>=0&&c.destination<=1);
  assert(c.executor==((c.step==2||c.step==3||c.step==4)?c.destination:c.source));
  assert(seeds.insert(c.seed).second);assert(expected.insert(pattern(0,c.seed)).second);
  assert(pattern(0,c.seed)!=0 && pattern(0,c.seed)!=0xffffffffU);
  physical+=c.physical();push+=c.transfer==Transfer::PHYSICAL_PUSH;pull+=c.transfer==Transfer::PHYSICAL_PULL;
  if(c.transfer==Transfer::PHYSICAL_PUSH)assert(c.source_mode==0&&c.destination_mode==2);
  if(c.transfer==Transfer::PHYSICAL_PULL)assert((c.source_mode==1||c.source_mode==2)&&c.destination_mode==0);
 }
 assert(physical==6&&push==2&&pull==4);
 for(auto value:expected)assert(!expected.count(~value));
 for(unsigned invalid:{0U,13U,0xffffffffU}){bool rejected=false;try{describe(invalid);}catch(const std::runtime_error&){rejected=true;}assert(rejected);}
 assert(pattern(0,0x78dcdebc)==0x5a977825U);
 std::puts("PHYSICAL_PULL_PROTOCOL_FIXTURES PASS cases=12 physical=6 source_patterns_distinct=1 cpu_only=1");
}
