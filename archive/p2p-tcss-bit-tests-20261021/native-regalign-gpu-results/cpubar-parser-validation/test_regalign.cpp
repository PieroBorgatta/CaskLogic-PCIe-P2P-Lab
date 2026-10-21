#include "ARCHIVE_ROOT/p2p-tcss-bit-tests-20261021/native-cpubar-probe/cpubar_trace.h"
#include <cassert>
#include <iostream>
static std::string read_file(const std::string&p){std::ifstream f(p);assert(f);std::ostringstream s;s<<f.rdbuf();return s.str();}
static std::string replace(std::string s,const std::string&a,const std::string&b){auto p=s.find(a);assert(p!=std::string::npos);s.replace(p,a.size(),b);return s;}
static std::string line(const std::string&s,const std::string&needle){auto p=s.find(needle);assert(p!=std::string::npos);auto b=s.rfind('\n',p);auto e=s.find('\n',p);return s.substr(b==std::string::npos?0:b+1,e-(b==std::string::npos?0:b+1))+"\n";}
int main(int argc,char**argv){
 assert(argc==2);unsigned tests=0;cpubar::Query q;
 q.begin="CaskLogicCPUBAR fixture=1 phase=begin";q.end="CaskLogicCPUBAR fixture=1 phase=end";q.size=0x200000;
 const std::string ada="GPU-00000000-0000-0000-0000-000000000001",a2000="GPU-00000000-0000-0000-0000-000000000002";
 for(unsigned i=1;i<=4;++i){
  q.va=0x787489200000ULL+0x200000ULL*i;bool owner_ada=i==1||i==4;
  q.owner_bdf=owner_ada?"0000:01:00.0":"0000:06:00.0";q.requester_bdf=owner_ada?"0000:06:00.0":"0000:01:00.0";
  q.owner_uuid=owner_ada?ada:a2000;q.requester_uuid=owner_ada?a2000:ada;
  std::string original=read_file(std::string(argv[1])+"/live-window"+std::to_string(i)+".log");cpubar::Window w;std::string e;
  if(!cpubar::resolve(original,q,w,e)){std::cerr<<"live fixture "<<i<<" rejected: "<<e<<"\n";return 1;}++tests;
  assert(w.id==i);assert(w.offset==(i==1?0x400000:i==2?0x400000:i==3?0x600000:0x600000));
  auto bad=[&](const std::string&s){cpubar::Window x;std::string err;bool accepted=cpubar::resolve(s,q,x,err);if(accepted){std::cerr<<"BAD FIXTURE ACCEPTED i="<<i<<" tests="<<tests<<"\n";exit(2);}assert(!err.empty());++tests;};
  bad(replace(original,q.begin,"old_marker"));bad(replace(original,q.end,"old_marker"));bad(q.begin+"\n"+original);
  bad(replace(original,"P2PTRC WINDOW_CREATE","P2PTRC MISSING_WINDOW"));bad(replace(original,"P2PTRC RM_PTE","P2PTRC MISSING_PTE"));
  bad(replace(original,q.end,line(original,"P2PTRC WINDOW_CREATE")+q.end));
  bad(replace(original,"ranges=1","ranges=2"));bad(replace(original,"ranges=1","ranges=1 ranges=1"));
  bad(replace(original,"readonly=0","readonly=1"));bad(replace(original,"valid=1","valid=0"));bad(replace(original,"fmt=2","fmt=1"));
  bad(replace(original,"bar_index=1","bar_index=0"));bad(replace(original,"offset=0 size=200000 dynamic=1","offset=4 size=200000 dynamic=1"));
  bad(replace(original,"dynamic=1","dynamic=0"));bad(replace(original,"iommu_resource=0 status=0","iommu_resource=0 status=1"));
  bad(original+"P2PTRC WINDOW_DESTROY_BEGIN id="+std::to_string(i)+" mem=1\n");
  bad(original+line(original,"P2PTRC WINDOW_CREATE"));
  std::string request=line(original,"P2PTRC RM_REQUEST");auto d=request.find("desc=");assert(d!=std::string::npos);auto de=request.find(' ',d);bad(replace(original,request,replace(request,request.substr(d,de-d),"desc=(ptrval)")));
  std::string up=line(original,"P2PTRC UVM_PTE gpu=ID "+std::string(owner_ada?"9":"1"));auto p=up.find("raw0=");auto pe=up.find(' ',p);bad(replace(original,up,replace(up,up.substr(p,pe-p),"raw0=0000000000000001")));
  bad(replace(original,"window_phys=", "bad_window_phys="));bad(replace(original,"bar1_size=", "bad_bar1_size="));
  bad(replace(original,"resource_end=", "bad_resource_end="));bad(replace(original,"addr_shift=12","addr_shift=13"));
  for(size_t cut=0;cut<original.find(q.end)+q.end.size();cut+=37)bad(original.substr(0,cut));
 }
 cpubar::U n=0;for(const auto&s:{"-1","+1","0x","fffffffffffffffff","12tail"," 12","1\n"}){assert(!cpubar::number(s,n));++tests;}
 assert(cpubar::number("FFFFFFFFFFFFFFFF",n)&&n==UINT64_MAX);++tests;
 assert(!cpubar::bdf_ok("../../dev/mem"));++tests;
 std::cout<<"CPUBAR_PARSER_TESTS_PASS cases="<<tests<<" hardware_access=0 real_fragments=4\n";
}
