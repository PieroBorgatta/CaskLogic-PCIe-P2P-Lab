#pragma once
// Diagnostic only. No PCI configuration writes, BAR writes, or guessed addresses.
#include <algorithm>
#include <cerrno>
#include <cctype>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <limits>
#include <map>
#include <regex>
#include <sstream>
#include <string>
#include <vector>
#if defined(__linux__)
#include <fcntl.h>
#include <sys/klog.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <signal.h>
#include <setjmp.h>
#endif

namespace cpubar {
using U = uint64_t;
struct Record { std::string kind; std::map<std::string,std::string> f; size_t order=0; };
struct Query {
    std::string begin, end, owner_bdf, requester_bdf, owner_uuid, requester_uuid;
    U va=0, size=0, useful=4;
};
struct Window { U id=0, offset=0, physical=0, dma=0, bar=0, bar_size=0, size=0; };
inline bool number(const std::string &s,U &n,int base=16) {
    if(s.empty() || s.size()>18 || s[0]=='-' || s[0]=='+') return false;
    for(size_t i=0;i<s.size();++i) {
        if(base==16 && i==1 && s[0]=='0' && (s[i]=='x'||s[i]=='X')) continue;
        if(!((s[i]>='0'&&s[i]<='9') || (base==16&&((s[i]>='a'&&s[i]<='f')||(s[i]>='A'&&s[i]<='F'))))) return false;
    }
    char *end=nullptr; errno=0; unsigned long long v=strtoull(s.c_str(),&end,base);
    if(errno||!end||*end) return false; n=static_cast<U>(v); return true;
}
inline bool get(const Record&r,const char *key,U&v,int base=16) {
    auto i=r.f.find(key);return i!=r.f.end()&&number(i->second,v,base);
}
inline std::string field(const Record&r,const char *key) { auto i=r.f.find(key);return i==r.f.end()?"":i->second; }
inline bool equal(const Record&r,const char *key,U v,int base=16) {U n=0;return get(r,key,n,base)&&n==v;}
inline std::string trim(std::string s) {auto a=s.find_first_not_of(" \t\r");if(a==std::string::npos)return "";return s.substr(a,s.find_last_not_of(" \t\r")-a+1);}
inline bool parse_record(const std::string&line,size_t order,Record&r) {
    auto p=line.find("P2PTRC ");if(p==std::string::npos)return false;
    p+=7;auto e=line.find(' ',p);if(e==std::string::npos)return false;
    r.kind=line.substr(p,e-p);r.order=order;
    const std::string tail=line.substr(e+1);
    static const std::regex key("(?:^|[ \\t])([a-zA-Z0-9_]+)=");
    std::vector<std::pair<std::string,std::pair<size_t,size_t>>> matches;
    for(std::sregex_iterator i(tail.begin(),tail.end(),key),end;i!=end;++i)
        matches.push_back({(*i)[1].str(),{static_cast<size_t>(i->position()),static_cast<size_t>(i->position()+i->length())}});
    for(size_t i=0;i<matches.size();++i) {
        size_t start=matches[i].second.second,stop=i+1<matches.size()?matches[i+1].second.first:tail.size();
        if(!r.f.emplace(matches[i].first,trim(tail.substr(start,stop-start))).second)return false;
    }
    return !r.f.empty();
}
inline bool uuid_ok(const std::string&s) {return std::regex_match(s,std::regex("GPU-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"));}
inline bool bdf_ok(const std::string&s) {return std::regex_match(s,std::regex("[0-9a-f]{4}:[0-9a-f]{2}:[0-1][0-9a-f]\\.[0-7]"));}
inline bool gpu_matches(const Record&r,const std::string&uuid) {
    const auto s=field(r,"gpu");auto p=s.find(uuid);if(p==std::string::npos)return false;
    return (p==0||!(std::isalnum(static_cast<unsigned char>(s[p-1]))||s[p-1]=='-')) &&
           (p+uuid.size()==s.size()||!(std::isalnum(static_cast<unsigned char>(s[p+uuid.size()]))||s[p+uuid.size()]=='-'));
}
template<class F> inline const Record* unique(const std::vector<Record>&rs,const char*kind,F pred,std::string&error) {
    const Record*found=nullptr;for(const auto&r:rs)if(r.kind==kind&&pred(r)) {if(found){error=std::string("ambiguous_")+kind;return nullptr;}found=&r;}
    if(!found)error=std::string("missing_")+kind;return found;
}
// Pure parser, also exercised on local fixtures. It never opens a device.
inline bool resolve(const std::string&log,const Query&q,Window&w,std::string&error) {
    error.clear();w={};
    if(q.begin.empty()||q.end.empty()||!bdf_ok(q.owner_bdf)||!bdf_ok(q.requester_bdf)||q.owner_bdf==q.requester_bdf||
       !uuid_ok(q.owner_uuid)||!uuid_ok(q.requester_uuid)||q.owner_uuid==q.requester_uuid||q.va==0||q.size<4||q.useful!=4){error="invalid_query";return false;}
    std::vector<std::string> lines;std::istringstream in(log);std::string l;while(std::getline(in,l))lines.push_back(l);
    size_t begin=lines.size(),end=lines.size();unsigned nb=0,ne=0;
    for(size_t i=0;i<lines.size();++i){if(lines[i].find(q.begin)!=std::string::npos){begin=i;++nb;}if(lines[i].find(q.end)!=std::string::npos){end=i;++ne;}}
    if(nb!=1||ne!=1||begin>=end){error="missing_duplicate_or_reversed_markers";return false;}
    std::vector<Record>rs;
    for(size_t i=begin+1;i<end;++i)if(lines[i].find("P2PTRC ")!=std::string::npos){Record r;if(!parse_record(lines[i],i,r)){error="malformed_trace";return false;}rs.push_back(r);}
    auto a=unique(rs,"UVM_ALLOCATION",[&](const Record&r){return gpu_matches(r,q.requester_uuid)&&equal(r,"gpu_va",q.va);},error);if(!a)return false;
    U mem=0;if(!get(*a,"rm_mem",mem)||!mem||!equal(*a,"map_offset",0)||!equal(*a,"length",q.size)||!equal(*a,"allocation_size",q.size)){error="allocation_range";return false;}
    auto req=unique(rs,"RM_REQUEST",[&](const Record&r){return equal(r,"mem",mem);},error);if(!req)return false;
    U client=0,src=0,dst=0,dma=0;
    const std::string desc=field(*req,"desc");U desc_value=0;
    if(!get(*req,"client",client)||!get(*req,"src",src,10)||!get(*req,"dst",dst,10)||src==dst||
       !number(desc,desc_value)||!desc_value||!get(*req,"dma",dma)||!dma||!equal(*req,"dynamic",1,10)||
       !equal(*req,"offset",0)||!equal(*req,"size",q.size)){error="request_fields_or_descriptor";return false;}
    auto win=unique(rs,"WINDOW_CREATE",[&](const Record&r){return equal(r,"mem",mem)&&equal(r,"src",src,10)&&equal(r,"dst",dst,10)&&field(r,"desc")==desc;},error);if(!win)return false;
    if(!get(*win,"id",w.id,10)||!w.id||!get(*win,"bar1_off",w.offset)||!get(*win,"window_phys",w.physical)||
       !get(*win,"bar1",w.bar)||!get(*win,"bar1_size",w.bar_size)||!get(*win,"size",w.size)||
       !get(*win,"dma",w.dma)||w.dma!=dma||w.size!=q.size||!equal(*win,"ranges",1,10)||
       w.offset>w.bar_size||w.size>w.bar_size-w.offset||w.bar>UINT64_MAX-w.offset||w.physical!=w.bar+w.offset||
       (w.offset&3)||!w.bar){error="window_bounds_or_address";return false;}
    auto pte=unique(rs,"RM_PTE",[&](const Record&r){return equal(r,"client",client)&&equal(r,"src",src,10)&&equal(r,"dst",dst,10)&&field(r,"desc")==desc;},error);if(!pte)return false;
    U raw0=0,raw1=0,entry=0,page=0,aperture=0;
    if(!get(*pte,"raw0",raw0)||!get(*pte,"raw1",raw1)||!get(*pte,"entry",entry,10)||(entry!=8&&entry!=16)||
       !get(*pte,"page",page)||page<0x1000||(page&(page-1))||!get(*pte,"aperture",aperture,10)||(aperture!=2&&aperture!=3)||
       !equal(*pte,"valid",1,10)||!equal(*pte,"dynamic",1,10)||!equal(*pte,"offset",0)||
       !equal(*pte,"dma_base",dma)||!equal(*pte,"phys_input",dma)||!equal(*pte,"decoded",dma)||
       !equal(*pte,"readonly",0,10)||!equal(*pte,"fmt",2,10)||!equal(*pte,"addr_shift",12,10)||
       !(raw0&1)||((raw0>>1)&3)!=aperture||(((raw0>>8)&((U(1)<<46)-1))<<12)!=dma){error="rm_pte_mismatch";return false;}
    auto ret=unique(rs,"RM_RETURN",[&](const Record&r){return equal(r,"client",client)&&equal(r,"mem",mem)&&equal(r,"src",src,10);},error);
    if(!ret||!equal(*ret,"status",0)){if(error.empty())error="rm_return_error";return false;}
    auto up=unique(rs,"UVM_PTE",[&](const Record&r){return gpu_matches(r,q.requester_uuid)&&equal(r,"mem",mem)&&equal(r,"gpu_va",q.va);},error);if(!up)return false;
    if(!equal(*up,"map_offset",0)||!equal(*up,"map_size",q.size)||!equal(*up,"entry",entry,10)||
       !equal(*up,"page",page)||!equal(*up,"raw0",raw0)||!equal(*up,"raw1",raw1)){error="uvm_pte_mismatch";return false;}
    auto sub=unique(rs,"UVM_SUBMIT",[&](const Record&r){return gpu_matches(r,q.requester_uuid)&&equal(r,"mem",mem)&&equal(r,"gpu_va",q.va);},error);
    if(!sub||!equal(*sub,"status",0)){if(error.empty())error="uvm_submit_error";return false;}
    // Owner and requester can have separate MAP_COMPLETE records for the same VA.
    // Bind this completion to the selected submission before the next mapping.
    size_t completion_end=end;
    for(const auto&r:rs)if(r.kind=="UVM_ALLOCATION"&&r.order>sub->order&&equal(r,"gpu_va",q.va))completion_end=std::min(completion_end,r.order);
    auto done=unique(rs,"UVM_MAP_COMPLETE",[&](const Record&r){return r.order>sub->order&&r.order<completion_end&&equal(r,"gpu_va",q.va)&&equal(r,"length",q.size);},error);
    if(!done||!equal(*done,"status",0)){if(error.empty())error="uvm_complete_error";return false;}
    auto dm=unique(rs,"DMA_MAP",[&](const Record&r){return field(r,"src")==q.requester_bdf&&field(r,"dst")==q.owner_bdf&&equal(r,"input",w.physical)&&equal(r,"output",dma);},error);if(!dm)return false;
    U end_resource=0,os_page=0,pages=0;
    if(!equal(*dm,"status",0)||!equal(*dm,"bar_index",1,10)||!equal(*dm,"resource_start",w.bar)||
       !get(*dm,"resource_end",end_resource)||end_resource<w.bar||end_resource-w.bar==UINT64_MAX||end_resource-w.bar+1!=w.bar_size||
       !get(*dm,"os_page",os_page,10)||!os_page||(os_page&(os_page-1))||!get(*dm,"pages",pages)||
       pages>UINT64_MAX/os_page||pages*os_page<w.size){error="dma_resource_mismatch";return false;}
    if(!(a->order<req->order&&dm->order<win->order&&win->order<req->order&&req->order<pte->order&&pte->order<ret->order&&ret->order<up->order&&up->order<sub->order&&sub->order<done->order)){error="trace_order";return false;}
    // Detect a lifetime ending even after the end marker but before this read_all snapshot.
    for(size_t i=begin+1;i<lines.size();++i)if(lines[i].find("P2PTRC ")!=std::string::npos){Record r;if(!parse_record(lines[i],i,r)){error="malformed_after_begin";return false;}
        if((r.kind=="WINDOW_DESTROY_BEGIN"||r.kind=="WINDOW_DESTROY_DONE")&&equal(r,"id",w.id,10)){error="window_destroyed";return false;}
        if(i>end&&r.kind=="WINDOW_CREATE"&&equal(r,"id",w.id,10)){error="window_id_recreated";return false;}}
    return true;
}

struct Identity { std::string bdf,uuid;U vendor=0,device=0,klass=0,start=0,end=0,flags=0; };
inline bool same_identity(const Identity&a,const Identity&b) {return a.bdf==b.bdf&&a.uuid==b.uuid&&a.vendor==b.vendor&&a.device==b.device&&a.klass==b.klass&&a.start==b.start&&a.end==b.end&&a.flags==b.flags;}
inline bool identity(const std::string&bdf,const std::string&uuid,Identity&out,std::string&error) {
    if(!bdf_ok(bdf)||!uuid_ok(uuid)){error="invalid_identity";return false;}
    Identity id;id.bdf=bdf;id.uuid=uuid;std::string base="/sys/bus/pci/devices/"+bdf+"/",s;
    for(auto pair:{std::make_pair("vendor",&id.vendor),std::make_pair("device",&id.device),std::make_pair("class",&id.klass)}){
        std::ifstream f(base+pair.first);if(!std::getline(f,s)||!number(trim(s),*pair.second)){error="identity_read_failed";return false;}}
    if(id.vendor!=0x10de||id.device==0||id.device>=0xffff||(id.klass&0xff0000)!=0x030000){error="identity_not_nvidia_gpu";return false;}
    std::ifstream info("/proc/driver/nvidia/gpus/"+bdf+"/information");bool found=false;
    while(std::getline(info,s))if(s.rfind("GPU UUID:",0)==0){if(found||trim(s.substr(9))!=uuid){error="proc_uuid_mismatch";return false;}found=true;}
    if(!found){error="missing_proc_uuid";return false;}
    std::ifstream res(base+"resource");std::string line;if(!std::getline(res,line)||!std::getline(res,line)){error="resource_missing";return false;}
    std::istringstream tokens(line);std::string start,end,flags,extra;
    if(!(tokens>>start>>end>>flags)||(tokens>>extra)||!number(start,id.start)||!number(end,id.end)||!number(flags,id.flags)||
       !id.start||id.end<id.start||(id.flags&0x200)==0||(id.flags&0x100)!=0){error="resource_invalid";return false;}
    out=id;return true;
}
inline bool read_kernel_log(std::string&log,std::string&error) {
#if defined(__linux__)
    int size=klogctl(10,nullptr,0); // SYSLOG_ACTION_SIZE_BUFFER: no clearing.
    if(size<=0||size>16*1024*1024){error="klog_size_unavailable";return false;}
    std::vector<char>b(static_cast<size_t>(size)+1);int n=klogctl(3,b.data(),size); // READ_ALL, never READ_CLEAR.
    if(n<0||n>size){error="klog_read_all_failed";return false;}log.assign(b.data(),static_cast<size_t>(n));return true;
#else
    (void)log;error="linux_required";return false;
#endif
}

#if defined(__linux__)
static thread_local sigjmp_buf fault_env;
static thread_local volatile sig_atomic_t fault_active=0;
static void fault_handler(int signo){if(fault_active)siglongjmp(fault_env,signo);_exit(128+signo);}
inline bool guarded_read(const volatile uint32_t *ptr,uint32_t&value,std::string&error){
    struct sigaction handler{},old_bus{},old_segv{};handler.sa_handler=fault_handler;sigemptyset(&handler.sa_mask);
    if(sigaction(SIGBUS,&handler,&old_bus)!=0){error="sigbus_guard_failed";return false;}
    if(sigaction(SIGSEGV,&handler,&old_segv)!=0){sigaction(SIGBUS,&old_bus,nullptr);error="sigsegv_guard_failed";return false;}
    int fault=sigsetjmp(fault_env,1);if(fault==0){fault_active=1;asm volatile("" ::: "memory");value=*ptr;asm volatile("" ::: "memory");}
    fault_active=0;int r1=sigaction(SIGBUS,&old_bus,nullptr),r2=sigaction(SIGSEGV,&old_segv,nullptr);
    if(r1||r2){error="signal_restore_failed";return false;}if(fault){error="mmio_signal_"+std::to_string(fault);return false;}return true;
}
#endif
class ReadOnlyWord {
    void *mapping_=nullptr;size_t length_=0,delta_=0;int fd_=-1;
public:
    ReadOnlyWord()=default;ReadOnlyWord(const ReadOnlyWord&)=delete;ReadOnlyWord&operator=(const ReadOnlyWord&)=delete;
    ~ReadOnlyWord(){close();}
    void close(){
#if defined(__linux__)
        if(mapping_)munmap(mapping_,length_);if(fd_>=0)::close(fd_);
#endif
        mapping_=nullptr;fd_=-1;length_=delta_=0;
    }
    bool open(const Identity&id,const Window&w,std::string&error){
#if defined(__linux__)
        close();Identity now;if(!identity(id.bdf,id.uuid,now,error)||!same_identity(id,now)){if(error.empty())error="identity_changed";return false;}
        const long ps=sysconf(_SC_PAGESIZE);if(ps<=0||(ps&(ps-1))){error="page_size";return false;}
        const U page=static_cast<U>(ps),offset=w.offset&~(page-1),delta=w.offset-offset;
        if(id.start!=w.bar||id.end-id.start+1!=w.bar_size||delta>page-4||w.offset>w.bar_size||w.bar_size-w.offset<4||
           offset>w.bar_size||w.bar_size-offset<page||offset>static_cast<U>(std::numeric_limits<off_t>::max())||w.size<4){error="mmap_bounds";return false;}
        const std::string path="/sys/bus/pci/devices/"+id.bdf+"/resource1";
        fd_=::open(path.c_str(),O_RDONLY|O_CLOEXEC|O_NOFOLLOW);if(fd_<0){error="resource1_open_failed_"+std::to_string(errno);return false;}
        struct stat st{};if(fstat(fd_,&st)!=0||st.st_size<0||static_cast<U>(st.st_size)!=w.bar_size){error="resource1_stat_mismatch";close();return false;}
        void*p=mmap(nullptr,static_cast<size_t>(page),PROT_READ,MAP_SHARED,fd_,static_cast<off_t>(offset));
        if(p==MAP_FAILED){error="resource1_mmap_failed_"+std::to_string(errno);close();return false;}
        if(p==nullptr){munmap(p,static_cast<size_t>(page));error="null_mapping_address";close();return false;}
        mapping_=p;length_=static_cast<size_t>(page);delta_=static_cast<size_t>(delta);return true;
#else
        (void)id;(void)w;error="linux_required";return false;
#endif
    }
    bool read(uint32_t&word,std::string&error){
#if defined(__linux__)
        if(!mapping_){error="not_mapped";return false;}
        return guarded_read(reinterpret_cast<const volatile uint32_t*>(static_cast<const char*>(mapping_)+delta_),word,error);
#else
        (void)word;error="linux_required";return false;
#endif
    }
};
} // namespace cpubar
