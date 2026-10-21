// Appended diagnostic only: all P2P comparisons have already finished.
static std::vector<std::pair<unsigned*,int>> cpu_rw_targets;
static unsigned cpu_rw_pass=0,cpu_rw_fail=0,cpu_rw_skip=0;
static bool cpu_rw_halt=false;
static bool cpu_rw_cuda(cudaError_t status,const char *stage,std::string&error) {
    if(status==cudaSuccess)return true;
    error=std::string(stage)+"_"+std::to_string(static_cast<int>(status));return false;
}
static void cpu_bar_rw_check(unsigned *ptr,int owner) {
    std::string error;auto it=cpu_meta.find(ptr);
    auto skip=[&](const std::string&reason){
        printf("CPUBAR_RW_RESULT owner=%d gpu_va=%p status=SKIP writes_attempted=0 reason=%s\n",owner,(void*)ptr,reason.c_str());++cpu_rw_skip;
    };
    if(cpu_rw_halt){skip("previous_rw_control_halted");return;}
    if(it==cpu_meta.end()||!it->second.ready){skip(it==cpu_meta.end()?"metadata_missing":it->second.reason);return;}
    const CpuBarMeta&m=it->second;
    cpubar::Window w;cpubar::WritableWord word;
    if(!current_window(m,w,error)||!word.open(m.owner,w,error)){skip(error);return;}
    auto unchanged=[&](std::string&why){
        cpubar::Window now;cpubar::Identity id;
        if(!current_window(m,now,why)||!same_window(w,now)||
           !cpubar::identity(m.owner.bdf,m.owner.uuid,id,why)||!cpubar::same_identity(id,m.owner)) {
            if(why.empty())why="rw_mapping_or_identity_changed";return false;
        }
        return true;
    };
    if(!unchanged(error)||!cpu_rw_cuda(cudaSetDevice(owner),"set_owner",error)||
       !cpu_rw_cuda(cudaDeviceSynchronize(),"owner_sync",error)){skip(error);return;}
    uint32_t previous=0,previous_owner=0;
    if(!word.read(previous,error)||
       !cpu_rw_cuda(cudaMemcpy(&previous_owner,ptr,4,cudaMemcpyDeviceToHost),"save_owner",error)) {skip(error);return;}
    printf("CPUBAR_RW_SAVED owner=%d gpu_va=%p window_id=%llu physical=%llx cpu=%08x owner_d2h=%08x valid=%d\n",
        owner,(void*)ptr,(unsigned long long)w.id,(unsigned long long)w.physical,previous,previous_owner,previous==previous_owner);
    // A single restore value must describe both views before any CPU store.
    if(previous!=previous_owner){skip("previous_cpu_owner_disagree");return;}
    const uint32_t patterns[2]={0x37b95a61u^(static_cast<uint32_t>(owner)*0x01010101u),0xc846a59eu^(static_cast<uint32_t>(owner)*0x01010101u)};
    const uint32_t peer_expected=98765u^0xa5a5a5a5u;
    if(patterns[0]==previous||patterns[1]==previous||patterns[0]==peer_expected||patterns[1]==peer_expected){skip("pattern_collision");return;}
    printf("CPUBAR_RW_MATCH owner=%d bdf=%s gpu_va=%p window_id=%llu bar=%llx offset=%llx physical=%llx bytes=4 mapping=O_RDWR_PROT_READ_WRITE no_pci_configuration_writes=1\n",
        owner,m.owner.bdf.c_str(),(void*)ptr,(unsigned long long)w.id,(unsigned long long)w.bar,(unsigned long long)w.offset,(unsigned long long)w.physical);
    bool good=true,complete=true,attempted=false,access_fault=false,identity_lost=false;
    unsigned completed=0;phase("cpu_rw_begin",owner,-1);pcie_snapshot(owner==0?"cpu_rw_ada_before":"cpu_rw_a2000_before");
    for(unsigned i=0;i<2;++i) {
        error.clear();
        if(!unchanged(error)){complete=false;identity_lost=true;break;}
        // Mark the attempt before the guarded store: a fault does not prove no write happened.
        attempted=true;uint32_t cpu=0,gpu=0;
        bool store_ok=word.write(patterns[i],error);
        bool cpu_ok=store_ok&&word.read(cpu,error);
        if(!store_ok||!cpu_ok){complete=false;access_fault=true;break;}
        bool owner_ok=cpu_rw_cuda(cudaMemcpy(&gpu,ptr,4,cudaMemcpyDeviceToHost),"pattern_owner_d2h",error);
        if(!owner_ok){complete=false;break;}
        bool valid=cpu==patterns[i]&&gpu==patterns[i];good=good&&valid;++completed;
        printf("CPUBAR_RW_PATTERN owner=%d pattern=%u expected=%08x cpu=%08x owner_d2h=%08x cpu_valid=%d owner_valid=%d valid=%d\n",
            owner,i+1,patterns[i],cpu,gpu,cpu==patterns[i],gpu==patterns[i],valid);
    }
    const std::string diagnostic_error=error;
    bool restore_attempted=false,restore_store_ok=false,restore_cpu_ok=false,restore_owner_ok=false,restored=false;
    uint32_t restore_cpu=0,restore_owner=0;std::string restore_error;
    if(attempted) {
        // Always try restoration after any attempted store, including a signal,
        // but NEVER write again when the allocation/window/identity is no longer valid.
        if(!identity_lost&&unchanged(restore_error)) {
            restore_attempted=true;
            restore_store_ok=word.write(previous,restore_error);
            restore_cpu_ok=restore_store_ok&&word.read(restore_cpu,restore_error);
            restore_owner_ok=cpu_rw_cuda(cudaMemcpy(&restore_owner,ptr,4,cudaMemcpyDeviceToHost),"restore_owner_d2h",restore_error);
            restored=restore_store_ok&&restore_cpu_ok&&restore_owner_ok&&restore_cpu==previous&&restore_owner==previous;
        } else {identity_lost=true;if(restore_error.empty())restore_error="identity_or_chain_lost_no_further_store";}
    } else restored=true; // No store attempt, so no restoration was necessary.
    printf("CPUBAR_RW_RESTORE owner=%d writes_attempted=%d attempted=%d store_ok=%d cpu_read_ok=%d owner_read_ok=%d previous=%08x cpu=%08x owner_d2h=%08x restored=%d reason=%s\n",
        owner,attempted,restore_attempted,restore_store_ok,restore_cpu_ok,restore_owner_ok,previous,restore_cpu,restore_owner,restored,restore_error.empty()?"none":restore_error.c_str());
    word.close();pcie_snapshot(owner==0?"cpu_rw_ada_after":"cpu_rw_a2000_after");phase("cpu_rw_done",owner,-1);
    if(identity_lost||access_fault||!restored)cpu_rw_halt=true;
    if(!attempted){++cpu_rw_skip;printf("CPUBAR_RW_RESULT owner=%d gpu_va=%p status=SKIP writes_attempted=0 reason=%s\n",owner,(void*)ptr,diagnostic_error.c_str());return;}
    bool pass=complete&&good&&completed==2&&restored;
    if(pass)++cpu_rw_pass;else ++cpu_rw_fail;
    printf("CPUBAR_RW_RESULT owner=%d gpu_va=%p status=%s writes_attempted=1 patterns_completed=%u restored=%d access_fault=%d identity_lost=%d reason=%s p2p_result_unchanged=1\n",
        owner,(void*)ptr,pass?"PASS":"FAIL",completed,restored,access_fault,identity_lost,
        !diagnostic_error.empty()?diagnostic_error.c_str():!good?"pattern_mismatch":!restored?"restore_not_verified":"none");
}
