// SPDX-License-Identifier: GPL-2.0-only
/* Read-only VT-d snapshot for one known native machine; no control-register write. */
#include <linux/module.h>
#include <linux/acpi.h>
#include <linux/io.h>
#include <linux/pci.h>
#include <linux/slab.h>
#include <linux/string.h>
#include <linux/errno.h>
#include <asm/cpufeature.h>
#include <asm/processor.h>
#define PFX "CaskVTdRO: "
#include "dmar_parse.inc"
#define KNOWN_DRHD 0xfed91000ULL
#define VTD_VER 0x00
#define VTD_CAP 0x08
#define VTD_ECAP 0x10
#define VTD_GSTS 0x1c
#define VTD_RTADDR 0x20
#define VTD_FSTS 0x34
#define VTD_PMEN 0x64
static bool sample_tcss=true;
module_param_named(tcss,sample_tcss,bool,0400);
MODULE_PARM_DESC(tcss,"Read documented Alder Lake TCSS VT-d BARs after exact host bridge/MCHBAR profile check.");
static char result[40]="not_started";
module_param_string(result,result,sizeof(result),0444);

static int snapshot_unit(u64 base, const char *origin)
{
    void __iomem *regs;
    u32 ver,gsts_before,gsts_after,fsts,pmen;
    u64 cap,ecap,rtaddr,phmbase=0,phmlimit=0;
    u32 plmbase=0,plmlimit=0;
    /* Caller validates either ACPI declaration or exact documented TCSS BAR.
     * This machine-specific sampler refuses all other physical apertures. */
    if ((base&0xfffULL) || base<0xfed00000ULL || base>0xfedff000ULL) return -EINVAL;
    regs=ioremap((phys_addr_t)base,4096);
    if (!regs) return -ENOMEM;
    gsts_before=readl(regs+VTD_GSTS);
    ver=readl(regs+VTD_VER);
    cap=readq(regs+VTD_CAP);
    ecap=readq(regs+VTD_ECAP);
    rtaddr=readq(regs+VTD_RTADDR);
    fsts=readl(regs+VTD_FSTS);
    pmen=readl(regs+VTD_PMEN);
    if (cap&BIT_ULL(5)) {plmbase=readl(regs+0x68);plmlimit=readl(regs+0x6c);}
    if (cap&BIT_ULL(6)) {phmbase=readq(regs+0x70);phmlimit=readq(regs+0x78);}
    gsts_after=readl(regs+VTD_GSTS);
    iounmap(regs);
    pr_info(PFX "SNAPSHOT origin=%s base=%016llx VER=%08x CAP=%016llx ECAP=%016llx GSTS_before=%08x GSTS_after=%08x RTADDR=%016llx FSTS=%08x PMEN=%08x stable=%u\n",
            origin,(unsigned long long)base,ver,(unsigned long long)cap,(unsigned long long)ecap,
            gsts_before,gsts_after,(unsigned long long)rtaddr,fsts,pmen,gsts_before==gsts_after);
    pr_info(PFX "PMR origin=%s base=%016llx PLMR_supported=%u PHMR_supported=%u PLMBASE=%08x PLMLIMIT=%08x PHMBASE=%016llx PHMLIMIT=%016llx bounds_are_raw=1\n",
            origin,(unsigned long long)base,!!(cap&BIT_ULL(5)),!!(cap&BIT_ULL(6)),
            plmbase,plmlimit,(unsigned long long)phmbase,(unsigned long long)phmlimit);
    if (!ver || ver==~0U || cap==~0ULL || ecap==~0ULL ||
        gsts_before==~0U || gsts_after==~0U)
        return -EIO;
    if (gsts_before!=gsts_after) return -EAGAIN;
    pr_info(PFX "STATUS base=%016llx TES=%u RTPS=%u QIES=%u IRES=%u IRTPS=%u PMEN_EPM_raw=%u PMEN_PRS_raw=%u PMR_status_valid=%u origin=%s\n",
            (unsigned long long)base,!!(gsts_after&BIT(31)),!!(gsts_after&BIT(30)),
            !!(gsts_after&BIT(26)),!!(gsts_after&BIT(25)),!!(gsts_after&BIT(24)),
            !!(pmen&BIT(31)),!!(pmen&BIT(0)),
            !!(cap&(BIT_ULL(5)|BIT_ULL(6))) && pmen!=~0U,origin);
    return 0;
}

/* Coreboot Alder Lake systemagent.h: TBTxBAR=7888+x*8, EN=bit0,
 * mask=7ffffff000; acpi.c uses these as DRHDs for D7:F0..3.
 * No generic MCHBAR decode: only the observed exact machine profile. */
