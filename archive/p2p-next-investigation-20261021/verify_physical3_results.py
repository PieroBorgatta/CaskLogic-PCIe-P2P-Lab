#!/usr/bin/env python3
"""Read-only root verification of PHYS3 logs, derived from the reviewed PHYS2 auditor."""
import hashlib
import json
import re
from pathlib import Path

R = Path(__file__).resolve().parent / 'native-physical3-ce-results'
kernel = (R / 'kernel.log').read_text().splitlines()
result = (R / 'result.log').read_text().splitlines()
protocol = json.loads((R / 'verified-protocol-root.json').read_text())

def check(value, label):
    if not value:
        raise ValueError(label)

def parse(line, index):
    d = dict(re.findall(r'(\w+)=([^\s]+)', line))
    d['_line'] = index + 1
    d['_text'] = line
    t = re.search(r'\[\s*([0-9.]+)\]', line)
    if t:
        d['_kernel_s'] = float(t[1])
    return d

def rows(marker, lines=kernel):
    return [parse(x, i) for i, x in enumerate(lines) if marker in x]

def one(items, label):
    check(len(items) == 1, label)
    return items[0]

def h(d, key):
    return int(d[key], 16)

manifest = json.loads((R / 'collected-sha256.json').read_text())
for name, digest in manifest.items():
    check(hashlib.sha256((R / name).read_bytes()).hexdigest() == digest, 'hash:' + name)
check(len(manifest) == 17, '17 collected files')

allocations = rows('P2PTRC UVM_ALLOCATION')
ptes = rows('P2PTRC UVM_PTE ')
windows = rows('P2PTRC WINDOW_CREATE ')
check(len(windows) == 2, 'two windows')
methods = rows('CASKPHYS ')
requests = []
for case in protocol['p2p']:
    if 'ioctl' not in case:
        continue
    q = case['ioctl']
    req = [x for x in methods if x['request'] == q['request']]
    m = one([x for x in req if x['stage'] == 'methods'], 'methods')
    ret = one([x for x in req if x['stage'] == 'return'], 'return')
    check(ret['operation'] == '1' and h(ret,'status') == 0 and h(ret,'flags') == 0x77, 'completed')
    check(ret['last_stage'] == 'submitted_wait' and ret['_line'] > m['_line'], 'completion order')
    for rk, qk in [('src_va','src'),('dst_va','dst'),('src_mem','source_handle'),
                   ('dst_mem','destination_handle'),('src_phys','source_pa'),
                   ('dst_phys','destination_pa'),('src_off','source_offset'),
                   ('dst_off','destination_offset'),('class','ce_class'),
                   ('launch','launch'),('src_mode','source_mode'),('dst_mode','destination_mode')]:
        check(h(m,rk) == h(q,qk), 'kernel/client:' + rk)
    check(m['bytes'] == '4' and m['p2p'] == m['privileged'] == m['no_virtual_fallback'] == '1', 'physical channel')
    check(h(m,'class') == 0xc7b5 and h(m,'launch') == 0x04003186 and h(m,'src_mode') == 0 and h(m,'dst_mode') == 1, 'exact methods')
    identities = {}
    for role in ('source','destination_peer','destination_owner'):
        rr = [x for x in req if x.get('role') == role]
        guards = one([x for x in rr if x['stage'] == 'map_guards'], 'guards:' + role)
        meta = one([x for x in rr if x['stage'] == 'map_meta'], 'meta:' + role)
        geom = one([x for x in rr if x['stage'] == 'map_geometry'], 'geometry:' + role)
        ident = one([x for x in rr if x['stage'] == 'map_identity'], 'identity:' + role)
        ready = one([x for x in rr if x['stage'] == 'map_ready'], 'ready:' + role)
        check(h(guards,'bits') == h(guards,'expected') == 0xffff, 'all map guards')
        check(h(meta,'kind') == 6 and meta['format'] == '0' and meta['mapping_type'] == '1', 'kind and permission metadata')
        check(meta['recorded'] == meta['device_descendant'] == '1' and meta['sysmem'] == meta['egm'] == '0', 'owned VRAM')
        check(h(meta,'page_size') == 0x200000, 'page size')
        check(h(geom,'map_offset') == 0 and h(geom,'allocation_size') == 0x800000, 'allocation bounds')
        check(geom['node_start'] == geom['origin_start'] and geom['node_end'] == geom['origin_end'], 'unsplit mapping')
        check(h(ready,'offset') == h(ready,'tracker_status') == 0 and ready['_line'] < m['_line'], 'mapping ready')
        identities[role] = ident
        if role != 'destination_owner':
            query = one([x for x in rr if x['stage'] == 'query_result'], 'RW query:' + role)
            check(query['mapping_type'] == '2' and h(query,'offset') == h(query,'status') == 0, 'RW query success')
            check(query['written'] == '1' and query['remaining'] == '0' and h(query,'page') == h(query,'bytes') == 4096, 'one page')
            pa = 'source_pa' if role == 'source' else 'destination_pa'
            check(h(query,'base') == h(q,pa) and query['_line'] < m['_line'], 'query supplies methods')
    peer, owner = identities['destination_peer'], identities['destination_owner']
    check(peer['user_client'] == owner['user_client'] and peer['user_object'] == owner['user_object'], 'same destination allocation')
    source_map = one([x for x in allocations if x['rm_mem'] == q['source_handle']], 'source allocation')
    source_pte = one([x for x in ptes if x['mem'] == q['source_handle']], 'source PTE')
    check(source_map['gpu_va'] == q['src'] and source_pte['gpu_va'] == q['src'], 'source VA')
    check(((h(source_pte,'raw0') >> 8) & ((1<<25)-1)) << 12 == h(q,'source_pa'), 'local VRAM PA from PTE')
    window = one([x for x in windows if x['mem'] == q['destination_handle']], 'destination window')
    reused = one([x for x in rows('P2PTRC WINDOW_REUSE ') if x['id'] == window['id']], 'existing window reused')
    peer_pte = one([x for x in ptes if x['mem'] == q['destination_handle']], 'peer PTE')
    check(h(window,'window_phys') == h(window,'dma') == h(reused,'dma') == h(q,'destination_pa'), 'BAR1 address unchanged')
    check(h(window,'bar1') + h(window,'bar1_off') == h(q,'destination_pa') and h(window,'size') == 0x800000, 'window geometry')
    check(((h(peer_pte,'raw0') >> 8) & ((1<<46)-1)) << 12 == h(q,'destination_pa'), 'peer PTE PA')
    check(peer_pte['gpu_va'] == q['dst'] and h(peer_pte,'page') == 0x200000 and peer_pte['count'] == '4', 'peer VA and PTE size')
    check(window['_line'] < reused['_line'] < m['_line'], 'existing allocation before CE')
    requests.append({'request':q['request'],'source':case['source'],'destination':case['destination'],
                     'source_va':q['src'],'destination_va':q['dst'],'source_pa':q['source_pa'],
                     'destination_pa':q['destination_pa'],'window_id':window['id'],'class':q['ce_class'],
                     'launch':q['launch'],'source_mode':0,'destination_mode':1,
                     'guards':'ffff','kind':6,'mapping_type_recorded':1,'query_mapping_type':2,
                     'completed':True,'kernel_methods_line':m['_line'],'kernel_return_line':ret['_line']})

