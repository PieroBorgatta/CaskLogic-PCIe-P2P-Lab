/* Included by the kernel module and the offline mocked-API tests.
 * Only the two known unbound NVIDIA audio functions may be resumed.
 * All callbacks run before any device_lock; rescan/remove lock is held.
 */
static bool activate_audio;
module_param(activate_audio, bool, 0400);
MODULE_PARM_DESC(activate_audio, "Opt in to standard runtime resume of the two verified unbound audio functions already in physical D0.");
static bool audio_pm_prepared;
static u32 pm_config_before[ND][16];
static struct {
    resource_size_t start, end;
    unsigned long flags;
    struct resource *parent;
} pm_resource_before[ND][PCI_NUM_RESOURCES];

static bool is_trial_audio(unsigned int i)
{
    return i == 4 || i == 6;
}

static int live_identity_and_d0(unsigned int i)
{
    struct pci_dev *d = devs[i];
    u32 id;
    u16 cap, pmcsr;
    if (!d || d->vendor != identity[i].vendor || d->device != identity[i].device ||
        d->is_virtfn || d->current_state != PCI_D0)
        return -ENODEV;
    if (read32(d, PCI_VENDOR_ID, &id) ||
        id != ((u32)identity[i].device << 16 | identity[i].vendor))
        return -ENODEV;
    if (d->pm_cap < 0x40 || d->pm_cap > 0xf8 || (d->pm_cap & 3))
        return -EINVAL;
    if (pci_read_config_word(d, d->pm_cap + PCI_CAP_LIST_ID, &cap) != PCIBIOS_SUCCESSFUL ||
        cap == 0xffff || (cap & 0xff) != PCI_CAP_ID_PM ||
        pci_read_config_word(d, d->pm_cap + PCI_PM_CTRL, &pmcsr) != PCIBIOS_SUCCESSFUL ||
        pmcsr == 0xffff || (pmcsr & PCI_PM_CTRL_STATE_MASK) != PCI_D0) {
        pr_err(PFX "PM live identity/D0 check failed index=%u bdf=%s\n", i, pci_name(d));
        return -EIO;
    }
    return 0;
}

static int pm_state_guard(unsigned int i, bool allow_audio_suspended)
{
    struct pci_dev *d = devs[i];
    int status = READ_ONCE(d->dev.power.runtime_status);
    int error = READ_ONCE(d->dev.power.runtime_error);
    if (i >= NB && d->driver)
        return -EBUSY;
    if (error || status == RPM_SUSPENDING || status == RPM_RESUMING)
        return -EBUSY;
    if (pm_runtime_active(&d->dev))
        return 0;
    /* The observed case: enabled PM, only our reference, no driver, physical D0. */
    if (allow_audio_suspended && is_trial_audio(i) && !d->driver &&
        !d->dev.power.disable_depth && status == RPM_SUSPENDED &&
        atomic_read(&d->dev.power.usage_count) == 1)
        return 0;
    return -ENODEV;
}

static int capture_pm_baseline(void)
{
    unsigned int i, j;
    int ret;
    for (i = 0; i < ND; i++) {
        ret = live_identity_and_d0(i);
        if (ret)
            return ret;
        ret = pm_state_guard(i, true);
        if (ret)
            return ret;
        for (j = 0; j < 16; j++)
            if (read32(devs[i], j * 4, &pm_config_before[i][j]))
                return -EIO;
        for (j = 0; j < PCI_NUM_RESOURCES; j++) {
            struct resource *r = &devs[i]->resource[j];
            pm_resource_before[i][j].start = r->start;
            pm_resource_before[i][j].end = r->end;
            pm_resource_before[i][j].flags = r->flags;
            pm_resource_before[i][j].parent = r->parent;
        }
    }
    return 0;
}

static int verify_pm_config_resources(void)
{
    unsigned int i, j;
    u32 value, mask;
    for (i = 0; i < ND; i++) {
        if (live_identity_and_d0(i))
            return -EIO;
        for (j = 0; j < 16; j++) {
            /* PCI STATUS is live/W1C. COMMAND and all other header fields stay exact. */
            mask = j == PCI_COMMAND / 4 ? 0x0000ffff : 0xffffffff;
            if (read32(devs[i], j * 4, &value) ||
                (value & mask) != (pm_config_before[i][j] & mask)) {
                pr_err(PFX "PM resume changed config %s offset=%x\n", pci_name(devs[i]), j * 4);
                return -EIO;
            }
        }
        for (j = 0; j < PCI_NUM_RESOURCES; j++) {
            struct resource *r = &devs[i]->resource[j];
            if (r->start != pm_resource_before[i][j].start ||
                r->end != pm_resource_before[i][j].end ||
                r->flags != pm_resource_before[i][j].flags ||
                r->parent != pm_resource_before[i][j].parent) {
                pr_err(PFX "PM resume changed resource %s index=%u\n", pci_name(devs[i]), j);
                return -EIO;
            }
        }
    }
    return 0;
}

static int prepare_audio_pm(void)
{
    unsigned int i;
    int ret;
    ret = capture_pm_baseline();
    if (ret)
        return ret;
    for (i = 0; i < ND; i++) {
        if (!is_trial_audio(i) || pm_runtime_active(&devs[i]->dev))
            continue;
        if (!activate_audio) {
            pr_err(PFX "PM audio needs explicit activate_audio=1: %s\n", pci_name(devs[i]));
            return -EACCES;
        }
        ret = live_identity_and_d0(i);
        if (ret)
            return ret;
        ret = pm_state_guard(i, true);
        if (ret)
            return ret;
        pr_info(PFX "PM resume_and_get begin index=%u bdf=%s usage=%d\n",
                i, pci_name(devs[i]), atomic_read(&devs[i]->dev.power.usage_count));
        ret = pm_runtime_resume_and_get(&devs[i]->dev);
        if (ret < 0) {
            /* A failed resume_and_get does not acquire an extra reference. */
            pr_err(PFX "PM resume_and_get failed %s rc=%d; relocation not started\n",
                    pci_name(devs[i]), ret);
            return ret;
        }
        /* Exchange the noresume reference for the successfully acquired active one. */
        pm_runtime_put_noidle(&devs[i]->dev);
        audio_pm_prepared = true;
        pr_info(PFX "PM resume_and_get done index=%u bdf=%s usage=%d runtime_status=%d\n",
                i, pci_name(devs[i]), atomic_read(&devs[i]->dev.power.usage_count),
                (int)READ_ONCE(devs[i]->dev.power.runtime_status));
        ret = pm_state_guard(i, false);
        if (ret)
            return ret;
        ret = verify_pm_config_resources();
        if (ret)
            return ret;
    }
    return verify_pm_config_resources();
}

static int verify_live_pm_ready(void)
{
    unsigned int i;
    int ret;
    for (i = 0; i < ND; i++) {
        ret = live_identity_and_d0(i);
        if (ret)
            return ret;
        ret = pm_state_guard(i, false);
        if (ret)
            return ret;
    }
    return 0;
}
