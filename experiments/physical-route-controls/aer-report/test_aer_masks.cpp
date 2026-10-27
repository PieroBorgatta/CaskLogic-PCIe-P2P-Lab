#include "aer_report.h"
#include <cassert>
#include <initializer_list>
int main() {
 for(unsigned i=0;i<=65535;++i) {
  auto a=static_cast<uint16_t>(i);
  assert((cask_aer::desired_devctl(a)&~cask_aer::REPORT_MASK)==(a&~cask_aer::REPORT_MASK));
  assert((cask_aer::desired_devctl(a)&cask_aer::REPORT_MASK)==cask_aer::REPORT_MASK);
  assert(cask_aer::restore_devctl(cask_aer::desired_devctl(a),a)==a);
  for(unsigned b: {0U,0xffffU,0x2930U,0x2910U}) {
   auto n=static_cast<uint16_t>(b);
   assert((cask_aer::restore_devctl(n,a)&~cask_aer::REPORT_MASK)==(n&~cask_aer::REPORT_MASK));
   assert((cask_aer::restore_devctl(n,a)&cask_aer::REPORT_MASK)==(a&cask_aer::REPORT_MASK));
  }
 }
 for(uint32_t a: {0U,0xffffffffU,0x10000U,0x400000U}) {
  for(uint32_t b: {0U,0xffffffffU,0x10000U,0x12345678U}) {
   assert((cask_aer::restore_uem(b,a)&~cask_aer::UEM_MASK)==(b&~cask_aer::UEM_MASK));
   assert((cask_aer::restore_uem(b,a)&cask_aer::UEM_MASK)==(a&cask_aer::UEM_MASK));
  }
 }
 cask_aer::Scope unopened;
 assert(unopened.restore());
}
