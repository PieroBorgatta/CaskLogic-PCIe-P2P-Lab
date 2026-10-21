#!/usr/bin/env python3
"""Crea solo overlay/diff locali; nessuna compilazione, installazione o chiamata GPU."""
import difflib
import hashlib
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
BASE=ROOT/'runtime/reports/p2p-tcss-bit-tests-20261021/driver-instrumented/validated-complete-tree/source/NVIDIA-open-gpu-kernel-modules-19f3b34'
REL=Path('kernel-open/nvidia-uvm')

def once(s,old,new):
    if s.count(old)!=1: raise RuntimeError('Anchor non univoco: '+old[:100])
    return s.replace(old,new)

def sha(b): return hashlib.sha256(b).hexdigest()

sources={}
for name in ('uvm_va_range.h','uvm_map_external.c','uvm_test_ioctl.h','uvm_test.h','uvm_test.c','uvm_gpu.h','uvm_gpu.c'):
    sources[name]=(BASE/REL/name).read_text()
outputs=dict(sources)
outputs['uvm_va_range.h']=once(outputs['uvm_va_range.h'], '    bool need_l2_invalidate_at_unmap;\n} uvm_ext_gpu_map_t;', '''    bool need_l2_invalidate_at_unmap;

    // CaskLogic test-only provenance from the validated RM duplication/map.
    // These fields do not affect mappings. Split maps deliberately do not copy
    // them; the diagnostic additionally requires the original unsplit interval.
    bool cask_phys_recorded;
    bool cask_phys_device_descendant;
    NvU32 cask_phys_kind;
    NvU32 cask_phys_format;
    NvU32 cask_phys_mapping_type;
    NvU64 cask_phys_page_size;
    NvU64 cask_phys_origin_start;
    NvU64 cask_phys_origin_end;
    NvU64 cask_phys_map_offset;
    NvU64 cask_phys_allocation_size;
    NvHandle cask_phys_user_client;
    NvHandle cask_phys_user_object;
} uvm_ext_gpu_map_t;''')
outputs['uvm_map_external.c']=once(outputs['uvm_map_external.c'], '''    status = set_ext_gpu_map_location(ext_gpu_map, va_space, mapping_gpu, &mem_info);
    if (status != NV_OK)
        goto error;

    // Determine''','''    status = set_ext_gpu_map_location(ext_gpu_map, va_space, mapping_gpu, &mem_info);
    if (status != NV_OK)
        goto error;

    // Diagnostic metadata only. Preserve the allocation page size before the
    // existing code selects a possibly smaller mapping page size below.
    ext_gpu_map->cask_phys_device_descendant = mem_info.deviceDescendant;
    ext_gpu_map->cask_phys_kind = mem_info.kind;
    ext_gpu_map->cask_phys_format = map_rm_params->format_type;
    ext_gpu_map->cask_phys_mapping_type = map_rm_params->mapping_type;
    ext_gpu_map->cask_phys_page_size = mem_info.pageSize;
    ext_gpu_map->cask_phys_origin_start = base;
    ext_gpu_map->cask_phys_origin_end = base + length - 1;
    ext_gpu_map->cask_phys_map_offset = map_rm_params->map_offset;
    ext_gpu_map->cask_phys_allocation_size = mem_info.size;
    ext_gpu_map->cask_phys_user_client = user_rm_mem->user_client;
    ext_gpu_map->cask_phys_user_object = user_rm_mem->user_object;

    // Determine''')
outputs['uvm_map_external.c']=once(outputs['uvm_map_external.c'], '''                                            out_tracker);
    if (status != NV_OK)
        goto error;

    uvm_mutex_unlock(&range_tree->lock);
    return NV_OK;''','''                                            out_tracker);
    if (status != NV_OK)
        goto error;

    ext_gpu_map->cask_phys_recorded = true;
    uvm_mutex_unlock(&range_tree->lock);
    return NV_OK;''')
