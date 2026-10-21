#!/usr/bin/env python3
"""Decodifica soltanto copie locali: nessun accesso a /dev o sysfs."""
import hashlib
import json
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent
source = ROOT / 'snapshot.json'
data = json.loads(source.read_text())
root_low = (0x50400000, 0xbfffffff)
occupied = []
registers = {}

def overlap(a, b):
    return a[0] <= b[1] and b[0] <= a[1]

for bdf, device in data['pci'].items():
    for index, line in enumerate(device['resources'].splitlines()):
        start, end, flags = [int(v, 16) for v in line.split()]
        if flags & 0x200 and end >= start and overlap((start, end), root_low):
            occupied.append({'start': max(start, root_low[0]),
                             'end': min(end, root_low[1]),
                             'source': bdf + ' resource ' + str(index)})
    if 'config_hex' not in device:
        continue
    config = bytes.fromhex(device['config_hex'])
    if len(config) < 4096 or int(device['class'], 16) != 0x060400:
        continue
    def u32(offset):
        return struct.unpack_from('<I', config, offset)[0]
    fields = {hex(offset): '0x%08x' % u32(offset) for offset in
              [4, 0x18, 0x20, 0x24, 0x28, 0x2c, 0xd0, 0xd4, 0xd8,
               0xf0, 0xba0, 0xba4, 0xba8, 0xbac, 0xbb0, 0xbb4,
               0xbb8, 0xbbc, 0xbc0]}
    pmbl = u32(0x24)
    mbl = u32(0x20)
    pref_base = ((pmbl & 0xfff0) << 16) | (u32(0x28) << 32)
    pref_limit = (pmbl & 0xfff00000) | (u32(0x2c) << 32) | 0xfffff
    registers[bdf] = {'raw': fields, 'memory_space_enabled': bool(u32(4) & 2),
                      'pref_base': pref_base, 'pref_limit': pref_limit,
                      'pref_64bit_base': (pmbl & 0xf) == 1,
                      'pref_64bit_limit': ((pmbl >> 16) & 0xf) == 1,
                      'mem_base': (mbl & 0xfff0) << 16,
                      'mem_limit': (mbl & 0xfff00000) | 0xfffff}
    if bdf in ('0000:00:07.0', '0000:00:07.2'):
        cap = u32(0xba4)
        registers[bdf]['fpb'] = {
            'capability_id': u32(0xba0) & 0xff,
            'rid_supported': bool(cap & 1),
            'low_supported': bool(cap & 2),
            'high_supported': bool(cap & 4),
            'rid_enabled': bool(u32(0xba8) & 1),
            'low_enabled': bool(u32(0xbb0) & 1),
            'high_enabled': bool(u32(0xbb4) & 1),
            'high_granularity_code': (u32(0xbb4) >> 4) & 0xf,
            'high_vector_base': (u32(0xbb4) & 0xf0000000) | (u32(0xbb8) << 32),
            'vector_access_selector_raw': u32(0xbbc),
            'vector_access_data_raw': u32(0xbc0),
            'vector_note': 'BC0 reads only the currently selected DWORD; no vector-select writes performed.'}

for line in (ROOT / 'iomem.txt').read_text().splitlines():
    match = re.match(r'\s*([0-9a-f]+)-([0-9a-f]+) : (.*)$', line)
    if not match:
        continue
    start, end = int(match[1], 16), int(match[2], 16)
    if (start, end) == root_low and match[3] == 'PCI Bus 0000:00':
        continue
    if overlap((start, end), root_low):
        occupied.append({'start': max(start, root_low[0]),
                         'end': min(end, root_low[1]), 'source': 'iomem: ' + match[3]})

for key, value in data['firmware_memmap'].items():
    start, end = int(value['start'], 16), int(value['end'], 16)
    if overlap((start, end), root_low):
        occupied.append({'start': max(start, root_low[0]),
                         'end': min(end, root_low[1]),
                         'source': 'firmware_memmap ' + key + ': ' + value['type']})

merged = []
for item in sorted(occupied, key=lambda row: (row['start'], row['end'])):
    if merged and item['start'] <= merged[-1][1] + 1:
        merged[-1][1] = max(merged[-1][1], item['end'])
    else:
        merged.append([item['start'], item['end']])
free = []
cursor = root_low[0]
for start, end in merged:
    if start > cursor:
        free.append([cursor, start - 1])
    cursor = max(cursor, end + 1)
if cursor <= root_low[1]:
    free.append([cursor, root_low[1]])

geometry = []
for start, end in free:
    bar1_base = (start + 0xfffffff) & ~0xfffffff
    bar1_end = bar1_base + 0x10000000 - 1
    bar3_base = (bar1_end + 1 + 0x1ffffff) & ~0x1ffffff
    bar3_end = bar3_base + 0x2000000 - 1
    if bar3_end <= end:
        geometry.append({'bar1_base': bar1_base, 'bar1_end': bar1_end,
                         'bar3_base': bar3_base, 'bar3_end': bar3_end,
                         'window_base': bar1_base, 'window_limit': bar3_end,
                         'bytes': bar3_end - bar1_base + 1,
                         'selection': 'First 256MiB-aligned base in each free interval, followed by 32MiB-aligned BAR3.'})

report = {'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
          'context': data['context'], 'boot_id': data['boot_id'],
          'hardware_writes': False, 'registers': registers,
          'root_low_window': list(root_low), 'occupied': occupied,
          'free_intervals_dom0_only': free, 'hypothetical_256M_plus_32M_geometry': geometry,
          'ready_for_relocation': False,
          'limitations': [
              'Snapshot is Xen dom0, not the native test boot.',
              'A2000 currently has 8GiB BAR1; 256MiB size is observed only after native tunnel recreation.',
              'No proof of a peer-only 32bit routing limit has been established.',
              'Native resource map, actual BAR sizes, command bits, bridge windows, Linux resource model, and PTE addresses must be checked before a relocation trial.',
              'No FPB vector is enabled in the observed D7 registers; support alone is not P2P permission.']}
(ROOT / 'decode-analysis.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'free': [[hex(a), hex(b)] for a,b in free],
                  'hypothetical_geometry': [{k: hex(v) if isinstance(v,int) else v for k,v in row.items()} for row in geometry],
                  'ready_for_relocation': False}, indent=2))
