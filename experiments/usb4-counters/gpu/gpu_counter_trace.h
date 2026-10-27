#ifndef CASK_GPU_COUNTER_TRACE_H
#define CASK_GPU_COUNTER_TRACE_H
#define CASK_COUNTER_NO_MAIN
#include "tb_counter_probe.cpp"
#include <time.h>
// No CUDA calls, MMIO access or register writes in this observer.
namespace gpu_counter {
inline uint64_t ns(){timespec t{};tb_counter::need(clock_gettime(CLOCK_MONOTONIC,&t)==0,"counter_clock");return uint64_t(t.tv_sec)*1000000000ULL+t.tv_nsec;}
struct Timed {tb_counter::Count value;uint64_t time;};
using Snapshot=std::array<Timed,4>;
inline Snapshot snapshot(){
 Snapshot s{};
 for(size_t i=0;i<4;++i){const auto &p=tb_counter::points[i];
  s[i]={tb_counter::decode(tb_counter::read_text(std::string(p.path)+"/counters"),p.index),ns()};
 }
 return s;
}
inline void record(uint64_t id,const char *stage,size_t bytes,const Snapshot &before,const Snapshot &after){
 for(size_t i=0;i<4;++i){
  auto d=tb_counter::delta(before[i].value,after[i].value);
  tb_counter::need(after[i].time>before[i].time,"counter_clock_order");
  std::printf("TB_GPU_SAMPLE id=%llu stage=%s bytes=%zu point=%s before=%llu after=%llu delta=%llu dropped_before=%u dropped_after=%u dropped_delta=%u before_ns=%llu after_ns=%llu elapsed_ns=%llu\n",
   (unsigned long long)id,stage,bytes,tb_counter::points[i].name,
   (unsigned long long)before[i].value.received,(unsigned long long)after[i].value.received,
   (unsigned long long)d.received,before[i].value.dropped,after[i].value.dropped,d.dropped,
   (unsigned long long)before[i].time,(unsigned long long)after[i].time,
   (unsigned long long)(after[i].time-before[i].time));
 }
}
inline void idle(uint64_t id){
 tb_counter::validate_paths(true);
 auto before=snapshot();usleep(20000);auto after=snapshot();record(id,"IDLE",0,before,after);
}
} // namespace gpu_counter
#endif