snapshots = rows('PCIE_SNAPSHOT ',result)
baseline = {x['bdf']:x for x in snapshots if x['phase'] == 'physical_program_baseline'}
check(len(baseline) == 6, 'six PCI endpoints')
ignored = {'phase','monotonic','_line','_text'}
deltas = []
for row in snapshots:
    check(row['clock_ok'] == '1' and row['CONFIG_BYTES'] == '4096' and row['READ_ERRNO'] == '0', 'PCI read complete')
    base = baseline[row['bdf']]
    change = {k:[base.get(k),v] for k,v in row.items() if k not in ignored and base.get(k)!=v}
    if change:
        deltas.append({'phase':row['phase'],'bdf':row['bdf'],'changes':change})
check(not deltas, 'no PCI deltas')
phases = rows('CaskLogicPhysicalCE phase=')
done = one([x for x in phases if x['phase']=='data_done'],'data done')
exit_row = one([x for x in phases if x['phase']=='context_exit_begin'],'context exit')
frees = [x for x in phases if x['phase']=='allocation_free_begin']
check(len(frees)==4 and all(x['_line']>done['_line'] for x in frees),'free after data')
destroy = rows('P2PTRC WINDOW_DESTROY_DONE ')
check({x['id'] for x in destroy}=={'1','2'} and all(done['_line']<x['_line']<exit_row['_line'] for x in destroy),'window destruction')
assertions = rows('Assertion failed:')
leftover = rows('left-over mappings in IOVAS')
check(all(x['_line']>exit_row['_line'] for x in assertions+leftover),'cleanup errors after exit')
xid = rows('NVRM: Xid')
check(not xid,'no Xid')
check([x.split()[-1] for x in result if x.startswith('PEG_CCFG ')] == ['04008077']*3,'original D1 throughout')
check([x.split()[-1] for x in result if x.startswith('TCSS_CCFG ')] == ['0e009077']*6,'original D7 throughout')
summary = {'status':'ROOT_PHYS3_KERNEL_AUDIT_PASS','collected_hashes_verified':len(manifest),
           'collected_sha256':manifest,'requests':requests,'pci_snapshots':len(snapshots),
           'pci_deltas':deltas,'rma_new':False,'aer_new':False,'kind6_observed':True,
           'recorded_mapping_type':1,'data_done_kernel_s':done['_kernel_s'],
           'context_exit_kernel_s':exit_row['_kernel_s'],'windows_destroyed':2,
           'cleanup_assertions':len(assertions),'xid_count':len(xid),
           'first_assert_after_context_exit_ms':1000*(assertions[0]['_kernel_s']-exit_row['_kernel_s']) if assertions else None,
           'leftovers_after_context_exit_ms':[1000*(x['_kernel_s']-exit_row['_kernel_s']) for x in leftover],
           'raw_inputs_modified':False}
(R/'verified-kernel-root.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k not in ('collected_sha256',)},indent=2))
