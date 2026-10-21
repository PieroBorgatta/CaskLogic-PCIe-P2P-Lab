/* CPU-only tests: compile the actual included PM implementation with fake APIs.
 * No PCI, device file, kernel module, network, or hardware access exists here. */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <stdarg.h>

typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t resource_size_t;
#define ND 7
#define NB 3
#define PCI_NUM_RESOURCES 17
#define PCI_D0 0
#define PCI_VENDOR_ID 0
#define PCI_COMMAND 4
#define PCI_CAP_LIST_ID 0
#define PCI_CAP_ID_PM 1
#define PCI_PM_CTRL 4
#define PCI_PM_CTRL_STATE_MASK 3
#define PCIBIOS_SUCCESSFUL 0
#define RPM_ACTIVE 0
#define RPM_RESUMING 1
#define RPM_SUSPENDED 2
#define RPM_SUSPENDING 3
#define PFX "test: "
#define READ_ONCE(x) (x)
#define module_param(a,b,c)
#define MODULE_PARM_DESC(a,b)
typedef int atomic_t;
static int atomic_read(const atomic_t *a) { return *a; }
struct resource {
    resource_size_t start, end;
    unsigned long flags;
    struct resource *parent;
};
struct power_info {
    int runtime_status, runtime_error;
    unsigned int disable_depth;
    atomic_t usage_count;
};
struct device { struct power_info power; unsigned int index; };
struct pci_dev {
    u16 vendor, device;
    bool is_virtfn;
    int current_state;
    u8 pm_cap;
    void *driver;
    struct device dev;
    struct resource resource[PCI_NUM_RESOURCES];
    u32 config[64];
};
static const struct {u16 vendor, device;} identity[ND] = {
    {0x8086,0x466e},{0x1b21,0x2461},{0x1b21,0x2461},
    {0x10de,0x2571},{0x10de,0x228e},{0x10de,0x28b0},{0x10de,0x22be}
};
static struct pci_dev objects[ND], *devs[ND];
static struct resource parent[2];
static int read_error_index, read_error_offset;
static int read32(struct pci_dev *d, int off, u32 *v)
{
    if ((int)d->dev.index == read_error_index && off == read_error_offset)
        return -EIO;
    *v = d->config[off/4];
    return 0;
}
static int pci_read_config_word(struct pci_dev *d, int off, u16 *v)
{
    u32 value;
    if (read32(d, off & ~3, &value))
        return 1;
    *v = (u16)(value >> ((off & 2)*8));
    return 0;
}
static const char *pci_name(struct pci_dev *d) { (void)d; return "mock"; }
static void log_message(const char *format, ...) { (void)format; }
#define pr_err log_message
#define pr_info log_message
static bool pm_runtime_active(struct device *d)
{
    return d->power.runtime_status == RPM_ACTIVE || d->power.disable_depth;
}
static unsigned int calls, ref_puts, resume_mask;
static int fail_index, mutation;
static unsigned int mutate_index;
static int pm_runtime_resume_and_get(struct device *d)
{
    struct pci_dev *p = &objects[mutate_index];
    calls++;
    resume_mask |= 1U << d->index;
    if ((int)d->index == fail_index)
        return -EIO; /* Linux API returns failure without keeping another ref. */
    d->power.usage_count++;
    d->power.runtime_status = RPM_ACTIVE;
    switch (mutation) {
    case 1: d->power.runtime_status=RPM_SUSPENDED; break;
    case 2: p->config[PCI_COMMAND/4] ^= 4; break;
    case 3: p->config[PCI_COMMAND/4] ^= 0x20000000; break;
    case 4: p->config[0x14/4] ^= 0x1000; break;
    case 5: p->resource[1].start++; break;
    case 6: p->resource[1].end++; break;
    case 7: p->resource[1].flags ^= 8; break;
    case 8: p->resource[1].parent=&parent[1]; break;
    case 9: p->config[p->pm_cap/4+1] |= 3; break;
    case 10: p->current_state=3; break;
    case 11: p->config[0] ^= 1; break;
    case 12: p->driver=p; break;
    case 13: d->power.runtime_error=-EIO; break;
    case 14: d->power.runtime_status=RPM_RESUMING; break;
    default: break;
    }
    return 0;
}
static void pm_runtime_put_noidle(struct device *d)
{
    if (d->power.usage_count <= 0) {
        fprintf(stderr,"reference underflow\n");
        exit(2);
    }
    d->power.usage_count--;
    ref_puts++;
}
#include "audio_pm.inc"