outputs['uvm_map_external.c'] += '\n// Isolated diagnostic entry point; ordinary mapping and cleanup are unchanged.\n#include "cask_phys_ce.inc"\n'
outputs['uvm_test_ioctl.h']=once(outputs['uvm_test_ioctl.h'], '#include "nv_uvm_user_types.h"', '#include "nv_uvm_user_types.h"\n#include "cask_phys_ce_ioctl.h"')
outputs['uvm_test_ioctl.h']=once(outputs['uvm_test_ioctl.h'], '#define UVM_TEST_IOCTL_BASE(i)                          UVM_IOCTL_BASE(200 + i)', '#define UVM_TEST_IOCTL_BASE(i)                          UVM_IOCTL_BASE(200 + i)\n#define UVM_TEST_CASK_PHYSICAL_CE                       UVM_TEST_IOCTL_BASE(115)')
outputs['uvm_test.h']=once(outputs['uvm_test.h'], 'NV_STATUS uvm_test_ce_sanity(UVM_TEST_CE_SANITY_PARAMS *params, struct file *filp);', 'NV_STATUS uvm_test_ce_sanity(UVM_TEST_CE_SANITY_PARAMS *params, struct file *filp);\nNV_STATUS uvm_test_cask_physical_ce(UVM_TEST_CASK_PHYSICAL_CE_PARAMS *params, struct file *filp);')
outputs['uvm_test.c']=once(outputs['uvm_test.c'], '        UVM_ROUTE_CMD_STACK_INIT_CHECK(UVM_TEST_CE_SANITY,                    uvm_test_ce_sanity);', '        UVM_ROUTE_CMD_STACK_INIT_CHECK(UVM_TEST_CE_SANITY,                    uvm_test_ce_sanity);\n        UVM_ROUTE_CMD_STACK_INIT_CHECK(UVM_TEST_CASK_PHYSICAL_CE,             uvm_test_cask_physical_ce);')
outputs['uvm_gpu.h']=once(outputs['uvm_gpu.h'], 'void uvm_gpu_release_pcie_peer_access(uvm_gpu_t *gpu0, uvm_gpu_t *gpu1);', '''void uvm_gpu_release_pcie_peer_access(uvm_gpu_t *gpu0, uvm_gpu_t *gpu1);

// CaskLogic diagnostic: retain only an already existing PCIE_BAR1 pairing.
// Requires global_lock; success retains the pairing and both GPU objects.
// Release must run after any VA-space lock is dropped.
NV_STATUS uvm_gpu_cask_retain_existing_bar1_peer(uvm_gpu_t *gpu0, uvm_gpu_t *gpu1);
void uvm_gpu_cask_release_bar1_peer(uvm_gpu_t *gpu0, uvm_gpu_t *gpu1);''')
outputs['uvm_gpu.c']=once(outputs['uvm_gpu.c'], 'uvm_gpu_link_type_t uvm_parent_gpu_peer_link_type(uvm_parent_gpu_t *parent_gpu0, uvm_parent_gpu_t *parent_gpu1)\n{', '''// Diagnostic counterpart for the automatically discovered BAR1 pairing.
// Deliberately never calls peers_init: an existing nonzero reference is required
// while global_lock excludes removal. No RM API or normal peer policy changes.
NV_STATUS uvm_gpu_cask_retain_existing_bar1_peer(uvm_gpu_t *gpu0, uvm_gpu_t *gpu1)
{
    NV_STATUS status;
    uvm_assert_mutex_locked(&g_uvm_global.global_lock);
    if (!gpu0 || !gpu1 || gpu0->parent == gpu1->parent ||
        uvm_parent_gpu_peer_link_type(gpu0->parent, gpu1->parent) != UVM_GPU_LINK_PCIE_BAR1 ||
        uvm_gpu_peer_ref_count(gpu0, gpu1) == 0 ||
        uvm_gpu_peer_ref_count(gpu0, gpu1) == NV_U64_MAX)
        return NV_ERR_NOT_SUPPORTED;
    status = peers_retain(gpu0, gpu1);
    if (status != NV_OK)
        return status;
    uvm_gpu_retain(gpu0);
    uvm_gpu_retain(gpu1);
    return NV_OK;
}

void uvm_gpu_cask_release_bar1_peer(uvm_gpu_t *gpu0, uvm_gpu_t *gpu1)
{
    uvm_assert_mutex_locked(&g_uvm_global.global_lock);
    UVM_ASSERT(uvm_parent_gpu_peer_link_type(gpu0->parent, gpu1->parent) == UVM_GPU_LINK_PCIE_BAR1);
    UVM_ASSERT(uvm_gpu_peer_ref_count(gpu0, gpu1) > 1);
    peers_release(gpu0, gpu1);
    uvm_gpu_release_locked(gpu0);
    uvm_gpu_release_locked(gpu1);
}

uvm_gpu_link_type_t uvm_parent_gpu_peer_link_type(uvm_parent_gpu_t *parent_gpu0, uvm_parent_gpu_t *parent_gpu1)
{''')
for name in ('cask_phys_ce_ioctl.h','cask_phys_ce.inc'):
    outputs[name]=(HERE/name).read_text()
files={}
diff=[]
for name in sorted(outputs):
    new=outputs[name];old=sources.get(name,'');rel=str(REL/name)
    dest=HERE/'overlay'/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(new)
    files[rel]={'preimage_sha256':sha(old.encode()) if name in sources else None,
                'postimage_sha256':sha(new.encode()),'size':len(new.encode()),'new_file':name not in sources}
    diff.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),
                 fromfile='a/'+rel if name in sources else '/dev/null',tofile='b/'+rel))
patch=''.join(diff);(HERE/'physical-ce.patch').write_text(patch)
manifest={'status':'source_candidate_not_compiled_not_loaded','baseline_source_root':str(BASE),
          'baseline_nvidia_sha256':'ab41b0a38e7ab92c0d1468b33c456c5c5c57501c67dfe5a666f49aed9fb6b1b5',
          'baseline_uvm_sha256':'9b993671ef066c9d3e58fd52b0d70228861769a2e3dcf304bc3d80bca089c4d0',
          'kernel':'7.0.0-38-generic','driver':'595.99.02','only_module_to_rebuild':'nvidia-uvm',
          'parameter':'uvm_cask_physical_ce','parameter_default':False,'parameter_mode':'0400',
          'required_builtin_tests_parameter':'uvm_enable_builtin_tests=1','abi':1,'ioctl':315,'bytes':4,
          'abi_size':144,'files':files,'patch_sha256':sha(patch.encode()),
          'generator_sha256':sha(Path(__file__).read_bytes()),'hardware_operations':False,
          'rm_changes':False,'baseline_mapping_or_cleanup_changes':False,
          'limitations':['Physical destination explicitly uses NONCOHERENT_SYSMEM; stock UVM SYS CE helper uses COHERENT_SYSMEM.',
                         'Expected completion is CE tracker completion, not proof that remote data arrived.',
                         'Unconfirmed completion deliberately retains peer pair, GPU objects and duplicate handles until reboot.',
                         'Only unsplit original external VMM mappings and exact native CPU/two GPU identities are accepted.']}
(HERE/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'files':len(files),'patch_sha256':manifest['patch_sha256']}))
