#include "cpubar_trace.h"
#include <cassert>
#include <iostream>

static std::string replace(std::string s,const std::string&a,const std::string&b) {
    auto p=s.find(a);assert(p!=std::string::npos);s.replace(p,a.size(),b);return s;
}
static std::string matching_line(const std::string&s,const std::string&needle) {
    auto p=s.find(needle);assert(p!=std::string::npos);
    auto begin=s.rfind('\n',p),end=s.find('\n',p);
    return s.substr(begin==std::string::npos?0:begin+1,end-(begin==std::string::npos?0:begin+1))+"\n";
}
int main(int argc,char**argv) {
    assert(argc==2);unsigned count=0;
    const std::string ada="GPU-00000000-0000-0000-0000-000000000001";
    const std::string ampere="GPU-00000000-0000-0000-0000-000000000002";
    for(unsigned i=1;i<=4;++i) {
        cpubar::Query q;q.begin="CaskLogicCPUBAR fixture=1 phase=begin";
        q.end="CaskLogicCPUBAR fixture=1 phase=end";q.size=0x200000;
        q.va=0x7e36bf200000ULL+0x200000ULL*i;
        bool own_ada=i==1||i==4;
        q.owner_bdf=own_ada?"0000:01:00.0":"0000:06:00.0";
        q.requester_bdf=own_ada?"0000:06:00.0":"0000:01:00.0";
        q.owner_uuid=own_ada?ada:ampere;q.requester_uuid=own_ada?ampere:ada;
        std::ifstream f(std::string(argv[1])+"/live-window"+std::to_string(i)+".log");assert(f);
        std::string text,line;
        while(std::getline(f,line)) {
            // Synthetic page-granularity change only: keep addresses and raw
            // first PTE unchanged. All 512 entries fit one current UVM batch.
            if(line.find("P2PTRC RM_PTE")!=std::string::npos) {
                line=replace(line,"page=200000","page=1000");
                line=replace(line,"pte_count=1","pte_count=512");
                line=replace(line,"entry=16","entry=8");
            }
            if(line.find("P2PTRC UVM_PTE")!=std::string::npos && line.find(q.requester_uuid)!=std::string::npos) {
                line=replace(line,"page=200000","page=1000");
                line=replace(line,"count=1","count=512");
                line=replace(line,"entry=16","entry=8");
            }
            text+=line+"\n";
        }
        cpubar::Window w;std::string err;
        assert(cpubar::resolve(text,q,w,err));++count;
        assert(w.id==i&&w.size==0x200000);
        auto reject=[&](const std::string&bad) {
            cpubar::Window ignored;std::string error;
            assert(!cpubar::resolve(bad,q,ignored,error));assert(!error.empty());
            std::cout<<"EXPECTED_SKIP fixture="<<i<<" reason="<<error<<"\n";++count;
        };
        const std::string rm=matching_line(text,"P2PTRC RM_PTE");
        const std::string up=matching_line(text,"P2PTRC UVM_PTE gpu=ID "+std::string(own_ada?"9":"1"));
        reject(replace(text,q.end,rm+q.end));
        reject(replace(text,q.end,up+q.end));
        reject(replace(text,up,replace(up,"map_size=200000","map_size=1000")));
        reject(replace(text,up,replace(up,"map_offset=0","map_offset=1000")));
    }
    std::cout<<"CPUBAR_4K_COMPAT_PASS cases="<<count<<" hardware_access=0 synthetic_pages=1\n";
}
