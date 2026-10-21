// SPDX-License-Identifier: GPL-2.0-only
/* Active-PM candidate. Native RAM boot; topology-specific; no firmware writes. */
#include <linux/module.h>
#include <linux/pci.h>
#include <linux/ioport.h>
#include <linux/delay.h>
#include <linux/device.h>
#include <linux/pm_runtime.h>
#include <linux/string.h>
#include <asm/cpufeature.h>
#include <asm/processor.h>

#define PFX "CaskLowMMIO: "
#define NB 3
#define ND 7
#define NR 5
#define PREF_RES (PCI_BRIDGE_RESOURCES + 2)
#define B1_SIZE 0x10000000ULL
#define B3_SIZE 0x02000000ULL
#define WIN_SIZE (B1_SIZE + B3_SIZE)

static bool execute;
static unsigned long long base = 0x80000000ULL;
static char result[40] = "not_started";
module_param(execute, bool, 0400);
module_param(base, ullong, 0400);
module_param_string(result, result, sizeof(result), 0444);
MODULE_PARM_DESC(execute, "Default false: no BAR relocation; activate_audio may run standard PM callbacks. True changes RAM-boot PCI configuration.");

/* Root-to-leaf bridges, external GPU+audio, internal GPU+audio. */
static const struct { u8 bus, devfn; u16 vendor, device; } identity[ND] = {
    {0, PCI_DEVFN(7,0), 0x8086, 0x466e},
    {4, PCI_DEVFN(0,0), 0x1b21, 0x2461},
    {5, PCI_DEVFN(0,0), 0x1b21, 0x2461},
    {6, PCI_DEVFN(0,0), 0x10de, 0x2571},
    {6, PCI_DEVFN(0,1), 0x10de, 0x228e},
    {1, PCI_DEVFN(0,0), 0x10de, 0x28b0},
    {1, PCI_DEVFN(0,1), 0x10de, 0x22be},
};
static struct pci_dev *devs[ND];
static u16 old_command[ND];
static u32 old_cfg[NB][3], old_bars[4];
static u32 old_saved_bridge[NB][3], old_saved_bars[4];
static struct resource *res[NR], *old_parent[NR], *low_parent;
static resource_size_t old_start[NR], old_end[NR];
static unsigned long old_flags[NR];
static struct resource old_guard = {.name = "CaskLogic original prefetch reservation", .flags = IORESOURCE_MEM};
static struct resource new_guard = {.name = "CaskLogic low prefetch reservation", .flags = IORESOURCE_MEM};
static bool hardware_touched, tree_touched, pinned;
static unsigned int pm_refs;

static int read32(struct pci_dev *d, int off, u32 *v)
{
    return pci_read_config_dword(d, off, v) == PCIBIOS_SUCCESSFUL ? 0 : -EIO;
}

#include "audio_pm.inc"

static int write32_verify(struct pci_dev *d, int off, u32 v)
{
    u32 actual;
    if (pci_write_config_dword(d, off, v) != PCIBIOS_SUCCESSFUL ||
        read32(d, off, &actual) || actual != v) {
        pr_err(PFX "%s config %x write/readback failed\n", pci_name(d), off);
        return -EIO;
    }
    return 0;
}

static int command_verify(struct pci_dev *d, u16 value)
{
    u16 actual;
    if (pci_write_config_word(d, PCI_COMMAND, value) != PCIBIOS_SUCCESSFUL ||
        pci_read_config_word(d, PCI_COMMAND, &actual) != PCIBIOS_SUCCESSFUL ||
        actual != value)
        return -EIO;
    return 0;
}

static bool overlaps(resource_size_t a, resource_size_t z,
                     resource_size_t b, resource_size_t y)
{
    return a <= y && b <= z;
}

static int check_bus_members(struct pci_bus *bus, struct pci_dev *a,
                             struct pci_dev *b)
{
    struct pci_dev *d;
    unsigned int count = 0;
    if (!bus)
        return -EINVAL;
    list_for_each_entry(d, &bus->devices, bus_list) {
        if (d != a && d != b)
            return -EBUSY;
        count++;
    }
    return count == (b ? 2 : 1) ? 0 : -EINVAL;
}

