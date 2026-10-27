#define CASK_COUNTER_NO_MAIN
#include "tb_counter_probe.cpp"
#include "counter-fixtures.h"
#include <functional>
static unsigned tests=0;
static void fails(std::function<void()> f) {
 bool failed=false;try{f();}catch(const std::exception&){failed=true;}
 tb_counter::need(failed,"negative_test_accepted");++tests;
}
int main() {
 using namespace tb_counter;
 const char* regs[]={fixture_0_regs,fixture_1_regs,fixture_2_regs,fixture_3_regs};
 const char* paths[]={fixture_0_path,fixture_1_path,fixture_2_path,fixture_3_path};
 const char* counters[]={fixture_0_counters,fixture_1_counters,fixture_2_counters,fixture_3_counters};
 for(size_t i=0;i<4;++i) {
  check_path(points[i],regs[i],paths[i],true);++tests;
  auto c=decode(counters[i],points[i].index);need(!c.received&&!c.dropped,"baseline_count");++tests;
  fails([&]{check_path(points[i],regs[i],paths[i],false);});
  auto bad=points[i];bad.dw0^=0x20000;
  fails([&]{check_path(bad,regs[i],paths[i],true);});
 }
 fails([]{parse("0x0 0 0x0 0x1\n0x0 0 0x0 0x2\n");});
 fails([]{parse("0x0 0 0x0\n");});
 fails([]{parse("0x0 0 0x0 0x1 extra\n");});
 fails([]{parse("error: register access denied\n");});
 fails([]{parse("# no registers\n");});
 fails([]{number("-1",0);});fails([]{number("+1",0);});
 fails([]{number("0x100000000",0);});fails([]{number("0x1x",0);});
 fails([]{decode("0x0 0 0x0 0x1\n0x1 1 0x0 0x0\n",0);});
 fails([]{decode("0x0 0 0x0 0x1\n0x1 1 0x1 0x0\n0x2 2 0x0 0x0\n",0);});
 auto c=decode("0x0 0 0x0 0xffffffff\n0x1 1 0x0 0x1\n0x2 2 0x0 0x3\n",0);
 need(c.received==0x1ffffffffULL&&c.dropped==3,"high_low_order");++tests;
 auto d=delta({0xffffffffULL,2},{0x100000001ULL,3});
 need(d.received==2&&d.dropped==1,"low_word_carry");++tests;
 fails([]{delta({5,0},{4,0});});fails([]{delta({5,3},{6,2});});
 fails([]{delta({UINT64_MAX,0},{UINT64_MAX,0});});
 fails([]{delta({0,0},{UINT64_MAX,0});});
 fails([]{delta({0,UINT32_MAX},{1,UINT32_MAX});});
 fails([]{delta({0,0},{1,UINT32_MAX});});
 need(wanted_dw1(points[0],true)==0x03800301,"protocol_counter_mask");++tests;
 need(wanted_dw1(points[1],true)==0x01801301,"lane_counter_mask");++tests;
 // A second live path cannot silently share the selected lane counter.
 std::string shared=fixture_1_path;
 auto pos=shared.find("0x0012    0 0x09 0x00000000");need(pos!=std::string::npos,"fixture_layout");
 shared.replace(pos,27,"0x0012    0 0x09 0x80000000");
 pos=shared.find("0x0013    1 0x09 0x00000000");need(pos!=std::string::npos,"fixture_layout");
 shared.replace(pos,27,"0x0013    1 0x09 0x00801000");
 fails([&]{check_path(points[1],fixture_1_regs,shared,true);});
 std::printf("PASS %u counter parser, ownership, mask and saturation checks\n",tests);
}