static unsigned int cases;
static void demand(bool yes, const char *what)
{
    if (!yes) { fprintf(stderr,"FAILED case %u: %s\n",cases,what); exit(1); }
}
static void reset(void)
{
    unsigned int i,j;
    memset(objects,0,sizeof(objects));
    memset(pm_config_before,0,sizeof(pm_config_before));
    memset(pm_resource_before,0,sizeof(pm_resource_before));
    activate_audio=true;
    audio_pm_prepared=false;
    calls=ref_puts=resume_mask=0;
    fail_index=read_error_index=read_error_offset=-1;
    mutation=0;
    mutate_index=4;
    for (i=0;i<ND;i++) {
        struct pci_dev *d=&objects[i];
        devs[i]=d;
        d->vendor=identity[i].vendor;
        d->device=identity[i].device;
        d->current_state=PCI_D0;
        d->pm_cap=0x40;
        d->driver=i<NB?d:NULL;
        d->dev.index=i;
        d->dev.power.runtime_status=(i==4||i==6)?RPM_SUSPENDED:RPM_ACTIVE;
        d->dev.power.usage_count=(i==3||i==5)?2:1; /* includes our get_noresume */
        d->config[0]=((u32)d->device<<16)|d->vendor;
        d->config[PCI_COMMAND/4]=0x00100007;
        d->config[d->pm_cap/4]=PCI_CAP_ID_PM;
        d->config[d->pm_cap/4+1]=8; /* actual observation: PMCSR 0008 = D0 */
        for (j=0;j<PCI_NUM_RESOURCES;j++) {
            d->resource[j].start=(uint64_t)(i+1)*0x1000000+j*0x1000;
            d->resource[j].end=d->resource[j].start+0xfff;
            d->resource[j].flags=0x10220;
            d->resource[j].parent=&parent[0];
        }
    }
    cases++;
}
static void check_refs_and_release(void)
{
    unsigned int i;
    for (i=0;i<ND;i++) {
        int want=(i==3||i==5)?2:1;
        demand(objects[i].dev.power.usage_count==want,"one module reference remains for every device");
        pm_runtime_put_noidle(&objects[i].dev);
        demand(objects[i].dev.power.usage_count==want-1,"safe-exit puts balance original refs");
    }
}
int main(void)
{
    unsigned int i,m;
    int ret;
    reset();
    demand(prepare_audio_pm()==0,"observed D0/suspended audio resumes");
    demand(calls==2&&ref_puts==2&&resume_mask==((1U<<4)|(1U<<6)),"only two audio callbacks and ref swaps");
    demand(verify_live_pm_ready()==0,"all live identity/PM checks pass");
    demand(audio_pm_prepared,"records actual callbacks");
    check_refs_and_release();

    reset(); activate_audio=false;
    demand(prepare_audio_pm()==-EACCES&&calls==0,"default no opt-in never resumes");
    check_refs_and_release();
    reset(); activate_audio=false;
    objects[4].dev.power.runtime_status=objects[6].dev.power.runtime_status=RPM_ACTIVE;
    demand(prepare_audio_pm()==0&&calls==0&&!audio_pm_prepared,"already active needs no callback");
    check_refs_and_release();

    /* Every physical/cached identity and power failure aborts before callbacks. */
    for(i=0;i<ND;i++) {
        reset(); objects[i].config[0]^=1;
        demand(prepare_audio_pm()<0&&calls==0,"wrong live PCI ID");
        reset(); objects[i].vendor^=1;
        demand(prepare_audio_pm()<0&&calls==0,"wrong cached PCI ID");
        reset(); objects[i].current_state=3;
        demand(prepare_audio_pm()<0&&calls==0,"cached D3 rejected");
        reset(); objects[i].current_state=-1;
        demand(prepare_audio_pm()<0&&calls==0,"unknown cached state rejected");
        reset(); objects[i].config[0x44/4]|=3;
        demand(prepare_audio_pm()<0&&calls==0,"physical D3 rejected");
        reset(); objects[i].config[0x44/4]=0xffff;
        demand(prepare_audio_pm()<0&&calls==0,"invalid PMCSR rejected");
        reset(); objects[i].config[0x40/4]=2;
        demand(prepare_audio_pm()<0&&calls==0,"not a PM capability");
        reset(); objects[i].pm_cap=0;
        demand(prepare_audio_pm()<0&&calls==0,"missing PM capability");
        reset(); objects[i].pm_cap=0x42;
        demand(prepare_audio_pm()<0&&calls==0,"unaligned PM capability");
        reset(); objects[i].is_virtfn=true;
        demand(prepare_audio_pm()<0&&calls==0,"VF rejected");
        reset(); read_error_index=(int)i; read_error_offset=0x44;
        demand(prepare_audio_pm()<0&&calls==0,"PMCSR read error rejected");
        reset(); objects[i].dev.power.runtime_error=-EIO;
        demand(prepare_audio_pm()<0&&calls==0,"runtime error rejected");
        reset(); objects[i].dev.power.runtime_status=RPM_SUSPENDING;
        demand(prepare_audio_pm()<0&&calls==0,"in-flight suspend rejected");
        reset(); objects[i].dev.power.runtime_status=RPM_RESUMING;
        demand(prepare_audio_pm()<0&&calls==0,"in-flight resume rejected");
    }
    for(i=0;i<ND;i++) {
        if(i==4||i==6) continue;
        reset(); objects[i].dev.power.runtime_status=RPM_SUSPENDED;
        demand(prepare_audio_pm()<0&&calls==0,"non-audio suspended never resumed");
    }
    for(i=NB;i<ND;i++) {
        reset(); objects[i].driver=&objects[i];
        demand(prepare_audio_pm()<0&&calls==0,"endpoint bound rejected");
    }
    for(i=4;i<=6;i+=2) {
        reset(); objects[i].dev.power.usage_count=2;
        demand(prepare_audio_pm()<0&&calls==0,"suspended audio other PM users rejected");
        reset(); fail_index=(int)i;
        demand(prepare_audio_pm()==-EIO,"resume failure propagated");
        demand(ref_puts==(i==4?0U:1U),"failure has no extra put");
        check_refs_and_release();
    }
    /* Failed postconditions are caught after successful resume, refs still balanced. */
    for(m=1;m<=14;m++) {
        reset(); mutation=(int)m;
        ret=prepare_audio_pm();
        if(m==3) {
            demand(ret==0,"live STATUS bits excluded, COMMAND still exact");
        } else {
            demand(ret<0,"resume mutation rejected");
        }
        check_refs_and_release();
    }
    /* Config/resource verification covers every target, not only resumed audio. */
    for(i=0;i<ND;i++) {
        reset(); mutation=4; mutate_index=i;
        demand(prepare_audio_pm()<0,"foreign-device config change rejected");
        reset(); mutation=5; mutate_index=i;
        demand(prepare_audio_pm()<0,"foreign-device resource change rejected");
    }
    /* Same live guard used immediately before COMMAND enables. */
    for(i=0;i<ND;i++) {
        reset(); demand(prepare_audio_pm()==0,"setup succeeds");
        objects[i].config[0x44/4]|=3;
        demand(verify_live_pm_ready()<0,"late physical D3 rejected");
        reset(); demand(prepare_audio_pm()==0,"setup succeeds");
        objects[i].config[0]^=1;
        demand(verify_live_pm_ready()<0,"late identity change rejected");
        reset(); demand(prepare_audio_pm()==0,"setup succeeds");
        objects[i].dev.power.runtime_status=RPM_SUSPENDED;
        demand(verify_live_pm_ready()<0,"late suspension rejected");
    }
    printf("{\"status\":\"PASS\",\"cases\":%u,\"source\":\"audio_pm.inc\",\"hardware_access\":false}\n",cases);
    return 0;
}
