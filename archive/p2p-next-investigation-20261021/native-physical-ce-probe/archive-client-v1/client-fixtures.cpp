#include "phys_ce_client.h"
#include <cassert>
#include <sys/wait.h>
#include <time.h>
#include <functional>
static unsigned checks=0;
static void check(bool value){++checks;if(!value){std::fprintf(stderr,"fixture failed at check %u\n",checks);std::abort();}}
int main(){
 uint8_t a[16]{1},b[16]{2};
 auto in=phys_ce::request(CASK_PHYS_CE_EXECUTE,123,a,b,0x100000000ULL,0x200000000ULL);
 check(sizeof(in)==144);check(offsetof(UVM_TEST_CASK_PHYSICAL_CE_PARAMS,source_physical)==72);
 check(in.bytes==4&&in.reserved==0&&in.reserved_out==0&&in.operation==1&&in.abi_version==1);
 auto out=in;out.source_physical=0x200000;out.destination_physical=0x4000400000ULL;
 out.source_rm_handle=1;out.destination_rm_handle=2;out.ce_class=0xc6b5;out.launch_dma=0x3000;out.source_phys_mode=0;out.destination_phys_mode=2;out.result_flags=0x77;
 check(phys_ce::valid_execution(in,out,0));out.ce_class=0xc7b5;check(phys_ce::valid_execution(in,out,0));
 const auto good=out;
 auto reject=[&](const std::function<void(UVM_TEST_CASK_PHYSICAL_CE_PARAMS&)>& mutate){auto x=good;mutate(x);check(!phys_ce::valid_execution(in,x,0));};
 reject([](auto&p){p.ce_class=0xc5b5;});reject([](auto&p){p.ce_class=0xc8b5;});reject([](auto&p){p.destination_phys_mode=1;});reject([](auto&p){p.destination_phys_mode=0;});reject([](auto&p){p.source_phys_mode=2;});
 reject([](auto&p){p.launch_dma&=~0x1000;});reject([](auto&p){p.launch_dma&=~0x2000;});reject([](auto&p){p.result_flags|=8;});reject([](auto&p){p.result_flags=1;});
 for(unsigned bit:{1U,2U,4U,0x10U,0x20U,0x40U})reject([&](auto&p){p.result_flags&=~bit;});
 reject([](auto&p){p.result_flags|=0x80;});reject([](auto&p){p.rmStatus=1;});reject([](auto&p){p.reserved_out=1;});
 reject([](auto&p){p.source_rm_handle=0;});reject([](auto&p){p.destination_rm_handle=0;});reject([](auto&p){p.source_physical|=1;});reject([](auto&p){p.destination_physical|=2;});
 reject([](auto&p){p.source_allocation_offset=4;});reject([](auto&p){p.destination_allocation_offset=4;});
 for(unsigned n=0;n<72;++n){auto x=good;reinterpret_cast<unsigned char*>(&x)[n]^=1;check(!phys_ce::valid_execution(in,x,0));}
 check(!phys_ce::valid_execution(in,good,-1));check(!phys_ce::retained_or_inflight(good));
 auto v=phys_ce::request(CASK_PHYS_CE_VALIDATE,9,a,b,0x1000,0x2000);auto vo=v;vo.result_flags=1;
 check(phys_ce::valid_validation(v,vo,0));vo.result_flags=0x77;check(!phys_ce::valid_validation(v,vo,0));vo.result_flags=1;vo.rmStatus=1;check(!phys_ce::valid_validation(v,vo,0));vo.rmStatus=0;vo.reserved_out=1;check(!phys_ce::valid_validation(v,vo,0));vo.reserved_out=0;check(!phys_ce::valid_validation(v,vo,-1));
 for(unsigned flags:{8U,2U,3U,0x73U,0x7fU}){auto x=in;x.result_flags=flags;check(phys_ce::retained_or_inflight(x));}
 // Prove the actual parking routine retains the child process after SIGTERM.
 // No CUDA, device, MMIO, ioctl, or host firmware access is performed.
 int pipefd[2];check(pipe(pipefd)==0);pid_t child=fork();check(child>=0);
 if(child==0){close(pipefd[0]);dup2(pipefd[1],STDOUT_FILENO);close(pipefd[1]);auto x=in;x.result_flags=8;phys_ce::abort_inflight(x);}
 close(pipefd[1]);char line[512]{};ssize_t got=read(pipefd[0],line,sizeof(line)-1);check(got>0);check(std::strstr(line,"parked=1 no_exit=1")!=nullptr);
 check(kill(child,SIGTERM)==0);timespec delay{0,100000000};nanosleep(&delay,nullptr);int status=0;check(waitpid(child,&status,WNOHANG)==0);
 check(kill(child,SIGKILL)==0);check(waitpid(child,&status,0)==child);check(WIFSIGNALED(status)&&WTERMSIG(status)==SIGKILL);close(pipefd[0]);
 std::printf("CLIENT_FIXTURES PASS checks=%u cpu_only=1 device_calls=0\n",checks);return 0;
}
