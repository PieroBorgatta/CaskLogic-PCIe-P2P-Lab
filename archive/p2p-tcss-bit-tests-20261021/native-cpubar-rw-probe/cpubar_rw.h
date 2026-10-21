#pragma once
// Explicit diagnostic extension: one validated 32-bit BAR1 word may be written.
// The unmodified cpubar_trace.h remains the strict trace/identity resolver.
#include "cpubar_trace.h"
namespace cpubar {
inline bool rw_bounds(const Identity&id,const Window&w,U page,U&offset,U&delta,std::string&error) {
    if(page<4||(page&(page-1))||!id.start||id.end<id.start||!w.bar_size||
       id.start!=w.bar||id.end-id.start+1!=w.bar_size||(w.offset&3)||
       w.offset>w.bar_size||w.bar_size-w.offset<4||w.size<4||
       w.offset>UINT64_MAX-id.start||w.physical!=id.start+w.offset) {
        error="rw_word_bounds";return false;
    }
    offset=w.offset&~(page-1);delta=w.offset-offset;
    if(delta>page-4||offset>w.bar_size||w.bar_size-offset<page||
       offset>static_cast<U>(std::numeric_limits<off_t>::max())) {
        error="rw_page_bounds";return false;
    }
    return true;
}
#if defined(__linux__)
inline bool guarded_write(volatile uint32_t *ptr,uint32_t value,std::string&error) {
    struct sigaction handler{},old_bus{},old_segv{};
    handler.sa_handler=fault_handler;sigemptyset(&handler.sa_mask);
    if(sigaction(SIGBUS,&handler,&old_bus)!=0){error="sigbus_guard_failed";return false;}
    if(sigaction(SIGSEGV,&handler,&old_segv)!=0){sigaction(SIGBUS,&old_bus,nullptr);error="sigsegv_guard_failed";return false;}
    int fault=sigsetjmp(fault_env,1);
    if(fault==0) {
        fault_active=1;
        asm volatile("" ::: "memory");
        *ptr=value; // Exactly one naturally aligned 32-bit store; no neighboring word.
        __sync_synchronize();
        asm volatile("" ::: "memory");
    }
    fault_active=0;
    int r1=sigaction(SIGBUS,&old_bus,nullptr),r2=sigaction(SIGSEGV,&old_segv,nullptr);
    if(r1||r2){error="signal_restore_failed";return false;}
    if(fault){error="mmio_write_signal_"+std::to_string(fault);return false;}
    return true;
}
#endif
class WritableWord {
    void *mapping_=nullptr;size_t length_=0,delta_=0;int fd_=-1;
public:
    WritableWord()=default;
    WritableWord(const WritableWord&)=delete;
    WritableWord&operator=(const WritableWord&)=delete;
    ~WritableWord(){close();}
    void close() {
#if defined(__linux__)
        if(mapping_)munmap(mapping_,length_);
        if(fd_>=0)::close(fd_);
#endif
        mapping_=nullptr;length_=delta_=0;fd_=-1;
    }
    bool open(const Identity&id,const Window&w,std::string&error) {
#if defined(__linux__)
        close();Identity now;
        if(!identity(id.bdf,id.uuid,now,error)||!same_identity(id,now)){if(error.empty())error="rw_identity_changed";return false;}
        long ps=sysconf(_SC_PAGESIZE);U offset=0,delta=0;
        if(ps<=0||!rw_bounds(id,w,static_cast<U>(ps),offset,delta,error))return false;
        std::string path="/sys/bus/pci/devices/"+id.bdf+"/resource1";
        fd_=::open(path.c_str(),O_RDWR|O_CLOEXEC|O_NOFOLLOW);
        if(fd_<0){error="rw_resource1_open_failed_"+std::to_string(errno);return false;}
        struct stat st{};
        if(fstat(fd_,&st)!=0||st.st_size<0||static_cast<U>(st.st_size)!=w.bar_size){error="rw_resource1_stat_mismatch";close();return false;}
        void *p=mmap(nullptr,static_cast<size_t>(ps),PROT_READ|PROT_WRITE,MAP_SHARED,fd_,static_cast<off_t>(offset));
        if(p==MAP_FAILED){error="rw_resource1_mmap_failed_"+std::to_string(errno);close();return false;}
        if(p==nullptr){munmap(p,static_cast<size_t>(ps));error="rw_null_mapping_address";close();return false;}
        mapping_=p;length_=static_cast<size_t>(ps);delta_=static_cast<size_t>(delta);
        if(!identity(id.bdf,id.uuid,now,error)||!same_identity(id,now)){if(error.empty())error="rw_identity_changed_after_mmap";close();return false;}
        return true;
#else
        (void)id;(void)w;error="linux_required";return false;
#endif
    }
    bool read(uint32_t&value,std::string&error) {
#if defined(__linux__)
        if(!mapping_){error="rw_not_mapped";return false;}
        return guarded_read(reinterpret_cast<const volatile uint32_t*>(static_cast<const char*>(mapping_)+delta_),value,error);
#else
        (void)value;error="linux_required";return false;
#endif
    }
    bool write(uint32_t value,std::string&error) {
#if defined(__linux__)
        if(!mapping_){error="rw_not_mapped";return false;}
        return guarded_write(reinterpret_cast<volatile uint32_t*>(static_cast<char*>(mapping_)+delta_),value,error);
#else
        (void)value;error="linux_required";return false;
#endif
    }
};
} // namespace cpubar
