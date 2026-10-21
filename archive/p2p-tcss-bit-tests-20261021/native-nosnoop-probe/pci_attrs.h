#pragma once
// Native diagnostic: writes only PCIe Device Control bits 11 and 4 on two GPUs.
// Never write Device Status (W1C), a root port, a bridge, or a BAR.
#include "cpubar_trace.h"
#include <array>
#include <ctime>
#include <cstring>
#if defined(__linux__) && defined(__x86_64__)
#include <cpuid.h>
#endif
namespace pciattrs {
constexpr uint16_t MASK=0x0810;
struct Snapshot { uint32_t id=0; uint16_t command=0,control=0,status=0; unsigned cap=0; };
inline uint16_t le16(const unsigned char*p){return uint16_t(p[0])|(uint16_t(p[1])<<8);}
inline bool decode(const unsigned char*b,size_t n,uint32_t expected,Snapshot&s,std::string&e) {
    s={};if(n<256){e="config_short";return false;}
    s.id=uint32_t(le16(b))|(uint32_t(le16(b+2))<<16);
    if(s.id!=expected||b[0x0b]!=3||(b[0x0e]&0x7f)!=0){e="endpoint_identity_or_header";return false;}
    s.command=le16(b+4);if((s.command&6)!=6){e="endpoint_memory_or_master_disabled";return false;}
    if(!(le16(b+6)&0x10)){e="capability_list_missing";return false;}
    std::array<bool,256>seen{};unsigned p=b[0x34];bool found=false;
    for(unsigned hops=0;p&&hops<48;++hops){
        if(p<0x40||p>0xfc||(p&3)||seen[p]){e="capability_chain_invalid";return false;}seen[p]=true;
        if(b[p]==0x10){
            if(found||p>0xf4){e="pcie_capability_duplicate_or_short";return false;}
            unsigned v=le16(b+p+2),type=(v>>4)&15;
            if((v&15)<1||(v&15)>2||(type!=0&&type!=1)){e="pcie_not_endpoint";return false;}
            found=true;s.cap=p;s.control=le16(b+p+8);s.status=le16(b+p+10);
        }
        p=b[p+1];
    }
    if(p||!found){e="pcie_capability_unavailable";return false;}
    return true;
}
inline uint16_t target(uint16_t current,uint16_t bits){return uint16_t((current&uint16_t(~MASK))|(bits&MASK));}
inline bool preserves_other_bits(uint16_t a,uint16_t b){return ((a^b)&uint16_t(~MASK))==0;}
class Controller {
    struct Endpoint {int fd=-1;cpubar::Identity identity;uint32_t expected_id=0;Snapshot original;bool captured=false,touched=false;};
    Endpoint ep_[2]; bool ready_=false;
    bool read(unsigned i,Snapshot&s,std::string&e){
#if defined(__linux__)
        Endpoint&x=ep_[i];cpubar::Identity now;
        if(x.fd<0||!cpubar::identity(x.identity.bdf,x.identity.uuid,now,e)||!cpubar::same_identity(now,x.identity)){if(e.empty())e="live_identity_changed";return false;}
        std::array<unsigned char,256>b{};ssize_t n=pread(x.fd,b.data(),b.size(),0);
        if(n!=static_cast<ssize_t>(b.size())){e="config_read_short_or_failed";return false;}
        if(!decode(b.data(),b.size(),x.expected_id,s,e))return false;
        if(x.captured&&s.cap!=x.original.cap){e="pcie_capability_moved";return false;}
        return true;
#else
        (void)i;(void)s;e="linux_required";return false;
#endif
    }
    bool write(unsigned i,const Snapshot&before,uint16_t wanted,std::string&e){
#if defined(__linux__)
        Endpoint&x=ep_[i];
        if(!x.captured||before.cap!=x.original.cap||!preserves_other_bits(before.control,wanted)||(before.status&0x20)){e="write_guard_or_transactions_pending";return false;}
        if(before.control==wanted)return true;
        const unsigned char bytes[2]={static_cast<unsigned char>(wanted),static_cast<unsigned char>(wanted>>8)};
        x.touched=true; // A short/failed write does not prove that no bit changed.
        ssize_t n=pwrite(x.fd,bytes,sizeof(bytes),static_cast<off_t>(before.cap+8));
        if(n!=2){e="devctl_write_short_or_failed";return false;}
        Snapshot after;if(!read(i,after,e))return false;
        printf("ATTR_WRITE device=%u bdf=%s offset=%x width=16 mask=0810 before=%04x wanted=%04x after=%04x valid=%d\n",i,x.identity.bdf.c_str(),before.cap+8,before.control,wanted,after.control,after.control==wanted);
        if(after.control!=wanted){e="devctl_write_not_held";return false;}
        return true;
#else
        (void)i;(void)before;(void)wanted;e="linux_required";return false;
#endif
    }
public:
    Controller()=default;Controller(const Controller&)=delete;Controller&operator=(const Controller&)=delete;
    ~Controller(){for(auto&x:ep_)if(x.fd>=0)::close(x.fd);}
    bool captured()const{return ep_[0].captured||ep_[1].captured;}
    bool capture(const std::string bdf[2],const std::string uuid[2],std::string&e){
#if defined(__linux__)
        if(captured()){e="already_captured";return false;}
        // Exact known native endpoints; do not accept the Xen virtual BDFs.
        const char*expected_bdf[2]={"0000:01:00.0","0000:06:00.0"};
        const char*expected_uuid[2]={"GPU-00000000-0000-0000-0000-000000000001","GPU-00000000-0000-0000-0000-000000000002"};
        const uint32_t ids[2]={0x28b010de,0x257110de};
        if(access("/sys/hypervisor/type",F_OK)==0){e="hypervisor_present";return false;}
#if defined(__x86_64__)
        unsigned a=0,b=0,c=0,d=0;
        if(!__get_cpuid(1,&a,&b,&c,&d)||a!=0x000906a3u||(c&0x80000000u)){e="unexpected_cpu_or_hypervisor";return false;}
#else
        e="native_x86_64_required";return false;
#endif
        int host=::open("/sys/bus/pci/devices/0000:00:00.0/config",O_RDONLY|O_CLOEXEC|O_NOFOLLOW);
        unsigned char host_id[4]={};ssize_t host_n=host<0?-1:pread(host,host_id,4,0);if(host>=0)::close(host);
        if(host_n!=4||le16(host_id)!=0x8086||le16(host_id+2)!=0x4641){e="unexpected_native_host_bridge";return false;}
        for(unsigned i=0;i<2;++i){Endpoint&x=ep_[i];
            if(bdf[i]!=expected_bdf[i]||uuid[i]!=expected_uuid[i]){e="unexpected_native_gpu_identity";return false;}
            if(!cpubar::identity(bdf[i],uuid[i],x.identity,e))return false;x.expected_id=ids[i];
            std::string path="/sys/bus/pci/devices/"+bdf[i]+"/config";
            x.fd=::open(path.c_str(),O_RDWR|O_CLOEXEC|O_NOFOLLOW);
            if(x.fd<0){e="config_open_failed";return false;}
            Snapshot s;if(!read(i,s,e))return false;
            if((s.control&MASK)!=MASK||(s.status&0x20)){e="baseline_attributes_or_pending";return false;}
            x.original=s;x.captured=true;
            printf("ATTR_ORIGINAL device=%u bdf=%s id=%08x cap=%02x devctl=%04x devsta=%04x width=16 mask=0810\n",i,bdf[i].c_str(),s.id,s.cap,s.control,s.status);
        }
        ready_=true;return true;
#else
        (void)bdf;(void)uuid;e="linux_required";return false;
#endif
    }
    // enabled_mode: 0=original, 1=only Ada clear, 2=both clear.
    bool set_mode(unsigned mode,std::string&e){
        if(!ready_||mode>2){e="invalid_mode_or_not_ready";return false;}
        Snapshot snapshots[2];
        for(unsigned i=0;i<2;++i){if(!read(i,snapshots[i],e))return false;
            if(!preserves_other_bits(snapshots[i].control,ep_[i].original.control)||(snapshots[i].status&0x20)){e="outside_bits_changed_or_pending";return false;}}
        for(unsigned i=0;i<2;++i){bool clear=mode==2||(mode==1&&i==0);
            // Refresh immediately before the write, after the two-endpoint precheck.
            Snapshot current;if(!read(i,current,e))return false;
            if(current.control!=snapshots[i].control||(current.status&0x20)){e="config_changed_before_write";return false;}
            if(!write(i,current,target(current.control,clear?0:ep_[i].original.control),e))return false;}
        return check("mode_committed",mode,e);
    }
    bool check(const char*label,unsigned mode,std::string&e){
        if(!ready_||mode>2){e="snapshot_not_ready";return false;}
        bool ok=true;struct timespec ts{};
        if(clock_gettime(CLOCK_MONOTONIC,&ts)!=0){e="monotonic_clock_failed";return false;}
        for(unsigned i=0;i<2;++i){Snapshot s;std::string why;
            if(!read(i,s,why)){printf("ATTR_SNAPSHOT label=%s device=%u status=INVALID reason=%s\n",label,i,why.c_str());if(e.empty())e=why;ok=false;continue;}
            uint16_t expected=target(ep_[i].original.control,(mode==2||(mode==1&&i==0))?0:ep_[i].original.control);
            bool valid=s.control==expected;
            printf("ATTR_SNAPSHOT label=%s monotonic=%lld.%09ld device=%u bdf=%s id=%08x cap=%02x devctl=%04x expected=%04x devsta=%04x pending=%u no_snoop=%u relaxed=%u valid=%d\n",label,(long long)ts.tv_sec,ts.tv_nsec,i,ep_[i].identity.bdf.c_str(),s.id,s.cap,s.control,expected,s.status,!!(s.status&0x20),!!(s.control&0x800),!!(s.control&0x10),valid);
            if(!valid){ok=false;if(e.empty())e="attributes_changed_during_operation";}}
        return ok;
    }
    bool restore(std::string&e){
        bool ok=true;
        for(unsigned i=0;i<2;++i){Endpoint&x=ep_[i];if(!x.captured)continue;
            Snapshot now;std::string why;
            if(!read(i,now,why)){ok=false;printf("ATTR_RESTORE device=%u valid=0 reason=%s\n",i,why.c_str());if(e.empty())e=why;continue;}
            bool pending=now.status&0x20;
            // Bounded polling is read-only. Do not alter the control while a
            // nonposted transaction is explicitly reported as pending.
            for(unsigned n=0;pending&&n<20;++n){usleep(5000);if(!read(i,now,why))break;pending=now.status&0x20;}
            bool restored=why.empty()&&!pending&&write(i,now,target(now.control,x.original.control),why);
            Snapshot final;
            restored=restored&&read(i,final,why)&&(final.control&MASK)==(x.original.control&MASK);
            printf("ATTR_RESTORE device=%u valid=%d mask=0810 original_bits=%04x preserved_current_other_bits=1 reason=%s\n",i,restored,x.original.control&MASK,why.empty()?(pending?"transactions_pending":"none"):why.c_str());
            if(restored)x.touched=false;else{ok=false;if(e.empty())e=why.empty()?"restore_not_confirmed":why;}
        }
        return ok;
    }
};
} // namespace pciattrs
