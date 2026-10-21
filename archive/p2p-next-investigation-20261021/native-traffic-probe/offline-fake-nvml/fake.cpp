#include "../include/nvml.h"
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
static nvmlDevice_t handle(uintptr_t i){nvmlDevice_t d{};static_assert(sizeof(d)==sizeof(i),"opaque_handle_size");std::memcpy(&d,&i,sizeof(d));return d;}
static uintptr_t number(nvmlDevice_t d){uintptr_t i=0;std::memcpy(&i,&d,sizeof(i));return i;}
static std::atomic<unsigned> calls{0};
extern "C" {
nvmlReturn_t nvmlInit_v2(){return NVML_SUCCESS;}
nvmlReturn_t nvmlShutdown(){return NVML_SUCCESS;}
nvmlReturn_t nvmlDeviceGetHandleByPciBusId_v2(const char*b,nvmlDevice_t*d){
 if(!std::strcmp(b,"0000:01:00.0"))*d=handle(1);
 else if(!std::strcmp(b,"0000:06:00.0"))*d=handle(2);
 else return NVML_ERROR_NOT_FOUND;return NVML_SUCCESS;
}
nvmlReturn_t nvmlDeviceGetUUID(nvmlDevice_t d,char*uuid,unsigned size){
 const char*u=number(d)==1?"GPU-00000000-0000-0000-0000-000000000001":"GPU-00000000-0000-0000-0000-000000000002";
 if(std::getenv("FAKE_BAD_UUID"))u="GPU-other";std::snprintf(uuid,size,"%s",u);return NVML_SUCCESS;
}
nvmlReturn_t nvmlDeviceGetPcieThroughput(nvmlDevice_t d,nvmlPcieUtilCounter_t c,unsigned*v){
 unsigned n=++calls;
 if(std::getenv("FAKE_PREFLIGHT_FAIL")||(std::getenv("FAKE_LATE_FAIL")&&n>20)){*v=0;return NVML_ERROR_NOT_SUPPORTED;}
 *v=unsigned(number(d))*100+unsigned(c);return NVML_SUCCESS;
}
}
