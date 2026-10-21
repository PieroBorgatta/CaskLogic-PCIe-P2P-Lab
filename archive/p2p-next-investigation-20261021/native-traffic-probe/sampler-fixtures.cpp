#include "nvml_sampler.h"
#include <cassert>
int main(){
 using namespace traffic;
 Sample s;s.stage=1;s.rc=NVML_SUCCESS;s.begin=1040000000;s.end=1040000100;s.value=0;
 assert(interior(s,1000000000,1200000000));
 s.begin=1039999999;assert(!interior(s,1000000000,1200000000));
 s.begin=1040000000;s.end=1200000001;assert(!interior(s,1000000000,1200000000));
 s.end=s.begin-1;assert(!interior(s,1000000000,1200000000));
 s.end=s.begin;s.stage=0;assert(!interior(s,1000000000,1200000000));
 s.stage=2;assert(!interior(s,1000000000,1200000000));
 s.stage=0;s.begin=1040000000;s.end=1040000100;assert(baseline_quiet(s,1000000000,1200000000));
 s.begin=1039999999;assert(!baseline_quiet(s,1000000000,1200000000));
 s.begin=1040000000;s.end=1200000001;assert(!baseline_quiet(s,1000000000,1200000000));
 s.end=s.begin-1;assert(!baseline_quiet(s,1000000000,1200000000));
 s.end=s.begin;s.stage=1;assert(!baseline_quiet(s,1000000000,1200000000));
 Stats stats;stats.add(s);assert(stats.count==1&&stats.sum==0&&stats.minimum==0&&stats.maximum==0);
 s.rc=NVML_ERROR_NOT_SUPPORTED;s.value=UINT_MAX;stats.add(s);assert(stats.count==1&&stats.invalid==1&&stats.sum==0&&stats.minimum==0);
 s.rc=NVML_SUCCESS;s.value=UINT_MAX;stats.add(s);assert(stats.count==2&&stats.invalid==1&&stats.sum==UINT_MAX&&stats.maximum==UINT_MAX);
 s.value=UINT_MAX;stats.add(s);assert(stats.sum==2ULL*UINT_MAX);
 assert(NVML_PCIE_UTIL_TX_BYTES==0&&NVML_PCIE_UTIL_RX_BYTES==1);
 std::puts("SAMPLER_FIXTURES checks=16 valid=1 hardware_calls=0");
}
