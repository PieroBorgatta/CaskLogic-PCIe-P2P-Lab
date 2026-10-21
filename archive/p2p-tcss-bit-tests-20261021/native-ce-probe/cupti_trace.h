#ifndef CASKLOGIC_CUPTI_TRACE_H
#define CASKLOGIC_CUPTI_TRACE_H
#include <cupti.h>
#include <cupti_activity.h>
#include <cupti_callbacks.h>
#include <cupti_driver_cbid.h>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <mutex>
#include <stdexcept>
#include <vector>

// CUPTI 12.6 record ABI. No CUDA calls or payload access in callbacks.
namespace ce_trace {
static_assert(CUPTI_API_VERSION == 24, "This parser requires CUPTI 12.6 headers");
static constexpr size_t MAX_RECORDS=16384;
struct Record {
 uint32_t kind=0,corr=0,device=0,context=0,stream=0,channel=0,channel_type=0;
 uint32_t copy_kind=0,src_kind=0,dst_kind=0,src_device=0,dst_device=0,cbid=0;
 uint64_t start=0,end=0,bytes=0,external=0; char name[128]{};
};
struct Callback {
 uint64_t case_id=0;uint32_t corr=0,context=0,cbid=0,site=0;
 CUdeviceptr src=0,dst=0;size_t bytes=0;CUstream stream=nullptr;
 int result=-1;bool is_d2d=false;
};
struct Case {
 uint64_t id=0,start=0,end=0;bool ce=false;int source=-1,destination=-1;
 uint32_t device=0,context=0,stream_id=0,target_device=0;
 CUdeviceptr src=0,dst=0;size_t bytes=0;CUstream stream=nullptr;
};
struct Summary {bool complete=false;unsigned ce_cases=0,ce_observed=0,sm_observed=0;uint64_t dropped=0;unsigned errors=0;};
static std::mutex trace_mutex;
static std::vector<Record> records;
static std::vector<Callback> callbacks;
static std::vector<Case> cases;
static std::atomic<uint64_t> active_case{0},dropped{0};
static std::atomic<unsigned> errors{0};
static CUpti_SubscriberHandle subscriber{};
static bool initialized=false;
static void check(CUptiResult r,const char*where){if(r!=CUPTI_SUCCESS){const char*s="unknown";cuptiGetResultString(r,&s);std::printf("CUPTI_ERROR where=%s code=%d text=%s\n",where,int(r),s);throw std::runtime_error("cupti_failure");}}
static void CUPTIAPI buffer_requested(uint8_t**buffer,size_t*size,size_t*max_records){
 *size=1024*1024;*max_records=0;void*p=nullptr;
 if(posix_memalign(&p,8,*size)!=0){*buffer=nullptr;*size=0;++errors;return;}
 *buffer=static_cast<uint8_t*>(p);
}
static void CUPTIAPI buffer_completed(CUcontext context,uint32_t stream,uint8_t*buffer,size_t,size_t valid){
 try{
  CUpti_Activity*a=nullptr;
  for(;;){CUptiResult r=cuptiActivityGetNextRecord(buffer,valid,&a);if(r==CUPTI_ERROR_MAX_LIMIT_REACHED)break;if(r!=CUPTI_SUCCESS){++errors;break;}
   Record x;x.kind=uint32_t(a->kind);bool keep=true;
   if(a->kind==CUPTI_ACTIVITY_KIND_MEMCPY){const auto*p=reinterpret_cast<const CUpti_ActivityMemcpy5*>(a);
    x.corr=p->correlationId;x.device=p->deviceId;x.context=p->contextId;x.stream=p->streamId;x.channel=p->channelID;x.channel_type=p->channelType;
    x.copy_kind=p->copyKind;x.src_kind=p->srcKind;x.dst_kind=p->dstKind;x.bytes=p->bytes;x.start=p->start;x.end=p->end;
   }else if(a->kind==CUPTI_ACTIVITY_KIND_MEMCPY2){const auto*p=reinterpret_cast<const CUpti_ActivityMemcpyPtoP4*>(a);
    x.corr=p->correlationId;x.device=p->deviceId;x.context=p->contextId;x.stream=p->streamId;x.channel=p->channelID;x.channel_type=p->channelType;
    x.copy_kind=p->copyKind;x.src_kind=p->srcKind;x.dst_kind=p->dstKind;x.bytes=p->bytes;x.start=p->start;x.end=p->end;x.src_device=p->srcDeviceId;x.dst_device=p->dstDeviceId;
   }else if(a->kind==CUPTI_ACTIVITY_KIND_CONCURRENT_KERNEL){const auto*p=reinterpret_cast<const CUpti_ActivityKernel9*>(a);
    x.corr=p->correlationId;x.device=p->deviceId;x.context=p->contextId;x.stream=p->streamId;x.channel=p->channelID;x.channel_type=p->channelType;x.start=p->start;x.end=p->end;
    if(p->name)std::snprintf(x.name,sizeof(x.name),"%s",p->name);
   }else if(a->kind==CUPTI_ACTIVITY_KIND_DRIVER){const auto*p=reinterpret_cast<const CUpti_ActivityAPI*>(a);x.corr=p->correlationId;x.cbid=p->cbid;x.start=p->start;x.end=p->end;
   }else if(a->kind==CUPTI_ACTIVITY_KIND_EXTERNAL_CORRELATION){const auto*p=reinterpret_cast<const CUpti_ActivityExternalCorrelation*>(a);
    x.corr=p->correlationId;x.external=p->externalId;keep=p->externalKind==CUPTI_EXTERNAL_CORRELATION_KIND_CUSTOM0;
   }else keep=false;
   if(keep){std::lock_guard<std::mutex>l(trace_mutex);if(records.size()>=MAX_RECORDS)++errors;else records.push_back(x);}
  }
  size_t lost=0;CUptiResult r=cuptiActivityGetNumDroppedRecords(context,stream,&lost);if(r!=CUPTI_SUCCESS)++errors;else dropped+=lost;
 }catch(...){++errors;}
 std::free(buffer);
}
static void CUPTIAPI api_callback(void*,CUpti_CallbackDomain domain,CUpti_CallbackId cbid,const void*data){
 if(domain!=CUPTI_CB_DOMAIN_DRIVER_API)return;
 const auto*p=static_cast<const CUpti_CallbackData*>(data);const uint64_t id=active_case.load();if(!id)return;
 try{Callback x;x.case_id=id;x.corr=p->correlationId;x.context=p->contextUid;x.cbid=cbid;x.site=p->callbackSite;
  x.is_d2d=cbid==CUPTI_DRIVER_TRACE_CBID_cuMemcpyDtoDAsync_v2 || cbid==CUPTI_DRIVER_TRACE_CBID_cuMemcpyDtoDAsync_v2_ptsz;
  if(x.is_d2d && p->functionParams){const auto*q=static_cast<const cuMemcpyDtoDAsync_v2_params*>(p->functionParams);x.src=q->srcDevice;x.dst=q->dstDevice;x.bytes=q->ByteCount;x.stream=q->hStream;}
  if(p->callbackSite==CUPTI_API_EXIT && p->functionReturnValue)x.result=int(*static_cast<const CUresult*>(p->functionReturnValue));
  std::lock_guard<std::mutex>l(trace_mutex);if(callbacks.size()>=MAX_RECORDS)++errors;else callbacks.push_back(x);
 }catch(...){++errors;}
}
static void initialize(){
 uint32_t version=0;check(cuptiGetVersion(&version),"version");if(version!=24)throw std::runtime_error("cupti_runtime_version_not_12_6");
 records.reserve(MAX_RECORDS);callbacks.reserve(MAX_RECORDS);cases.reserve(12);
 check(cuptiSubscribe(&subscriber,api_callback,nullptr),"subscribe");
 check(cuptiActivityRegisterCallbacks(buffer_requested,buffer_completed),"activity_callbacks");
 check(cuptiEnableDomain(1,subscriber,CUPTI_CB_DOMAIN_DRIVER_API),"driver_callbacks");
 for(auto k:{CUPTI_ACTIVITY_KIND_DRIVER,CUPTI_ACTIVITY_KIND_MEMCPY,CUPTI_ACTIVITY_KIND_MEMCPY2,CUPTI_ACTIVITY_KIND_CONCURRENT_KERNEL,CUPTI_ACTIVITY_KIND_EXTERNAL_CORRELATION})check(cuptiActivityEnable(k),"activity_enable");
 initialized=true;std::printf("CUPTI_READY version=%u memcpy_record=5 ptop_record=4 kernel_record=9\n",version);
}
static void begin(uint64_t id,bool ce,int source,int destination,CUcontext context,CUcontext target,CUstream stream,CUdeviceptr src,CUdeviceptr dst,size_t bytes){
 if(!initialized || active_case.load() || !id)throw std::runtime_error("trace_begin_state");
 Case c;c.id=id;c.ce=ce;c.source=source;c.destination=destination;c.stream=stream;c.src=src;c.dst=dst;c.bytes=bytes;
 check(cuptiGetDeviceId(context,&c.device),"device_id");check(cuptiGetDeviceId(target,&c.target_device),"target_device_id");
 check(cuptiGetContextId(context,&c.context),"context_id");check(cuptiGetStreamIdEx(context,stream,0,&c.stream_id),"stream_id");
 check(cuptiActivityFlushAll(0),"precase_flush");check(cuptiGetTimestamp(&c.start),"begin_timestamp");
 cases.push_back(c);check(cuptiActivityPushExternalCorrelationId(CUPTI_EXTERNAL_CORRELATION_KIND_CUSTOM0,id),"push_correlation");active_case=id;
 std::printf("CUPTI_CASE_BEGIN id=%llu engine=%s s=%d d=%d device=%u target_device=%u context=%u stream_id=%u stream=%p src=%llx dst=%llx bytes=%zu timestamp=%llu\n",(unsigned long long)id,ce?"CE_REQUEST":"SM",source,destination,c.device,c.target_device,c.context,c.stream_id,(void*)stream,(unsigned long long)src,(unsigned long long)dst,bytes,(unsigned long long)c.start);
}
static void end(uint64_t id){
 if(active_case.load()!=id || cases.empty() || cases.back().id!=id)throw std::runtime_error("trace_end_state");
 check(cuptiGetTimestamp(&cases.back().end),"end_timestamp");active_case=0;uint64_t popped=0;
 check(cuptiActivityPopExternalCorrelationId(CUPTI_EXTERNAL_CORRELATION_KIND_CUSTOM0,&popped),"pop_correlation");if(popped!=id)throw std::runtime_error("correlation_stack_mismatch");
 check(cuptiActivityFlushAll(0),"postcase_flush");std::printf("CUPTI_CASE_END id=%llu timestamp=%llu\n",(unsigned long long)id,(unsigned long long)cases.back().end);
}
static Summary finish(){
 if(active_case.load())throw std::runtime_error("trace_unclosed_case");
 check(cuptiActivityFlushAll(CUPTI_ACTIVITY_FLAG_FLUSH_FORCED),"final_flush");
 check(cuptiEnableDomain(0,subscriber,CUPTI_CB_DOMAIN_DRIVER_API),"disable_callbacks");
 for(auto k:{CUPTI_ACTIVITY_KIND_DRIVER,CUPTI_ACTIVITY_KIND_MEMCPY,CUPTI_ACTIVITY_KIND_MEMCPY2,CUPTI_ACTIVITY_KIND_CONCURRENT_KERNEL,CUPTI_ACTIVITY_KIND_EXTERNAL_CORRELATION})check(cuptiActivityDisable(k),"activity_disable");
 check(cuptiActivityFlushAll(CUPTI_ACTIVITY_FLAG_FLUSH_FORCED),"disabled_flush");
 check(cuptiUnsubscribe(subscriber),"unsubscribe");initialized=false;
 std::lock_guard<std::mutex>l(trace_mutex);Summary sum;sum.errors=errors.load();sum.dropped=dropped.load();sum.complete=sum.errors==0 && sum.dropped==0 && cases.size()==12;
 std::map<uint32_t,uint64_t> correlation;
 auto associate=[&](uint32_t corr,uint64_t id){auto it=correlation.find(corr);if(it!=correlation.end() && it->second!=id){sum.complete=false;++sum.errors;}else correlation[corr]=id;};
 for(const auto&r:records)if(r.kind==CUPTI_ACTIVITY_KIND_EXTERNAL_CORRELATION)associate(r.corr,r.external);
 for(const auto&c:callbacks)associate(c.corr,c.case_id);
 for(const auto&c:callbacks)std::printf("CUPTI_CALLBACK case=%llu corr=%u cbid=%u site=%u context=%u is_d2d=%d src=%llx dst=%llx bytes=%zu stream=%p result=%d\n",(unsigned long long)c.case_id,c.corr,c.cbid,c.site,c.context,c.is_d2d,(unsigned long long)c.src,(unsigned long long)c.dst,c.bytes,(void*)c.stream,c.result);
 for(const auto&r:records){auto it=correlation.find(r.corr);uint64_t id=it==correlation.end()?0:it->second;
  std::printf("CUPTI_RECORD case=%llu kind=%u corr=%u device=%u context=%u stream_id=%u channel=%u channel_type=%u copy_kind=%u src_kind=%u dst_kind=%u src_device=%u dst_device=%u bytes=%llu start=%llu end=%llu cbid=%u external=%llu name=%s\n",(unsigned long long)id,r.kind,r.corr,r.device,r.context,r.stream,r.channel,r.channel_type,r.copy_kind,r.src_kind,r.dst_kind,r.src_device,r.dst_device,(unsigned long long)r.bytes,(unsigned long long)r.start,(unsigned long long)r.end,r.cbid,(unsigned long long)r.external,r.name[0]?r.name:"none");
 }
 for(const auto&c:cases){unsigned copies=0,kernels=0,host_copies=0,unattributed=0,d2d_entries=0,d2d_exits=0,d2d_driver=0,d2d_corr=0;uint64_t total_bytes=0;bool engine_ok=true,metadata_ok=true;
  for(const auto&cb:callbacks)if(cb.case_id==c.id && cb.is_d2d){
   if(cb.site==CUPTI_API_ENTER){++d2d_entries;d2d_corr=cb.corr;}else if(cb.site==CUPTI_API_EXIT)++d2d_exits;
   if(cb.src!=c.src || cb.dst!=c.dst || cb.bytes!=c.bytes || cb.stream!=c.stream || cb.context!=c.context || (cb.site==CUPTI_API_EXIT && cb.result!=CUDA_SUCCESS))metadata_ok=false;
  }
  if(c.ce){for(const auto&cb:callbacks)if(cb.case_id==c.id && cb.is_d2d && cb.corr!=d2d_corr)metadata_ok=false;
   for(const auto&r:records)if(r.kind==CUPTI_ACTIVITY_KIND_DRIVER && r.corr==d2d_corr && (r.cbid==CUPTI_DRIVER_TRACE_CBID_cuMemcpyDtoDAsync_v2 || r.cbid==CUPTI_DRIVER_TRACE_CBID_cuMemcpyDtoDAsync_v2_ptsz))++d2d_driver;
  }
  for(const auto&r:records){bool memcpy=r.kind==CUPTI_ACTIVITY_KIND_MEMCPY || r.kind==CUPTI_ACTIVITY_KIND_MEMCPY2;bool kernel=r.kind==CUPTI_ACTIVITY_KIND_CONCURRENT_KERNEL;
   if(!memcpy && !kernel)continue;auto it=correlation.find(r.corr);uint64_t id=it==correlation.end()?0:it->second;
   if(id!=c.id){if(id==0 && r.start>=c.start && r.start<=c.end)++unattributed;continue;}
   if(r.device!=c.device || r.context!=c.context || r.stream!=c.stream_id || !r.start || r.end<r.start || r.start<c.start || r.end>c.end)metadata_ok=false;
   if(memcpy){if(c.ce && r.corr!=d2d_corr)metadata_ok=false;++copies;total_bytes+=r.bytes;if(r.src_kind!=CUPTI_ACTIVITY_MEMORY_KIND_DEVICE || r.dst_kind!=CUPTI_ACTIVITY_MEMORY_KIND_DEVICE)++host_copies;
    if(r.channel_type!=CUPTI_CHANNEL_TYPE_ASYNC_MEMCPY)engine_ok=false;
    if(r.copy_kind!=CUPTI_ACTIVITY_MEMCPY_KIND_DTOD && r.copy_kind!=CUPTI_ACTIVITY_MEMCPY_KIND_PTOP)metadata_ok=false;
    if(r.kind==CUPTI_ACTIVITY_KIND_MEMCPY2 && (r.src_device!=c.device || r.dst_device!=c.target_device))metadata_ok=false;
   }else{++kernels;if(!std::strstr(r.name,"peer_push_kernel"))metadata_ok=false;}
  }
  bool coverage=metadata_ok && unattributed==0 && (c.ce?(copies+kernels>0 && d2d_entries==1 && d2d_exits==1 && d2d_driver==1):(kernels==1 && copies==0));
  bool observed=c.ce && coverage && copies>0 && kernels==0 && engine_ok && host_copies==0 && total_bytes==c.bytes;
  if(c.ce){++sum.ce_cases;sum.ce_observed+=observed;}else sum.sm_observed+=coverage;
  sum.complete=sum.complete && coverage;
  std::printf("CUPTI_CASE_RESULT id=%llu engine=%s copies=%u kernels=%u copy_bytes=%llu host_copies=%u unattributed=%u d2d_entries=%u d2d_exits=%u d2d_driver=%u metadata_valid=%d coverage_complete=%d ce_observed=%d direct_route_proven=0\n",(unsigned long long)c.id,c.ce?"CE_REQUEST":"SM",copies,kernels,(unsigned long long)total_bytes,host_copies,unattributed,d2d_entries,d2d_exits,d2d_driver,metadata_ok,coverage,observed);
 }
 std::printf("CUPTI_SUMMARY trace_complete=%d cases=%zu ce_cases=%u ce_observed=%u sm_observed=%u dropped=%llu errors=%u direct_route_proven=0\n",sum.complete,cases.size(),sum.ce_cases,sum.ce_observed,sum.sm_observed,(unsigned long long)sum.dropped,sum.errors);
 return sum;
}
}
#endif
