#include "cask_phys_ce_ioctl.h"
#include <stddef.h>
#include <stdio.h>
#define ASSERT_OFFSET(field, expected) _Static_assert(offsetof(UVM_TEST_CASK_PHYSICAL_CE_PARAMS, field)==expected, #field)
ASSERT_OFFSET(abi_version,0);ASSERT_OFFSET(operation,4);ASSERT_OFFSET(request_id,8);
ASSERT_OFFSET(source_uuid,16);ASSERT_OFFSET(destination_uuid,32);
ASSERT_OFFSET(source_va,48);ASSERT_OFFSET(destination_va,56);
ASSERT_OFFSET(bytes,64);ASSERT_OFFSET(reserved,68);
ASSERT_OFFSET(source_physical,72);ASSERT_OFFSET(destination_physical,80);
ASSERT_OFFSET(source_allocation_offset,88);ASSERT_OFFSET(destination_allocation_offset,96);
ASSERT_OFFSET(source_rm_handle,104);ASSERT_OFFSET(destination_rm_handle,108);
ASSERT_OFFSET(ce_class,112);ASSERT_OFFSET(launch_dma,116);
ASSERT_OFFSET(source_phys_mode,120);ASSERT_OFFSET(destination_phys_mode,124);
ASSERT_OFFSET(result_flags,128);ASSERT_OFFSET(rmStatus,132);ASSERT_OFFSET(reserved_out,136);
_Static_assert(_Alignof(UVM_TEST_CASK_PHYSICAL_CE_PARAMS)==8,"alignment");
_Static_assert(CASK_PHYS_CE_IOCTL==315,"command");
_Static_assert(CASK_PHYS_CE_SUCCESS_FLAGS==(CASK_PHYS_CE_VALIDATED|CASK_PHYS_CE_SUBMITTED|CASK_PHYS_CE_COMPLETED|CASK_PHYS_CE_P2P_CHANNEL|CASK_PHYS_CE_PRIVILEGED|CASK_PHYS_CE_NO_VIRTUAL_FALLBACK),"success flags");
int main(void) { puts("ABI v1: size144 align8, all23 offsets PASS, ioctl315, flags0x77");return 0; }
