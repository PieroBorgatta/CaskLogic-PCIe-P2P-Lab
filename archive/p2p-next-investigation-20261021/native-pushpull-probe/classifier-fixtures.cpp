#include "cupti_trace.h"
#include <functional>
extern "C" CUptiResult CUPTIAPI cuptiGetResultString(CUptiResult,const char**s){*s="mock";return CUPTI_SUCCESS;}
extern "C" CUptiResult CUPTIAPI cuptiActivityFlushAll(uint32_t){return CUPTI_SUCCESS;}
extern "C" CUptiResult CUPTIAPI cuptiEnableDomain(uint32_t,CUpti_SubscriberHandle,CUpti_CallbackDomain){return CUPTI_SUCCESS;}
extern "C" CUptiResult CUPTIAPI cuptiActivityDisable(CUpti_ActivityKind){return CUPTI_SUCCESS;}
extern "C" CUptiResult CUPTIAPI cuptiUnsubscribe(CUpti_SubscriberHandle){return CUPTI_SUCCESS;}
using namespace ce_trace;
static void fixture(){
 records.clear();callbacks.clear();cases.clear();active_case=0;dropped=0;errors=0;initialized=true;
 for(unsigned i=1;i<=24;++i){
  Case c;c.id=i;c.start=1000*i;c.end=c.start+900;c.ce=i<=12?i%2==0:i%2==1;c.source=((i-1)%12)/6;c.destination=1-c.source;c.mode=i<=12?"PUSH":"PULL";c.executor=i<=12?c.source:c.destination;c.device=c.executor;c.source_device=c.source;c.target_device=c.destination;c.context=10+c.executor;c.stream_id=20+c.executor;c.stream=(CUstream)(uintptr_t)(30+c.executor);c.src=0x10000000+0x1000000*c.source;c.dst=0x30000000+0x1000000*c.destination;c.bytes=4;cases.push_back(c);
  Record e;e.kind=CUPTI_ACTIVITY_KIND_EXTERNAL_CORRELATION;e.corr=100+i;e.external=i;records.push_back(e);
  Record r;r.kind=c.ce?CUPTI_ACTIVITY_KIND_MEMCPY:CUPTI_ACTIVITY_KIND_CONCURRENT_KERNEL;r.corr=100+i;r.device=c.device;r.context=c.context;r.stream=c.stream_id;r.start=c.start+100;r.end=c.start+700;r.bytes=4;r.channel_type=c.ce?CUPTI_CHANNEL_TYPE_ASYNC_MEMCPY:CUPTI_CHANNEL_TYPE_COMPUTE;r.copy_kind=CUPTI_ACTIVITY_MEMCPY_KIND_DTOD;r.src_kind=r.dst_kind=CUPTI_ACTIVITY_MEMORY_KIND_DEVICE;std::strcpy(r.name,"peer_push_kernel");records.push_back(r);
  if(c.ce){Callback b;b.case_id=i;b.corr=100+i;b.context=c.context;b.cbid=CUPTI_DRIVER_TRACE_CBID_cuMemcpyDtoDAsync_v2;b.site=CUPTI_API_ENTER;b.src=c.src;b.dst=c.dst;b.bytes=c.bytes;b.stream=c.stream;b.is_d2d=true;callbacks.push_back(b);b.site=CUPTI_API_EXIT;b.result=CUDA_SUCCESS;callbacks.push_back(b);Record a;a.kind=CUPTI_ACTIVITY_KIND_DRIVER;a.corr=100+i;a.cbid=b.cbid;records.push_back(a);}
 }
}
static Record& ce(){for(auto&r:records)if(r.kind==CUPTI_ACTIVITY_KIND_MEMCPY)return r;std::abort();}
static Record& pull(){for(auto&r:records)if(r.corr==113 && r.kind==CUPTI_ACTIVITY_KIND_MEMCPY)return r;std::abort();}
static Record& sm(){for(auto&r:records)if(r.kind==CUPTI_ACTIVITY_KIND_CONCURRENT_KERNEL)return r;std::abort();}
int main(){
 if(!std::freopen("/dev/null","w",stdout))return 90;
 unsigned n=0;auto test=[&](const char*name,const std::function<void()>&mutate,bool expected){fixture();mutate();Summary s=finish();bool ready=s.complete&&s.ce_cases==12&&s.ce_observed==12&&s.sm_observed==12;if(ready!=expected){std::fprintf(stderr,"FAIL %s ready=%d expected=%d\n",name,ready,expected);std::exit(1);}++n;};
 test("valid",[]{},true);
 test("dropped",[]{dropped=1;},false);
 test("parser_error",[]{errors=1;},false);
 test("missing_case",[]{cases.pop_back();},false);
 test("missing_d2d_exit",[]{callbacks.erase(callbacks.begin()+1);},false);
 test("duplicate_d2d_entry",[]{callbacks.push_back(callbacks.front());},false);
 test("wrong_callback_source",[]{callbacks[0].src+=4;},false);
 test("wrong_callback_target",[]{callbacks[1].dst+=4;},false);
 test("wrong_callback_length",[]{callbacks[0].bytes+=4;},false);
 test("wrong_callback_context",[]{callbacks[0].context++;},false);
 test("wrong_callback_stream",[]{callbacks[0].stream=nullptr;},false);
 test("driver_api_failure",[]{callbacks[1].result=1;},false);
 test("missing_driver_activity",[]{for(auto&r:records)if(r.kind==CUPTI_ACTIVITY_KIND_DRIVER){r.cbid=0;break;}},false);
 test("ce_wrong_executor",[]{ce().device=1;},false);
 test("ce_wrong_context",[]{ce().context++;},false);
 test("ce_wrong_stream",[]{ce().stream++;},false);
 test("ce_wrong_channel",[]{ce().channel_type=CUPTI_CHANNEL_TYPE_COMPUTE;},false);
 test("ce_wrong_bytes",[]{ce().bytes=8;},false);
 test("ce_host_source",[]{ce().src_kind=CUPTI_ACTIVITY_MEMORY_KIND_PAGEABLE;},false);
 test("ce_host_target",[]{ce().dst_kind=CUPTI_ACTIVITY_MEMORY_KIND_PINNED;},false);
 test("ce_no_timestamp",[]{ce().start=0;},false);
 test("ce_past_case",[]{ce().end=9999999;},false);
 test("ce_wrong_copykind",[]{ce().copy_kind=CUPTI_ACTIVITY_MEMCPY_KIND_HTOD;},false);
 test("ce_wrong_correlation",[]{ce().corr=999999;},false);
 test("ptop_valid",[]{auto&r=ce();r.kind=CUPTI_ACTIVITY_KIND_MEMCPY2;r.copy_kind=CUPTI_ACTIVITY_MEMCPY_KIND_PTOP;r.src_device=0;r.dst_device=1;},true);
 test("ptop_wrong_target",[]{auto&r=ce();r.kind=CUPTI_ACTIVITY_KIND_MEMCPY2;r.copy_kind=CUPTI_ACTIVITY_MEMCPY_KIND_PTOP;r.src_device=0;r.dst_device=0;},false);
 test("pull_ptop_valid",[]{auto&r=pull();r.kind=CUPTI_ACTIVITY_KIND_MEMCPY2;r.copy_kind=CUPTI_ACTIVITY_MEMCPY_KIND_PTOP;r.src_device=0;r.dst_device=1;},true);
 test("pull_executor_wrongly_source",[]{pull().device=0;},false);
 test("pull_ptop_source_confused_with_executor",[]{auto&r=pull();r.kind=CUPTI_ACTIVITY_KIND_MEMCPY2;r.copy_kind=CUPTI_ACTIVITY_MEMCPY_KIND_PTOP;r.src_device=1;r.dst_device=1;},false);
 test("pull_wrong_context",[]{pull().context=10;},false);
 test("pull_wrong_stream",[]{pull().stream=20;},false);
 test("pull_wrong_ce_channel",[]{pull().channel_type=CUPTI_CHANNEL_TYPE_COMPUTE;},false);
 test("pull_wrong_bytes",[]{pull().bytes=8;},false);
 test("pull_host_source",[]{pull().src_kind=CUPTI_ACTIVITY_MEMORY_KIND_PAGEABLE;},false);
 test("pull_wrong_timestamp",[]{pull().start=0;},false);
 test("sm_wrong_name",[]{std::strcpy(sm().name,"unrelated_kernel");},false);
 test("sm_missing",[]{sm().kind=CUPTI_ACTIVITY_KIND_DRIVER;},false);
 test("sm_duplicate",[]{records.push_back(sm());},false);
 test("unattributed_during_case",[]{Record r=ce();r.corr=999999;records.push_back(r);},false);
 test("correlation_conflict",[]{Record r;r.kind=CUPTI_ACTIVITY_KIND_EXTERNAL_CORRELATION;r.corr=102;r.external=3;records.push_back(r);},false);
 std::fprintf(stderr,"PASS %u/%u classifier scenarios; CPU only, CUPTI APIs mocked\n",n,n);return 0;
}