static int check_children(struct resource *parent, struct resource *a,
                           struct resource *b)
{
    struct resource *r;
    unsigned int count = 0;
    for (r = parent->child; r; r = r->sibling) {
        if (r != a && r != b)
            return -EBUSY;
        count++;
    }
    return count == (b ? 2 : 1) ? 0 : -EINVAL;
}

static int verify_bridge_window(unsigned int i, bool original)
{
    unsigned int k;
    u32 v, want[3];
    resource_size_t start = original ? old_start[i] : base;
    resource_size_t end = original ? old_end[i] : base + WIN_SIZE - 1;
    want[0] = ((start >> 16) & 0xfff0) | (end & 0xfff00000) |
              (old_cfg[i][0] & 0x000f000f);
    want[1] = upper_32_bits(start);
    want[2] = upper_32_bits(end);
    for (k = 0; k < 3; k++)
        if (read32(devs[i], PCI_PREF_MEMORY_BASE + k * 4, &v) ||
            v != want[k])
            return -EIO;
    return 0;
}

/* Diagnostic clone: observations only, after get_noresume/device_lock.
 * usage_count includes this module's own reference. No resume, PCI read/write,
 * PM-state update or altered acceptance criterion is added here.
 */
static void log_preflight_state(void)
{
    unsigned int i;
    pr_info(PFX "DIAG cpu_signature=%08x hypervisor=%u execute=%u base=%#llx pm_refs=%u\n",
            cpuid_eax(1), !!boot_cpu_has(X86_FEATURE_HYPERVISOR),
            (unsigned int)execute, base, pm_refs);
    for (i = 0; i < ND; i++) {
        struct pci_dev *d = devs[i];
        struct dev_pm_info *power;
        if (!d) {
            pr_info(PFX "DIAG index=%u device_missing expected=%04x:%04x\n",
                    i, identity[i].vendor, identity[i].device);
            continue;
        }
        power = &d->dev.power;
        pr_info(PFX "DIAG index=%u bdf=%s id=%04x:%04x expected=%04x:%04x "
                "current_state=%d required_state=%d runtime_status=%d "
                "rpm_active_enum=%d rpm_suspended_enum=%d rpm_suspending_enum=%d rpm_resuming_enum=%d "
                "runtime_error=%d disable_depth=%u usage_count=%d pm_active=%u "
                "is_virtfn=%u driver=%s\n",
                i, pci_name(d), d->vendor, d->device,
                identity[i].vendor, identity[i].device,
                (int)READ_ONCE(d->current_state), (int)PCI_D0,
                (int)READ_ONCE(power->runtime_status),
                (int)RPM_ACTIVE, (int)RPM_SUSPENDED, (int)RPM_SUSPENDING, (int)RPM_RESUMING,
                READ_ONCE(power->runtime_error), (unsigned int)power->disable_depth,
                atomic_read(&power->usage_count), (unsigned int)pm_runtime_active(&d->dev),
                (unsigned int)d->is_virtfn, d->driver ? d->driver->name : "unbound");
        pr_info(PFX "DIAG index=%u identity_ok=%u d0_ok=%u non_vf_ok=%u pm_active_ok=%u "
                "driver_guard_ok=%u\n", i,
                (unsigned int)(d->vendor == identity[i].vendor && d->device == identity[i].device),
                (unsigned int)(d->current_state == PCI_D0), (unsigned int)!d->is_virtfn,
                (unsigned int)pm_runtime_active(&d->dev),
                (unsigned int)(i < NB || !d->driver));
    }
}

