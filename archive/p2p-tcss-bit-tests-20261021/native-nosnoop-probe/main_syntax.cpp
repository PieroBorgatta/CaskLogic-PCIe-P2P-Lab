#include "syntax_stubs.inc"
// Controlled comparison: all four handles and mappings persist across five phases.
static volatile sig_atomic_t attrs_stop=0;
static void attrs_signal(int s){attrs_stop=s;}
static void attrs_assert(pciattrs::Controller&ctl,const char*label,unsigned mode){
 std::string error;if(attrs_stop)throw std::runtime_error("termination_requested");
 if(!ctl.check(label,mode,error))throw std::runtime_error("attribute_guard_"+error);
}
static void sync_both(){for(int i=0;i<2;++i){CK(cudaSetDevice(i));CK(cudaDeviceSynchronize());}}
static void restore_attrs(pciattrs::Controller&ctl){
 sync_both();std::string error;if(!ctl.restore(error))throw std::runtime_error("attribute_restore_"+error);
}
static int run_comparison(pciattrs::Controller&ctl){
 int count=0;CK(cudaGetDeviceCount(&count));printf("GPU count %d\n",count);
 if(count!=2)throw std::runtime_error("gpu_count_not_two");
 pcie_snapshot("program_baseline");
 std::string bdfs[2],uuids[2];
 for(int i=0;i<2;++i){
  CK(cudaSetDevice(i));CK(cudaFree(nullptr));CK(cudaDeviceSynchronize());
  bdfs[i]=cuda_bdf(i);uuids[i]=cuda_uuid(i);
  int can=0;CK(cudaDeviceCanAccessPeer(&can,i,1-i));
  printf("PEER %d -> %d can %d\n",i,1-i,can);if(!can)throw std::runtime_error("peer_access_unavailable");
 }
 unsigned*source[2]={};unsigned*destination[2]={};
 // Allocate in the same order as the original baseline; move all mapping work
 // before any owner pattern or peer operation and retain every allocation.
 for(int owner=0;owner<2;++owner){int executor=1-owner;
  phase("mapping_begin",owner,executor);CK(cudaSetDevice(owner));
  alloc_peer(&source[owner],4,owner);pending_frees.push_back({source[owner],owner});
  CK(cudaSetDevice(executor));alloc_peer(&destination[owner],4,executor);pending_frees.push_back({destination[owner],executor});
  printf("PROBE_PTR s=%d d=%d src=%p dst=%p bytes=4\n",owner,executor,(void*)source[owner],(void*)destination[owner]);
  phase("mapping_done",owner,executor);
 }
 sync_both();std::string error;if(!ctl.capture(bdfs,uuids,error))throw std::runtime_error("attribute_capture_"+error);
 const char*names[5]={"baseline_initial","ada_off","baseline_restored","both_off","baseline_final"};
 const unsigned modes[5]={0,1,0,2,0};int total_failures=0;
 for(unsigned trial=0;trial<5;++trial){unsigned mode=modes[trial];
  if(attrs_stop)throw std::runtime_error("termination_requested");
  // Restore between modified phases before applying the next mode.
  if(trial==2||trial==4)restore_attrs(ctl);
  sync_both();error.clear();if(!ctl.set_mode(mode,error))throw std::runtime_error("attribute_mode_"+error);
  printf("ATTR_PHASE_BEGIN index=%u name=%s mode=%u allocations_unchanged=1\n",trial,names[trial],mode);phase(names[trial]);
  int failures=0;unsigned post_pass_before=cpu_post_pass,post_fail_before=cpu_post_fail,post_skip_before=cpu_post_skip;
  char label[128];
  for(int owner=0;owner<2;++owner){int executor=1-owner;unsigned*src=source[owner];unsigned*dst=destination[owner];
   auto boundary=[&](const char*operation){snprintf(label,sizeof(label),"phase%u_owner%d_%s",trial,owner,operation);attrs_assert(ctl,label,mode);};
   const unsigned initial=12345u;unsigned observed=0;
   boundary("owner_init_before");CK(cudaSetDevice(owner));CK(cudaMemcpy(src,&initial,4,cudaMemcpyHostToDevice));CK(cudaDeviceSynchronize());verify_owner_word("initialized",owner,src,initial);boundary("owner_init_after");
   // Existing read-only BAR control; it restores 12345 with owner sync before P2P.
   boundary("cpubar_check_before");cpu_bar_check(src,owner);boundary("cpubar_check_after");
   CK(cudaSetDevice(executor));CK(cudaMemset(dst,0,4));CK(cudaDeviceSynchronize());verify_owner_word("read_destination_zeroed",executor,dst,0);
   boundary("read_before");phase("read_begin",owner,executor);pcie_snapshot(label);
   peer_read(src,dst,1);CK(cudaGetLastError());CK(cudaDeviceSynchronize());
   boundary("read_after");pcie_snapshot(label);CK(cudaMemcpy(&observed,dst,4,cudaMemcpyDeviceToHost));
   bool good=observed==(initial^0x12345678u);if(!good)++failures;
   printf("REMOTE_READ phase=%u name=%s s=%d d=%d bytes=4 observed=%08x expected=%08x valid=%d\n",trial,names[trial],owner,executor,observed,initial^0x12345678u,good);phase("read_done",owner,executor);boundary("read_compare_after");
   boundary("owner_zero_before");CK(cudaSetDevice(owner));CK(cudaMemset(src,0,4));CK(cudaDeviceSynchronize());verify_owner_word("zeroed",owner,src,0);boundary("owner_zero_after");
   CK(cudaSetDevice(executor));boundary("write_before");phase("write_begin",executor,owner);pcie_snapshot(label);
   peer_write(src,1,98765u);CK(cudaGetLastError());CK(cudaDeviceSynchronize());
   boundary("write_after");pcie_snapshot(label);
   // No owner D2H or reinitialization before the same read-only CPU diagnostic.
   cpu_bar_postwrite(src,owner,executor,98765u^0xa5a5a5a5u);boundary("postwrite_cpu_after");
   CK(cudaSetDevice(owner));CK(cudaMemcpy(&observed,src,4,cudaMemcpyDeviceToHost));
   good=observed==(98765u^0xa5a5a5a5u);if(!good)++failures;
   printf("REMOTE_WRITE phase=%u name=%s s=%d d=%d bytes=4 observed=%08x expected=%08x valid=%d\n",trial,names[trial],executor,owner,observed,98765u^0xa5a5a5a5u,good);phase("write_done",executor,owner);boundary("write_compare_after");
  }
  sync_both();snprintf(label,sizeof(label),"phase%u_complete",trial);attrs_assert(ctl,label,mode);
  printf("ATTR_PHASE_RESULT index=%u name=%s mode=%u failures=%d comparisons=4 cpu_post_pass=%u cpu_post_fail=%u cpu_post_skip=%u valid_protocol=1\n",trial,names[trial],mode,failures,cpu_post_pass-post_pass_before,cpu_post_fail-post_fail_before,cpu_post_skip-post_skip_before);
  total_failures+=failures;
 }
 restore_attrs(ctl);attrs_assert(ctl,"final_restore_before_cleanup",0);
 printf("CPUBAR_POSTWRITE_SUMMARY pass=%u fail=%u skip=%u\n",cpu_post_pass,cpu_post_fail,cpu_post_skip);
 printf("CPUBAR_SUMMARY pass=%u fail=%u skip=%u\n",cpu_checks_pass,cpu_checks_fail,cpu_checks_skip);
 printf("TOTAL_FAILURES %d phases=5 comparisons=20\n",total_failures);phase("data_done");
 return total_failures?5:0;
}
int main(){
 setbuf(stdout,nullptr);signal(SIGTERM,attrs_signal);signal(SIGINT,attrs_signal);
 kmsg_fd=open("/dev/kmsg",O_WRONLY|O_CLOEXEC);if(kmsg_fd<0)printf("KMSG_UNAVAILABLE errno=%d\n",errno);
 pciattrs::Controller ctl;int result=12;bool completed=false,restored=true;
 try{phase("program_start");result=run_comparison(ctl);completed=true;}
 catch(const std::exception&e){printf("ATTR_TRIAL_ABORT reason=%s signal=%d\n",e.what(),int(attrs_stop));}
 // Error path is fail-closed: no further comparisons, and attempt restoration
 // even if CUDA synchronization failed. The register helper independently
 // refuses a live identity change or an explicit pending nonposted request.
 if(ctl.captured()){
  try{sync_both();}catch(const std::exception&e){printf("ATTR_ABORT_SYNC reason=%s\n",e.what());completed=false;result=12;}
  std::string error;restored=ctl.restore(error);
  printf("ATTR_FINAL_RESTORE valid=%d reason=%s\n",restored,error.empty()?"none":error.c_str());
  if(!restored){result=13;completed=false;}
 }
 // All frees remain after all comparisons and after verified register restore.
 if(restored){try{
  phase("cleanup_begin");for(auto item:pending_frees){CK(cudaSetDevice(item.second));phase("allocation_free_begin",item.second,-1);free_peer(item.first);phase("allocation_free_done",item.second,-1);}
  pending_frees.clear();phase("cleanup_done");
 }catch(const std::exception&e){printf("ATTR_CLEANUP_ERROR reason=%s\n",e.what());result=14;completed=false;}}
 printf("ATTR_PROGRAM_END protocol_complete=%d restored=%d rc=%d\n",completed,restored,result);
 try{phase("context_exit_begin");}catch(...){}
 if(kmsg_fd>=0)close(kmsg_fd);return result;
}
