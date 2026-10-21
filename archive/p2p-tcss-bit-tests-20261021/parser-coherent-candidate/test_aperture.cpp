#ifdef USE_BASELINE
#include "../native-cpubar-postwrite-probe/cpubar_trace.h"
#else
#include "../native-coherent-postwrite-probe/cpubar_trace.h"
#endif
#include <cassert>
#include <iostream>
#include <iomanip>
static std::string file(const std::string&p){std::ifstream f(p);assert(f);std::ostringstream s;s<<f.rdbuf();return s.str();}
static std::string replace_all(std::string s,const std::string&a,const std::string&b,unsigned expected){size_t pos=0;unsigned n=0;while((pos=s.find(a,pos))!=std::string::npos){s.replace(pos,a.size(),b);pos+=b.size();++n;}assert(n==expected);return s;}
static std::string rawhex(uint64_t n){std::ostringstream s;s<<std::hex<<std::setw(16)<<std::setfill('0')<<n;return s.str();}
int main(int argc,char**argv){
 assert(argc==2);unsigned cases=0;
 const std::string ada="GPU-00000000-0000-0000-0000-000000000001",a2000="GPU-00000000-0000-0000-0000-000000000002";
 for(unsigned i=1;i<=4;++i){
  cpubar::Query q;q.begin="CaskLogicCPUBAR fixture=1 phase=begin";q.end="CaskLogicCPUBAR fixture=1 phase=end";q.size=0x200000;q.va=0x7e36bf200000ULL+0x200000ULL*i;
  bool owner_ada=i==1||i==4;q.owner_bdf=owner_ada?"0000:01:00.0":"0000:06:00.0";q.requester_bdf=owner_ada?"0000:06:00.0":"0000:01:00.0";
  q.owner_uuid=owner_ada?ada:a2000;q.requester_uuid=owner_ada?a2000:ada;
  const std::string original=file(std::string(argv[1])+"/live-window"+std::to_string(i)+".log");
  auto at=original.find("P2PTRC RM_PTE ");assert(at!=std::string::npos);auto ra=original.find("raw0=",at);assert(ra!=std::string::npos);
  const std::string oldraw=original.substr(ra+5,16);uint64_t raw=std::stoull(oldraw,nullptr,16);assert(((raw>>1)&3)==3);
  auto variant=[&](unsigned en,unsigned hw){
   std::string s=replace_all(original,"aperture=3 ","aperture="+std::to_string(en)+" ",1);
   return replace_all(s,"raw0="+oldraw,"raw0="+rawhex((raw&~uint64_t(6))|(uint64_t(hw)<<1)),2);
  };
  auto check=[&](const std::string&s,bool expected){cpubar::Window w;std::string err;bool actual=cpubar::resolve(s,q,w,err);if(actual!=expected){std::cerr<<"case "<<cases<<" fixture "<<i<<" expected "<<expected<<" actual "<<actual<<" err "<<err<<"\n";exit(2);}assert(actual||!err.empty());if(actual)assert(w.id==i);++cases;};
  check(original,true);
#ifdef USE_BASELINE
  check(variant(4,2),false); // Reproduce the old coherent-only false SKIP.
#else
  check(variant(4,2),true);
  for(unsigned en:{0u,1u,2u,5u,6u})for(unsigned hw:{0u,1u,2u,3u})check(variant(en,hw),false);
  check(variant(4,3),false);check(variant(3,2),false);check(variant(4,0),false);check(variant(4,1),false);
  check(replace_all(variant(4,2),"readonly=0 ","readonly=1 ",1),false);
  check(replace_all(variant(4,2),q.begin,"old_marker",1),false);
  check(variant(4,2)+"P2PTRC WINDOW_DESTROY_BEGIN id="+std::to_string(i)+" mem=1\n",false);
  // Keep coherent RM raw, but revert only matching requester UVM raw: reject.
  std::string wrong=variant(4,2),needle="raw0="+rawhex((raw&~uint64_t(6))|4);auto a=wrong.find(needle),b=wrong.find(needle,a+1);assert(b!=std::string::npos);wrong.replace(b,needle.size(),"raw0="+oldraw);check(wrong,false);
#endif
 }
 std::cout<<"PASS aperture fixtures="<<cases<<" hardware_access=0\n";
}
