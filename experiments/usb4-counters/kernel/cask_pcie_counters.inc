/* Diagnostic counters: opt-in, fixed MS-01/ASM2463 topology, setup only. */
#include <linux/dmi.h>
#include <linux/moduleparam.h>

static bool cask_pcie_counters;
module_param(cask_pcie_counters, bool, 0400);
MODULE_PARM_DESC(cask_pcie_counters,
                "MS-01 lab: enable PCIe path counters before path activation");

static bool cask_root(const struct tb_switch *sw)
{
 return tb_route(sw) == 0 && sw->vendor == 0x8087 && sw->device == 0x463e;
}

static bool cask_dock(const struct tb_switch *sw)
{
 return tb_route(sw) == 1 && sw->vendor == 0x00b8 && sw->device == 0x2463;
}

static int cask_pci_counter_plan(struct tb_path *path)
{
 struct tb_port *src, *dst;
 struct tb_path_hop *h;
 int ret;

 if (!cask_pcie_counters)
  return 0;
 if (!dmi_match(DMI_BOARD_NAME, "AHWSA") ||
     !dmi_match(DMI_BIOS_VERSION, "1.26"))
  return -ENODEV;
 /* Never alter an existing/firmware-discovered active path. */
 if (path->activated) {
  pr_info("CASKTB_COUNTER_SKIP discovered_active_path=1\n");
  return 0;
 }
 if (path->path_length != 2)
  return 0;
 src = path->hops[0].in_port;
 dst = path->hops[1].out_port;
 if (!((cask_root(src->sw) && src->port == 8 && tb_port_is_pcie_down(src) &&
        cask_dock(dst->sw) && dst->port == 3 && tb_port_is_pcie_up(dst)) ||
       (cask_dock(src->sw) && src->port == 3 && tb_port_is_pcie_up(src) &&
        cask_root(dst->sw) && dst->port == 8 && tb_port_is_pcie_down(dst))))
  return 0;

 /* Validate every proposed counter owner before assigning any index.
  * Lane counter1 is separate from control Hop0/counter0. Protocol uses0.
  * No extra register writes occur here: the standard path activation
  * clears the selected counter and programs CID/CE with Valid=1 once.
  */
 tb_path_for_each_hop(path, h) {
  struct tb_port *p = h->in_port;
  struct tb_regs_hop old;
  u32 cs1;
  int i, index = tb_port_is_null(p) ? 1 : 0;
  if (h->in_hop_index != TB_PCI_HOPID || h->in_counter_index != -1 ||
      !p->config.counters_support || p->config.max_counters <= index ||
      p->config.max_in_hop_id < TB_PCI_HOPID ||
      p->config.max_in_hop_id > 31 ||
      (!cask_root(p->sw) && !cask_dock(p->sw)) ||
      (tb_port_is_null(p) && p->port != 1))
   return -EINVAL;
  ret = tb_port_read(p, &cs1, TB_CFG_PORT, 1, 1);
  if (ret)
   return ret;
  /* Keep the observed USB4v1 packet-counting policy unchanged. */
  if (cs1 & GENMASK(23, 20))
   return -EINVAL;
  if (tb_port_is_null(p)) {
   ret = tb_port_read(p, &old, TB_CFG_HOPS, 0, 2);
   if (ret)
    return ret;
   if (old.counter_enable && old.counter == index)
    return -EBUSY;
  }
  for (i = TB_PATH_MIN_HOPID; i <= p->config.max_in_hop_id; i++) {
   ret = tb_port_read(p, &old, TB_CFG_HOPS, 2 * i, 2);
   if (ret)
    return ret;
   if ((i == TB_PCI_HOPID && (old.enable || old.pending)) ||
       (old.counter_enable && old.counter == index))
    return -EBUSY;
  }
 }
 tb_path_for_each_hop(path, h) {
  int index = tb_port_is_null(h->in_port) ? 1 : 0;
  h->in_counter_index = index;
  pr_info("CASKTB_COUNTER_PLAN route=%llx port=%u hop=%d index=%d path_inactive=1 standard_activation=1\n",
          tb_route(h->in_port->sw), h->in_port->port,
          h->in_hop_index, index);
 }
 return 0;
}
