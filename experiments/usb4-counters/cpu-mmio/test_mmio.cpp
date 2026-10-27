#define CASK_MMIO_NO_MAIN
#include "mmio_probe.cpp"
#include <vector>
struct Fake {
 uint16_t value=0;int writes=0,fail_write=0;bool corrupt_readback=false;
 std::vector<uint16_t> values;
 uint16_t read_command(){if(corrupt_readback && writes==1){corrupt_readback=false;throw std::runtime_error("injected_read");}return value;}
 void write_command(uint16_t v){++writes;values.push_back(v);value=v;if(writes==fail_write)throw std::runtime_error("injected_write");}
};
int main(){
 using namespace mmio_control;
 {Fake f;{MseLease<Fake> l(f);need(f.value==2,"enable");need(l.restore(),"restore");need(l.restore(),"idempotent");}need(f.value==0 && f.values==std::vector<uint16_t>({2,0}),"exact_owned_writes");}
 {Fake f;{MseLease<Fake> l(f);}need(f.value==0,"destructor_restore");}
 {Fake f;f.fail_write=1;bool rejected=false;try{MseLease<Fake> l(f);}catch(...){rejected=true;}need(rejected && f.value==0 && f.values==std::vector<uint16_t>({2,0}),"partial_write_rollback");}
 {Fake f;f.corrupt_readback=true;bool rejected=false;try{MseLease<Fake> l(f);}catch(...){rejected=true;}need(rejected && f.value==0,"readback_failure_rollback");}
 {Fake f;f.value=4;bool rejected=false;try{MseLease<Fake> l(f);}catch(...){rejected=true;}need(rejected && !f.writes && f.value==4,"bus_master_guard");}
 {Fake f;MseLease<Fake> l(f);f.value=6;need(!l.restore() && f.writes==1 && f.value==6,"configuration_race_not_overwritten");f.value=2;need(l.restore(),"restore_after_test_race");}
 {Fake f;{MseLease<Fake> l(f);f.fail_write=2;bool failed=false;try{l.restore();}catch(...){failed=true;}need(failed,"restore_failure_visible");}need(f.value==0,"restore_write_effect");}
 std::printf("PASS 7 command lease lifecycle, injected failure and Bus Master guards\n");
}