static int snapshot_tcss(void)
{
    struct pci_dev *host;
    void __iomem *mch;
    u32 id,lo,hi,lo_after,hi_after;
    u64 raw[4],base;
    unsigned int i,enabled=0;
    int ret=0;
    host=pci_get_domain_bus_and_slot(0,0,PCI_DEVFN(0,0));
    if (!host) return -ENODEV;
    if (pci_read_config_dword(host,0,&id)!=PCIBIOS_SUCCESSFUL || id!=0x46418086 ||
        pci_read_config_dword(host,0x48,&lo)!=PCIBIOS_SUCCESSFUL || lo!=0xfedc0001 ||
        pci_read_config_dword(host,0x4c,&hi)!=PCIBIOS_SUCCESSFUL || hi!=0) {
        ret=-ENODEV; goto out;
    }
    mch=ioremap(0xfedc7000,4096);
    if (!mch) {ret=-ENOMEM;goto out;}
    for (i=0;i<4;i++) raw[i]=readq(mch+0x888+i*8);
    iounmap(mch);
    if (pci_read_config_dword(host,0x48,&lo_after)!=PCIBIOS_SUCCESSFUL || lo_after!=lo ||
        pci_read_config_dword(host,0x4c,&hi_after)!=PCIBIOS_SUCCESSFUL || hi_after!=hi) {
        ret=-EAGAIN; goto out;
    }
    for (i=0;i<4;i++) {
        base=raw[i]&0x7ffffff000ULL;
        pr_info(PFX "TCSS_BAR port=%u BDF=0000:00:07.%u MCH_offset=%04x raw=%016llx enabled=%u base=%016llx\n",
                i,i,0x7888+i*8,(unsigned long long)raw[i],!!(raw[i]&1),(unsigned long long)base);
        if (raw[i]==~0ULL) {ret=-EIO;goto out;}
        if (!(raw[i]&1)) continue; /* Never dereference a disabled BAR. */
        if (!base || (raw[i]&~(0x7ffffff000ULL|1ULL)) ||
            base<0xfed00000ULL || base>0xfedff000ULL) {ret=-EINVAL;goto out;}
        enabled++;
        ret=snapshot_unit(base,"TCSS_BAR");
        if (ret) goto out;
    }
    pr_info(PFX "TCSS_SUMMARY enabled_units_sampled=%u known_ports=4 no_control_writes=1\n",enabled);
out:
    pci_dev_put(host);
    return ret;
}

static int __init snapshot_init(void)
{
    struct acpi_table_header *table=NULL;
    struct snapshot_dmar parsed;
    u8 *copy=NULL;
    unsigned int i,length;
    bool found=false;
    int ret;
    acpi_status status;
    if (boot_cpu_has(X86_FEATURE_HYPERVISOR) || cpuid_eax(1)!=0x000906a3) {
        pr_err(PFX "native CPU profile rejected\n");
        return -EPERM;
    }
    status=acpi_get_table(ACPI_SIG_DMAR,0,&table);
    if (ACPI_FAILURE(status) || !table) {
        pr_err(PFX "ACPI DMAR unavailable status=%x\n",status);
        return -ENODEV;
    }
    length=table->length;
    if (length<DMAR_FIXED_SIZE || length>DMAR_LIMIT) {ret=-EINVAL;goto release;}
    copy=kmemdup(table,length,GFP_KERNEL);
    if (!copy) {ret=-ENOMEM;goto release;}
    ret=parse_dmar(copy,length,&parsed);
    if (ret) goto release;
    pr_info(PFX "DMAR_VALID length=%u revision=%u host_address_width_encoded=%u flags=%02x drhd_count=%u checksum=00 cpu=000906a3 hypervisor=0\n",
            length,parsed.revision,parsed.host_width,parsed.flags,parsed.count);
    /* Preserve bounded raw evidence in the log; the full table is available in sysfs. */
    print_hex_dump(KERN_INFO,PFX "DMAR_RAW ",DUMP_PREFIX_OFFSET,16,1,copy,min(length,4096U),false);
    for (i=0;i<parsed.count;i++) {
        struct snapshot_drhd *unit=&parsed.units[i];
        pr_info(PFX "DRHD index=%u segment=%u base=%016llx flags=%02x scopes=%u sampled=%u\n",
                i,unit->segment,(unsigned long long)unit->base,unit->flags,unit->scopes,
                unit->segment==0 && unit->base==KNOWN_DRHD);
        if (unit->segment==0 && unit->base==KNOWN_DRHD) found=true;
    }
    if (!found) {ret=-ENODEV;goto release;}
    ret=snapshot_unit(KNOWN_DRHD,"ACPI_DRHD");
    if (!ret && sample_tcss) ret=snapshot_tcss();
release:
    kfree(copy);
    acpi_put_table(table);
    if (ret) {
        pr_err(PFX "snapshot failed rc=%d; no control-register writes performed\n",ret);
        return ret;
    }
    strscpy(result,sample_tcss ? "drhd_tcss_snapshot_ok" : "declared_drhd_snapshot_ok",sizeof(result));
    pr_info(PFX "result=%s no_control_writes=1\n",result);
    return 0;
}
static void __exit snapshot_exit(void) {}
module_init(snapshot_init);
module_exit(snapshot_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Read-only native ACPI DRHD and documented Alder Lake TCSS VT-d snapshot");