static int validate(void)
{
    unsigned int i, j;
    struct pci_dev *d = NULL;
    struct resource *r;
    int n;
    u32 lo, hi;
    resource_size_t start, end;

    log_preflight_state();
    if (boot_cpu_has(X86_FEATURE_HYPERVISOR) || cpuid_eax(1) != 0x000906a3)
        return -EPERM;
    if ((base & (B1_SIZE - 1)) || base < 0x50400000ULL ||
        base > 0xc0000000ULL - WIN_SIZE)
        return -EINVAL;
    for (i = 0; i < ND; i++) {
        if (!devs[i] || devs[i]->vendor != identity[i].vendor ||
            devs[i]->device != identity[i].device ||
            devs[i]->current_state != PCI_D0 || devs[i]->is_virtfn ||
            !pm_runtime_active(&devs[i]->dev))
            return -ENODEV;
        if (i >= NB && devs[i]->driver)
            return -EBUSY;
        if (pci_read_config_word(devs[i], PCI_COMMAND, &old_command[i]) != PCIBIOS_SUCCESSFUL)
            return -EIO;
        pr_info(PFX "original %s command=%04x\n", pci_name(devs[i]), old_command[i]);
    }
    for (i = 0; i < NB; i++) {
        if (devs[i]->hdr_type != PCI_HEADER_TYPE_BRIDGE)
            return -EINVAL;
        if (check_bus_members(devs[i]->subordinate, devs[i+1],
                              i == NB-1 ? devs[4] : NULL))
            return -EBUSY;
        if (devs[i+1]->bus->self != devs[i])
            return -EINVAL;
        res[i] = &devs[i]->resource[PREF_RES];
        /* subordinate bus pointers must refer to these actual resource objects. */
        if (pci_bus_resource_n(devs[i]->subordinate, 2) != res[i])
            return -EINVAL;
        for (j = 0; j < 3; j++) {
            if (read32(devs[i], PCI_PREF_MEMORY_BASE + j*4, &old_cfg[i][j]))
                return -EIO;
            old_saved_bridge[i][j] = devs[i]->saved_config_space[(PCI_PREF_MEMORY_BASE/4)+j];
        }
        if ((old_cfg[i][0] & 0x000f000f) != 0x00010001)
            return -EINVAL;
        start = ((u64)old_cfg[i][1] << 32) | ((old_cfg[i][0] & 0xfff0) << 16);
        end = ((u64)old_cfg[i][2] << 32) | (old_cfg[i][0] & 0xfff00000) | 0xfffff;
        /* Explicitly reject nonidentity host/bus translation. */
        if (res[i]->start != start || res[i]->end != end)
            return -EINVAL;
        pr_info(PFX "original %s pref=%08x/%08x/%08x\n", pci_name(devs[i]),
                old_cfg[i][0], old_cfg[i][1], old_cfg[i][2]);
    }
    res[3] = &devs[3]->resource[1];
    res[4] = &devs[3]->resource[3];
    if (resource_size(res[3]) != B1_SIZE || resource_size(res[4]) != B3_SIZE)
        return -EINVAL;
    for (i = 0; i < NR; i++) {
        if ((res[i]->flags & (IORESOURCE_MEM | IORESOURCE_PREFETCH | IORESOURCE_MEM_64)) !=
            (IORESOURCE_MEM | IORESOURCE_PREFETCH | IORESOURCE_MEM_64) ||
            res[i]->flags & (IORESOURCE_BUSY | IORESOURCE_UNSET | IORESOURCE_PCI_FIXED) ||
            !res[i]->parent)
            return -EINVAL;
        old_parent[i] = res[i]->parent;
        old_start[i] = res[i]->start;
        old_end[i] = res[i]->end;
        old_flags[i] = res[i]->flags;
        pr_info(PFX "original resource %u start=%pa end=%pa flags=%lx\n",
                i, &old_start[i], &old_end[i], old_flags[i]);
    }
    if (res[1]->parent != res[0] || res[2]->parent != res[1] ||
        res[3]->parent != res[2] || res[4]->parent != res[2] ||
        res[3]->child || res[4]->child ||
        check_children(res[0], res[1], NULL) ||
        check_children(res[1], res[2], NULL) ||
        check_children(res[2], res[3], res[4]))
        return -EBUSY;
    for (i = 0; i < 2; i++) {
        int off = PCI_BASE_ADDRESS_0 + (i ? 3 : 1) * 4;
        if (read32(devs[3], off, &lo) || read32(devs[3], off+4, &hi))
            return -EIO;
        if ((lo & 0xf) != 0xc || (((u64)hi << 32) | (lo & ~0xfU)) != old_start[i+3])
            return -EINVAL;
        old_bars[i*2] = lo;
        old_bars[i*2+1] = hi;
        pr_info(PFX "original %s BAR%d=%08x/%08x\n", pci_name(devs[3]),
                i ? 3 : 1, lo, hi);
        old_saved_bars[i*2] = devs[3]->saved_config_space[off/4];
        old_saved_bars[i*2+1] = devs[3]->saved_config_space[off/4+1];
    }
    low_parent = NULL;
    pci_bus_for_each_resource(devs[0]->bus, r, n) {
        if (r && (r->flags & IORESOURCE_MEM) && r->start == 0x50400000ULL &&
            r->end == 0xbfffffffULL && r->parent == &iomem_resource) {
            if (low_parent)
                return -EINVAL;
            low_parent = r;
        }
    }
    if (!low_parent)
        return -ENOSPC;
    for_each_pci_dev(d) {
        for (i = 0; i < PCI_NUM_RESOURCES; i++) {
            r = &d->resource[i];
            if ((r->flags & IORESOURCE_MEM) && r->end >= r->start &&
                overlaps(base, base+WIN_SIZE-1, r->start, r->end)) {
                pr_err(PFX "target overlaps %s resource %u\n", pci_name(d), i);
                pci_dev_put(d);
                return -EBUSY;
            }
        }
    }
    /* request_resource below performs the authoritative iomem tree check. */
    return 0;
}

