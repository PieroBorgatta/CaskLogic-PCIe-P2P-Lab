#include "cask_phys_ce_ioctl.h"
#include <assert.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>
static void reset_outputs(UVM_TEST_CASK_PHYSICAL_CE_PARAMS *p) {
    p->source_physical=0;p->destination_physical=0;
    p->source_allocation_offset=0;p->destination_allocation_offset=0;
    p->source_rm_handle=0;p->destination_rm_handle=0;
    p->ce_class=0;p->launch_dma=0;
    p->source_phys_mode=0;p->destination_phys_mode=0;
    p->result_flags=0;p->rmStatus=0;p->reserved_out=0;
}
int main(void) {
 UVM_TEST_CASK_PHYSICAL_CE_PARAMS p; unsigned char before[72];
 memset(&p,0xa5,sizeof(p)); memcpy(before,&p,sizeof(before));reset_outputs(&p);
 assert(sizeof(p)==144 && offsetof(UVM_TEST_CASK_PHYSICAL_CE_PARAMS,source_physical)==72);
 assert(memcmp(before,&p,72)==0);
 for(size_t n=72;n<sizeof(p);++n) assert(((unsigned char *)&p)[n]==0);
 puts("PASS:72 input bytes unchanged;72 output bytes zero;13 explicit assignments");return 0;
}
