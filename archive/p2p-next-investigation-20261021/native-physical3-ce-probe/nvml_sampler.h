#pragma once
#include "include/nvml.h"
#include <algorithm>
#include <atomic>
#include <chrono>
#include <climits>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <dlfcn.h>
#include <stdexcept>
#include <string>
#include <thread>
#include <time.h>
#include <vector>

namespace traffic {
inline uint64_t now_ns() {
    timespec t{};
    if (clock_gettime(CLOCK_MONOTONIC,&t)) throw std::runtime_error("monotonic_clock_failed");
    return uint64_t(t.tv_sec)*1000000000ULL+uint64_t(t.tv_nsec);
}
constexpr uint64_t SAMPLE_PERIOD_NS=20000000ULL;
constexpr uint64_t INTERIOR_GUARD_NS=40000000ULL;
constexpr size_t MAX_SAMPLES=8192;
struct Sample {
    uint64_t begin=0,end=0;
    unsigned value=UINT_MAX;
    nvmlReturn_t rc=NVML_ERROR_UNKNOWN;
    int device=-1,counter=-1,stage=-1;
};
inline bool interior(const Sample&s,uint64_t active_begin,uint64_t active_end) {
    return s.stage==1 && s.begin>=active_begin+INTERIOR_GUARD_NS && s.end<=active_end && s.end>=s.begin;
}
inline bool baseline_quiet(const Sample&s,uint64_t sampler_begin,uint64_t active_begin) {
    return s.stage==0 && s.begin>=sampler_begin+INTERIOR_GUARD_NS && s.end<=active_begin && s.end>=s.begin;
}
struct Stats {
    size_t count=0,invalid=0;
    uint64_t sum=0;
    unsigned minimum=UINT_MAX,maximum=0;
    void add(const Sample&s) {
        if(s.rc!=NVML_SUCCESS){++invalid;return;}
        ++count;sum+=s.value;minimum=std::min(minimum,s.value);maximum=std::max(maximum,s.value);
    }
};
class Client {
    void* library_=nullptr;
    bool initialized_=false;
    decltype(&nvmlInit_v2) init_=nullptr;
    decltype(&nvmlShutdown) shutdown_=nullptr;
    decltype(&nvmlDeviceGetHandleByPciBusId_v2) get_handle_=nullptr;
    decltype(&nvmlDeviceGetUUID) get_uuid_=nullptr;
    decltype(&nvmlDeviceGetPcieThroughput) throughput_=nullptr;
    nvmlDevice_t devices_[2]{};
    template<class F> void symbol(F& out,const char*name){
        dlerror();void*p=dlsym(library_,name);const char*error=dlerror();
        if(error||!p)throw std::runtime_error(std::string("nvml_symbol_")+name);
        static_assert(sizeof(F)==sizeof(p),"function_pointer_size");std::memcpy(&out,&p,sizeof(out));
    }
public:
    Client()=default;
    Client(const Client&)=delete;
    Client&operator=(const Client&)=delete;
    ~Client(){if(initialized_&&shutdown_)shutdown_();if(library_)dlclose(library_);}
    void initialize(){
        library_=dlopen("libnvidia-ml.so.1",RTLD_NOW|RTLD_LOCAL);
        if(!library_)throw std::runtime_error("nvml_library_unavailable");
        symbol(init_,"nvmlInit_v2");symbol(shutdown_,"nvmlShutdown");
        symbol(get_handle_,"nvmlDeviceGetHandleByPciBusId_v2");symbol(get_uuid_,"nvmlDeviceGetUUID");
        symbol(throughput_,"nvmlDeviceGetPcieThroughput");
        nvmlReturn_t r=init_();std::printf("NVML_INIT rc=%d valid=%d\n",int(r),r==NVML_SUCCESS);
        if(r!=NVML_SUCCESS)throw std::runtime_error("nvml_init_failed");initialized_=true;
        const char*bdf[]={"0000:01:00.0","0000:06:00.0"};
        const char*uuid[]={"GPU-00000000-0000-0000-0000-000000000001","GPU-00000000-0000-0000-0000-000000000002"};
        for(int d=0;d<2;++d){
            r=get_handle_(bdf[d],&devices_[d]);char observed[NVML_DEVICE_UUID_BUFFER_SIZE]{};
            nvmlReturn_t ur=r==NVML_SUCCESS?get_uuid_(devices_[d],observed,sizeof(observed)):r;
            observed[sizeof(observed)-1]=0;
            bool valid=r==NVML_SUCCESS&&ur==NVML_SUCCESS&&!std::strcmp(observed,uuid[d]);
            std::printf("NVML_IDENTITY device=%d bdf=%s uuid=%s handle_rc=%d uuid_rc=%d valid=%d\n",d,bdf[d],observed,int(r),int(ur),valid);
            if(!valid)throw std::runtime_error("nvml_identity_failed");
            for(int c=0;c<2;++c){Sample s=read(d,c,0);
                std::printf("NVML_PREFLIGHT device=%d counter=%s rc=%d valid=%d value_kBps=%u begin_ns=%llu end_ns=%llu\n",d,c==0?"TX":"RX",int(s.rc),s.rc==NVML_SUCCESS,s.value,(unsigned long long)s.begin,(unsigned long long)s.end);
                if(s.rc!=NVML_SUCCESS)throw std::runtime_error("nvml_throughput_unavailable");
            }
        }
    }
    Sample read(int d,int c,int stage)const {
        Sample s;s.device=d;s.counter=c;s.stage=stage;s.begin=now_ns();
        unsigned value=UINT_MAX;
        s.rc=throughput_(devices_[d],c==0?NVML_PCIE_UTIL_TX_BYTES:NVML_PCIE_UTIL_RX_BYTES,&value);
        s.end=now_ns();if(s.rc==NVML_SUCCESS)s.value=value;return s;
    }
};
class Sampler {
    const Client&client_;
    std::thread thread_;
    std::atomic<bool> stop_{false};
    std::atomic<int> stage_{0};
    std::vector<Sample> samples_;
    bool overflow_=false,exception_=false;
    uint64_t started_=0,joined_=0;
    void work()noexcept{
        try{
            auto next=std::chrono::steady_clock::now();
            while(!stop_.load()){
                for(int d=0;d<2;++d)for(int c=0;c<2;++c){
                    if(samples_.size()==MAX_SAMPLES){overflow_=true;return;}
                    samples_.push_back(client_.read(d,c,stage_.load()));
                }
                next+=std::chrono::nanoseconds(SAMPLE_PERIOD_NS);
                auto now=std::chrono::steady_clock::now();if(next<now)next=now;
                std::this_thread::sleep_until(next);
            }
        }catch(...){exception_=true;}
    }
public:
    explicit Sampler(const Client&client):client_(client){samples_.reserve(MAX_SAMPLES);started_=now_ns();thread_=std::thread(&Sampler::work,this);}
    Sampler(const Sampler&)=delete;
    Sampler&operator=(const Sampler&)=delete;
    ~Sampler(){stop_join();}
    void stage(int stage){stage_.store(stage);}
    void stop_join()noexcept{stop_.store(true);if(thread_.joinable())thread_.join();}
    bool report(unsigned id,uint64_t active_begin,uint64_t active_end){
        stop_join();joined_=now_ns();bool valid=!overflow_&&!exception_;size_t selected=0,baseline_selected=0;
        Stats summary[3][2][2]{};
        for(const auto&s:samples_){
            bool use=interior(s,active_begin,active_end);
            bool quiet=baseline_quiet(s,started_,active_begin);
            if(s.stage==2||use||quiet)summary[s.stage][s.device][s.counter].add(s);
            if(use)++selected;if(quiet)++baseline_selected;
            valid&=s.rc==NVML_SUCCESS&&s.end>=s.begin;
            std::printf("NVML_SAMPLE phase=%u stage=%s device=%d counter=%s begin_ns=%llu end_ns=%llu rc=%d valid=%d value_kBps=%u interior=%d baseline_quiet=%d\n",id,s.stage==0?"BASELINE":s.stage==1?"ACTIVE":"TAIL",s.device,s.counter==0?"TX":"RX",(unsigned long long)s.begin,(unsigned long long)s.end,int(s.rc),s.rc==NVML_SUCCESS,s.value,use,quiet);
        }
        for(int stage=0;stage<3;++stage)for(int d=0;d<2;++d)for(int c=0;c<2;++c){
            const auto&s=summary[stage][d][c];if(stage==0||stage==1)valid&=s.count>=5&&s.invalid==0;
            std::printf("NVML_STATS phase=%u stage=%s device=%d counter=%s valid_count=%zu invalid_count=%zu mean_kBps=%.3f min_kBps=%u max_kBps=%u available=%d\n",id,stage==0?"BASELINE_QUIET":stage==1?"ACTIVE_INTERIOR":"TAIL",d,c==0?"TX":"RX",s.count,s.invalid,s.count?double(s.sum)/s.count:-1.0,s.count?s.minimum:UINT_MAX,s.count?s.maximum:UINT_MAX,s.count!=0);
        }
        std::printf("NVML_SAMPLER_END phase=%u started_ns=%llu joined_ns=%llu samples=%zu interior_samples=%zu baseline_quiet_samples=%zu overflow=%d exception=%d valid=%d aggregation=all_pcie_traffic payload_specific=0\n",id,(unsigned long long)started_,(unsigned long long)joined_,samples_.size(),selected,baseline_selected,overflow_,exception_,valid);
        return valid;
    }
};
} // namespace traffic