static int gate_commands(void)
{
    int i;
    u16 flags, status;
    unsigned int tries;
    if (verify_live_pm_ready())
        return -EIO;
    hardware_touched = true;
    for (i = ND-1; i >= 0; i--) {
        flags = old_command[i] & ~PCI_COMMAND_MASTER;
        if (i < 5)
            flags &= ~PCI_COMMAND_MEMORY;
        if (command_verify(devs[i], flags))
            return -EIO;
    }
    msleep(50);
    for (i = 0; i < ND; i++) {
        for (tries = 0; tries < 100; tries++) {
            if (pcie_capability_read_word(devs[i], PCI_EXP_DEVSTA, &status))
                return -EIO;
            if (!(status & PCI_EXP_DEVSTA_TRPND))
                break;
            msleep(1);
        }
        if (tries == 100)
            return -EBUSY;
    }
    return 0;
}

static int detach_tree(void)
{
    int i;
    for (i = NR-1; i >= 0; i--) {
        if (res[i]->parent) {
            if (res[i]->child || release_resource(res[i]))
                return -EBUSY;
        }
    }
    return 0;
}

static int attach_tree(bool original)
{
    unsigned int i;
    struct resource *parent;
    for (i = 0; i < NR; i++) {
        res[i]->start = original ? old_start[i] : base + (i == 4 ? B1_SIZE : 0);
        res[i]->end = original ? old_end[i] :
            (i < 3 ? base+WIN_SIZE-1 : res[i]->start + (i == 3 ? B1_SIZE : B3_SIZE) - 1);
        res[i]->flags = old_flags[i];
        parent = i == 0 ? (original ? &old_guard : &new_guard) : res[i < 3 ? i-1 : 2];
        if (request_resource(parent, res[i]))
            return -EBUSY;
    }
    return 0;
}

