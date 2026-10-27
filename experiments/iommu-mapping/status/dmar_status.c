// SPDX-License-Identifier: GPL-2.0-only
// Read-only status probe for the sole DRHD declared on the AHWSA1.26 lab host.
#include <linux/module.h>
#include <linux/acpi.h>
#include <linux/dmi.h>
#include <linux/io.h>
#include <linux/delay.h>
#include <asm/cpufeature.h>
#include "dmar_decode.h"
static int __init cask_dmar_init(void)
{
 struct acpi_table_header *table;struct cask_dmar_table decoded;
 void __iomem *regs;acpi_status status;u32 ver;u64 cap,ecap;unsigned int i;int ret;
 if(!dmi_match(DMI_BOARD_NAME,"AHWSA") || !dmi_match(DMI_BIOS_VERSION,"1.26") || boot_cpu_has(X86_FEATURE_HYPERVISOR))return -ENODEV;
 status=acpi_get_table(ACPI_SIG_DMAR,0,&table);if(ACPI_FAILURE(status))return -ENODEV;
 ret=cask_decode_dmar((const u8*)table,table->length,&decoded);acpi_put_table(table);if(ret)return ret;
 regs=ioremap(decoded.base,0x80);if(!regs)return -ENOMEM;
 ver=readl(regs);cap=readq(regs+0x8);ecap=readq(regs+0x10);
 if(ver!=0x50 || cap!=0x00d2008c40660462ULL || ecap!=0x0000000000f050daULL){iounmap(regs);return -ENODEV;}
 pr_info("CASKDMAR_BEGIN version=1 units=1 table_bytes=80 table_flags=%02x register_writes=0\n",decoded.flags);
 pr_info("CASKDMAR_CAP base=%llx ver=%08x cap=%016llx ecap=%016llx\n",decoded.base,ver,cap,ecap);
 for(i=0;i<2;++i){
  u32 gsts=readl(regs+0x1c),pmen=readl(regs+0x64);
  if(gsts==~0U || pmen==~0U){iounmap(regs);return -EIO;}
  pr_info("CASKDMAR_SAMPLE index=%u gsts=%08x pmen=%08x translation_enabled=%u interrupt_remapping_enabled=%u protected_region_enabled=%u protected_region_status=%u\n",i,gsts,pmen,!!(gsts&BIT(31)),!!(gsts&BIT(25)),!!(pmen&BIT(31)),!!(pmen&BIT(0)));
  if(i==0)usleep_range(1000,2000);
 }
 iounmap(regs);pr_info("CASKDMAR_END protocol_complete=1 register_writes=0\n");return 0;
}
static void __exit cask_dmar_exit(void){pr_info("CASKDMAR_UNLOADED register_writes=0\n");}
module_init(cask_dmar_init);module_exit(cask_dmar_exit);
MODULE_LICENSE("GPL");MODULE_DESCRIPTION("CaskLogic read-only AHWSA DRHD status probe");
