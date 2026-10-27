#include "phys_pull_client.h"
#include <cassert>
#include <functional>
#include <sys/wait.h>
#include <poll.h>
using P=UVM_TEST_CASK_PHYSICAL_CE_PARAMS;
static P input(unsigned transfer=0,unsigned mode=2){const uint8_t a[16]={1},b[16]={2};return phys_pull::request(1,123,a,b,transfer?b:a,0x1000000,0x2000000,transfer,mode);}
static P output(P p){p.source_physical=0x4000400000;p.destination_physical=0x4600400000;p.source_rm_handle=123;p.destination_rm_handle=456;p.ce_class=0xc7b5;p.launch_dma=0x04003186;p.source_phys_mode=p.transfer?p.remote_phys_mode:0;p.destination_phys_mode=p.transfer?0:p.remote_phys_mode;p.source_is_peer=p.transfer?1:0;p.destination_is_peer=p.transfer?0:1;p.stock_rejects_peer_source=p.source_is_peer;p.result_flags=CASK_PHYS_CE_SUCCESS_FLAGS;return p;}
int main(){
 for(unsigned transfer:{0u,1u})for(unsigned mode:{1u,2u}){
  auto in=input(transfer,mode),out=output(in);assert(phys_pull::valid_execution(in,out,0));assert(!phys_pull::valid_execution(in,out,-1));
  auto mutate=[&](std::function<void(P&)> f){auto bad=out;f(bad);assert(!phys_pull::valid_execution(in,bad,0));};
  mutate([](P&p){p.request_id++;});mutate([](P&p){p.executor_uuid[0]^=4;});mutate([](P&p){p.source_va+=4;});
  mutate([](P&p){p.ce_class=0xc6b5;});mutate([](P&p){p.launch_dma^=1;});mutate([](P&p){p.source_physical++;});
  mutate([](P&p){p.destination_physical=0;});mutate([](P&p){p.source_allocation_offset=4;});mutate([](P&p){p.destination_rm_handle=0;});
  mutate([](P&p){p.source_phys_mode^=1;});mutate([](P&p){p.destination_phys_mode^=1;});
  mutate([](P&p){p.source_is_peer=2;});mutate([](P&p){p.stock_rejects_peer_source^=1;});
  mutate([&](P&p){if(transfer)p.destination_is_peer=1;else p.source_is_peer=1;});
  mutate([](P&p){p.result_flags|=CASK_PHYS_CE_RETAINED;});mutate([](P&p){p.result_flags&=~CASK_PHYS_CE_COMPLETED;});mutate([](P&p){p.rmStatus=1;});
  // Dynamic BAR1 may not be classified peer; zero classifier does not prove support.
  out.source_is_peer=out.destination_is_peer=out.stock_rejects_peer_source=0;assert(phys_pull::valid_execution(in,out,0));
 }
 auto in=input();in.operation=0;auto out=in;out.ce_class=0xc7b5;out.source_rm_handle=1;out.destination_rm_handle=2;out.result_flags=1;
 assert(phys_pull::valid_validation(in,out,0));out.source_physical=4;assert(!phys_pull::valid_validation(in,out,0));out.source_physical=0;out.source_is_peer=1;assert(!phys_pull::valid_validation(in,out,0));
 for(unsigned mode:{0u,3u,4u}){bool rejected=false;try{input(0,mode);}catch(const std::runtime_error&){rejected=true;}assert(rejected);}
 {auto p=input();p.executor_uuid[0]=7;auto q=output(p);assert(!phys_pull::valid_execution(p,q,0));}
 {auto p=input();p.transfer=7;auto q=output(p);assert(!phys_pull::valid_execution(p,q,0));}
 {auto p=input();p.bytes=8;auto q=output(p);assert(!phys_pull::valid_execution(p,q,0));}
 P p{};p.result_flags=CASK_PHYS_CE_SUBMITTED;assert(phys_pull::retained_or_inflight(p));p.result_flags|=CASK_PHYS_CE_COMPLETED;assert(!phys_pull::retained_or_inflight(p));p.result_flags|=CASK_PHYS_CE_RETAINED;assert(phys_pull::retained_or_inflight(p));
 // Test the actual safety park in a disposable CPU-only child; no CUDA/device IO.
 int fds[2];assert(pipe(fds)==0);pid_t child=fork();assert(child>=0);
 if(child==0){close(fds[0]);assert(dup2(fds[1],STDOUT_FILENO)>=0);close(fds[1]);phys_pull::abort_inflight(p);}
 close(fds[1]);pollfd ready{fds[0],POLLIN,0};assert(poll(&ready,1,2000)==1);char line[512]{};assert(read(fds[0],line,sizeof(line)-1)>0);assert(std::strstr(line,"no_more_gpu_work=1"));
 assert(kill(child,SIGTERM)==0);usleep(20000);int status=0;assert(waitpid(child,&status,WNOHANG)==0);assert(kill(child,SIGKILL)==0);assert(waitpid(child,&status,0)==child);assert(WIFSIGNALED(status)&&WTERMSIG(status)==SIGKILL);close(fds[0]);
 std::puts("PHYSICAL_PULL_CLIENT_FIXTURES PASS cpu_only=1 ambiguous_completion_parks=1 sigterm_does_not_unwind=1");
}