static int program_config(bool original)
{
    int i;
    unsigned int k;
    u32 val[3];
    resource_size_t start, end;
    /* All affected bridges/endpoints have MSE=0 and all seven have BME=0. */
    for (i = 0; i < 2; i++) {
        int off = PCI_BASE_ADDRESS_0 + (i ? 3 : 1) * 4;
        start = original ? old_start[i+3] : base + (i ? B1_SIZE : 0);
        if (write32_verify(devs[3], off, lower_32_bits(start) | (old_bars[i*2] & 0xf)) ||
            write32_verify(devs[3], off+4, upper_32_bits(start)))
            return -EIO;
        devs[3]->saved_config_space[off/4] = original ? old_saved_bars[i*2] : lower_32_bits(start) | (old_bars[i*2] & 0xf);
        devs[3]->saved_config_space[off/4+1] = original ? old_saved_bars[i*2+1] : upper_32_bits(start);
    }
    for (i = NB-1; i >= 0; i--) {
        start = original ? old_start[i] : base;
        end = original ? old_end[i] : base+WIN_SIZE-1;
        val[0] = ((start >> 16) & 0xfff0) | (end & 0xfff00000) | (old_cfg[i][0] & 0x000f000f);
        val[1] = upper_32_bits(start);
        val[2] = upper_32_bits(end);
        /* Same disable-before-update order as Linux setup-bus.c. */
        if (write32_verify(devs[i], PCI_PREF_LIMIT_UPPER32, 0) ||
            write32_verify(devs[i], PCI_PREF_MEMORY_BASE, val[0]) ||
            write32_verify(devs[i], PCI_PREF_BASE_UPPER32, val[1]) ||
            write32_verify(devs[i], PCI_PREF_LIMIT_UPPER32, val[2]))
            return -EIO;
        for (k = 0; k < 3; k++)
            devs[i]->saved_config_space[PCI_PREF_MEMORY_BASE/4+k] =
                original ? old_saved_bridge[i][k] : val[k];
        if (verify_bridge_window(i, original))
            return -EIO;
    }
    return 0;
}

static int restore_commands(void)
{
    unsigned int i;
    /* Re-read hardware identity/D0 immediately before any COMMAND enable. */
    if (verify_live_pm_ready())
        return -EIO;
    /* Root first, endpoints last. Original values only after exact config/tree. */
    for (i = 0; i < ND; i++)
        if (command_verify(devs[i], old_command[i]))
            return -EIO;
    return 0;
}

static int verify_new_tree(void)
{
    unsigned int i;
    struct resource *parent;
    resource_size_t start, end;
    for (i = 0; i < NR; i++) {
        start = base + (i == 4 ? B1_SIZE : 0);
        end = i < 3 ? base+WIN_SIZE-1 : start+(i == 3 ? B1_SIZE : B3_SIZE)-1;
        parent = i == 0 ? low_parent : res[i < 3 ? i-1 : 2];
        if (res[i]->parent != parent || res[i]->start != start ||
            res[i]->end != end || res[i]->flags != old_flags[i])
            return -EINVAL;
    }
    return 0;
}

static int rollback(void)
{
    int ret = 0;
    unsigned int i;
    if (tree_touched) {
        if (detach_tree() || attach_tree(true) || program_config(true))
            return -EIO;
        if (remove_resource(&old_guard))
            return -EIO;
        for (i = 0; i < NR; i++)
            if (res[i]->parent != old_parent[i] || res[i]->start != old_start[i] ||
                res[i]->end != old_end[i] || res[i]->flags != old_flags[i])
                return -EIO;
    } else if (old_guard.parent) {
        if (remove_resource(&old_guard))
            return -EIO;
    }
    if (new_guard.parent && (new_guard.child || release_resource(&new_guard)))
        return -EIO;
    if (hardware_touched)
        ret = restore_commands();
    return ret;
}

