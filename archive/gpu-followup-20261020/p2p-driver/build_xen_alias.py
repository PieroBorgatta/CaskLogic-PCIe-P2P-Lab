from pathlib import Path
import difflib,subprocess,shutil
D=Path('/mnt/llm/riscrivo/runtime/reports/gpu-followup-20261020/p2p-driver');S=D/'source/NVIDIA-open-gpu-kernel-modules-19f3b34'
p=S/'kernel-open/nvidia/nv-dma.c';old=p.read_text();needle='        *va = pci_bus_address(peer_pci_dev, bar_index) + offset;\n        status = NV_OK;'
new='''        *va = pci_bus_address(peer_pci_dev, bar_index) + offset;
        /* Isolated Xen trial: aliases installed by xc_domain_memory_mapping. */
        if (bar_index == 1 && peer_pci_dev->vendor == 0x10de)
        {
            NvU64 alias = 0;
            if (peer_pci_dev->device == 0x28b0 && res->start == 0x800000000ULL)
                alias = 0x780000000ULL;
            if (peer_pci_dev->device == 0x2571 && res->start == 0xc00000000ULL)
                alias = 0x7c0000000ULL;
            if (alias)
            {
                if (offset >= 0x2000000ULL || page_count > ((0x2000000ULL-offset) >> PAGE_SHIFT))
                    return NV_ERR_INVALID_REQUEST;
                *va = alias + offset;
            }
        }
        status = NV_OK;'''
assert old.count(needle)==1
updated=old.replace(needle,new);p.write_text(updated)
(D/'xen-low-gpa-alias.patch').write_text(''.join(difflib.unified_diff(old.splitlines(True),updated.splitlines(True),fromfile='a/kernel-open/nvidia/nv-dma.c',tofile='b/kernel-open/nvidia/nv-dma.c')))
with (D/'build-xen-alias.log').open('w') as f:r=subprocess.run(['make','modules','-j2'],cwd=S,stdout=f,stderr=subprocess.STDOUT)
assert r.returncode==0,r.returncode
out=D/'compiled-xen-alias';out.mkdir(exist_ok=True)
for m in ['nvidia','nvidia-uvm','nvidia-modeset','nvidia-drm']:shutil.copy2(S/'kernel-open'/(m+'.ko'),out/(m+'.ko'))
print('COMPILED',flush=True)
