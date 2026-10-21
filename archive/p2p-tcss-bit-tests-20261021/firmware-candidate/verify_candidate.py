#!/usr/bin/env python3
"""Confronto locale completo; non effettua scritture hardware."""
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
def sha(b):
    return hashlib.sha256(b).hexdigest()
def inventory(root):
    return {str(p.relative_to(root)): p for p in root.rglob('*') if p.is_file()}

a = (OUT / 'SPI-reconstructed-NV-P2P-enabled.baseline.bin').read_bytes()
b = (OUT / 'SPI-CCFG25-27.EXPERIMENTAL-NOT-FLASH-READY.bin').read_bytes()
assert len(a) == len(b) == 0x2000000
expected = json.loads((OUT / 'patch-manifest.json').read_text())
assert sha(a) == expected['baseline']['sha256']
ia = inventory(OUT / 'baseline-extracted')
ib = inventory(OUT / 'candidate-extracted')
assert ia.keys() == ib.keys()
changes = []
for key in sorted(ia):
    x, y = ia[key].read_bytes(), ib[key].read_bytes()
    if x != y:
        assert len(x) == len(y), key
        changes.append({'path':key,'bytes':len(x),'changed_bytes':sum(m!=n for m,n in zip(x,y)),'before_sha256':sha(x),'after_sha256':sha(y)})
ffs_rel = 'regions/region-bios/volume-0/file-3417f275-4cf1-42d8-a0c3-b3f60779df4d/section1/volume-3417f275-4cf1-42d8-a0c3-b3f60779df4d/file-80a845ac-210f-43b0-995b-477be41ab4e8'
pe_rel = ffs_rel + '/section1/section0.pe'
assert len(changes) == 9
assert len([r for r in changes if r['path'].endswith('.pe')]) == 1
assert ia[pe_rel].read_bytes()[0x20304] == 0xfe
assert ib[pe_rel].read_bytes() == (OUT / 'SiInitFsp-clear-CCFG25-27.NONFLASHABLE.pe').read_bytes()
assert next(r for r in changes if r['path'] == pe_rel)['changed_bytes'] == 1
expected_container_paths = {
    'flash.fd','regions/region-bios.fd',
    'regions/region-bios/volume-0/file-3417f275-4cf1-42d8-a0c3-b3f60779df4d/file.obj',
    'regions/region-bios/volume-0/file-3417f275-4cf1-42d8-a0c3-b3f60779df4d/section1.fv',
    'regions/region-bios/volume-0/file-3417f275-4cf1-42d8-a0c3-b3f60779df4d/section1/volume-3417f275-4cf1-42d8-a0c3-b3f60779df4d.fv',
    str(Path(ffs_rel).parent / 'filesystem.ffs'),
    ffs_rel+'/file.obj',ffs_rel+'/section1.compressed',pe_rel,
}
assert {r['path'] for r in changes} == expected_container_paths
fa, fb = ia[ffs_rel+'/file.obj'].read_bytes(), ib[ffs_rel+'/file.obj'].read_bytes()
assert a.count(fa) == 1 and a.find(fa) == 0x1b02b60
assert b.count(fb) == 1 and b.find(fb) == 0x1b02b60
assert len(fa) == len(fb) == 154845 and fa[:24] == fb[:24]
diffs = [i for i,(x,y) in enumerate(zip(a,b)) if x != y]
assert len(diffs) == 72228
assert all(0x1b02b60 <= i < 0x1b02b60+len(fa) for i in diffs)
start, end = diffs[0] & ~4095, (diffs[-1]+4096) & ~4095
assert (start,end) == (0x1b16000,0x1b29000)
assert a[:start] == b[:start] and a[end:] == b[end:]
(OUT / 'SPI-01B16000-00013000.ORIGINAL.bin').write_bytes(a[start:end])
(OUT / 'SPI-01B16000-00013000.CANDIDATE-NOT-FLASH-READY.bin').write_bytes(b[start:end])
result = {
    'status':'LOCAL_REPACK_AND_SEMANTIC_COMPARISON_PASSED_NOT_BOOT_OR_FLASH_VALIDATED',
    'candidate_sha256':sha(b),'baseline_sha256':sha(a),'spi_bytes':len(a),
    'extracted_objects_before':len(ia),'extracted_objects_after':len(ib),
    'missing':[],'added':[],'changed_objects':changes,
    'single_changed_leaf':pe_rel,'semantic_byte_count':1,
    'physical_byte_count':len(diffs),'physical_first':hex(diffs[0]),'physical_last_inclusive':hex(diffs[-1]),
    'all_physical_changes_inside_original_target_ffs':True,
    'ffs_offset_unchanged':True,'ffs_size_unchanged':True,'ffs_header_exact':True,
    'all_bytes_outside_target_ffs_exact':True,'all_other_extracted_objects_exact':True,
    'descriptor_ME_TBT_payload_NVRAM_SMBIOS_and_other_regions_exact_to_baseline':True,
    'minimal_aligned_region':{'alignment':4096,'spi_start':hex(start),'spi_end_exclusive':hex(end),'bytes':end-start,'sectors':(end-start)//4096,'original_sha256':sha(a[start:end]),'candidate_sha256':sha(b[start:end]),'per_sector_changes':[{'spi_offset':hex(i),'bytes_changed':sum(x!=y for x,y in zip(a[i:i+4096],b[i:i+4096]))} for i in range(start,end,4096)]},
    'next_gate':'Confrontare dump SPI live aggiornati e stato BootGuard. Autorizzazione utente acquisita; verifica tecnica nativa in attesa, nessuna conferma di avviabilita o effetto P2P.',
}
(OUT / 'repack-verification.json').write_text(json.dumps(result,indent=2)+'\n')
expected['repack_verification']={'file':'repack-verification.json','candidate_sha256':sha(b),'physical_changes_inside_only_target_ffs':True,'semantic_bytes_changed':1,'minimal_spi_region_start':hex(start),'minimal_spi_region_length':hex(end-start),'flash_ready':False}
expected['target']['hypothesis']='Clear CCFG bit25,26,27 durante inizializzazione precedente alle operazioni D8 e 3E24; semantica bit e presenza lock attivo su ADL-P non dimostrate.'
(OUT / 'patch-manifest.json').write_text(json.dumps(expected,indent=2)+'\n')
print(json.dumps({'objects_checked':len(ia),'semantic_bytes_changed':1,'all_physical_changes_only_target_ffs':True,'minimal_aligned_region':result['minimal_aligned_region']},indent=2))