static int __init low_init(void)
{
    unsigned int i, locked = 0;
    int ret;
    /* Reject another platform before any optional runtime-PM callback. */
    if (boot_cpu_has(X86_FEATURE_HYPERVISOR) || cpuid_eax(1) != 0x000906a3)
        return -EPERM;
    if ((base & (B1_SIZE - 1)) || base < 0x50400000ULL ||
        base > 0xc0000000ULL - WIN_SIZE)
        return -EINVAL;
    pci_lock_rescan_remove();
    for (i = 0; i < ND; i++) {
        devs[i] = pci_get_domain_bus_and_slot(0, identity[i].bus, identity[i].devfn);
        if (!devs[i]) {
            ret = -ENODEV;
            goto out;
        }
        /* Acquire all references before any resume or device_lock. */
        pm_runtime_get_noresume(&devs[i]->dev);
        pm_refs++;
    }
    /* PCI PM callbacks must never run with any device_lock held. */
    ret = prepare_audio_pm();
    if (ret)
        goto out;
    for (i = 0; i < ND; i++) {
        device_lock(&devs[i]->dev);
        locked++;
    }
    ret = verify_pm_config_resources();
    if (ret)
        goto out;
    ret = verify_live_pm_ready();
    if (ret)
        goto out;
    ret = validate();
    if (ret)
        goto out;
    new_guard.start = base;
    new_guard.end = base+WIN_SIZE-1;
    ret = request_resource(low_parent, &new_guard);
    if (ret)
        goto out;
    if (!execute) {
        ret = release_resource(&new_guard);
        if (ret && new_guard.parent)
            goto retain;
        if (!ret)
            strscpy(result, activate_audio ? "preflight_ok_pm_ready" :
                    "preflight_ok_no_hardware_writes", sizeof(result));
        goto out;
    }
    old_guard.start = old_start[0];
    old_guard.end = old_end[0];
    ret = insert_resource(old_parent[0], &old_guard);
    if (ret)
        goto failed;
    if (check_children(&old_guard, res[0], NULL)) {
        ret = -EBUSY;
        goto failed;
    }
    ret = gate_commands();
    if (ret)
        goto failed;
    tree_touched = true;
    ret = detach_tree();
    if (ret)
        goto failed;
    ret = attach_tree(false);
    if (ret)
        goto failed;
    ret = program_config(false);
    if (ret)
        goto failed;
    ret = verify_live_pm_ready();
    if (ret)
        goto failed;
    /* Keep guard objects until all config readbacks succeed. */
    ret = remove_resource(&new_guard);
    if (ret)
        goto failed;
    ret = verify_new_tree();
    if (ret)
        goto failed;
    ret = release_resource(&old_guard);
    if (ret)
        goto frozen;
    ret = restore_commands();
    if (ret)
        goto frozen;
    __module_get(THIS_MODULE);
    pinned = true;
    strscpy(result, "relocated_verified_reboot_to_restore", sizeof(result));
    pr_info(PFX "COMMITTED BAR1=%#llx BAR3=%#llx window=%#llx-%#llx\n",
            base, base+B1_SIZE, base, base+WIN_SIZE-1);
    goto out;
failed:
    pr_err(PFX "transaction failed %d; attempting exact rollback\n", ret);
    if (rollback())
        goto frozen;
    strscpy(result, "failed_original_restored", sizeof(result));
    goto out;
frozen:
    /* Preserve static reservations. Never allow GPU load after this result. */
    for (i = 0; i < ND; i++)
        command_verify(devs[i], old_command[i] & ~(PCI_COMMAND_MASTER | PCI_COMMAND_MEMORY));
retain:
    /* This label also handles a preflight resource-release error without any PCI write. */
    __module_get(THIS_MODULE);
    pinned = true;
    strscpy(result, "FATAL_REBOOT_REQUIRED", sizeof(result));
    pr_crit(PFX "FATAL: keep all GPU drivers unloaded; reboot required\n");
    ret = 0; /* Must retain any resource objects referenced by the kernel. */
out:
    while (locked)
        device_unlock(&devs[--locked]->dev);
    pci_unlock_rescan_remove();
    pr_info(PFX "result=%s rc=%d audio_pm_prepared=%u\n", result, ret,
            (unsigned int)audio_pm_prepared);
    /* Keep PM references through the isolated trial after a commit/fatal state. */
    if (!pinned)
        while (pm_refs)
            pm_runtime_put_noidle(&devs[--pm_refs]->dev);
    if (ret) {
        for (i = 0; i < ND; i++) {
            pci_dev_put(devs[i]);
            devs[i] = NULL;
        }
    }
    return ret;
}

static void __exit low_exit(void)
{
    unsigned int i;
    WARN_ON(pinned || old_guard.parent || new_guard.parent);
    for (i = 0; i < ND; i++)
        pci_dev_put(devs[i]);
}
module_init(low_init);
module_exit(low_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("CaskLogic isolated native PCI low-MMIO experiment with verified audio runtime resume");
