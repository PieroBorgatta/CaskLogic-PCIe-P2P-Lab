#!/usr/bin/env python3
"""Prepara e verifica file locali soltanto; nessun accesso hardware o remoto."""
import hashlib
import json
import subprocess
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
PREV = OUT.parent / 'firmware-candidate'
REF = ROOT / 'runtime/reports/gpu-followup-20261020/driver-reference'
FRESH = OUT.parent / 'native-read-results/spi-current-a.bin'
def sha(b): return hashlib.sha256(b).hexdigest()
def crc(b): return zlib.crc32(b) & 0xffffffff
def inventory(root): return {str(p.relative_to(root)): p for p in root.rglob('*') if p.is_file()}
def run_logged(args, path):
    with path.open('wb') as out:
        subprocess.run([str(x) for x in args], stdout=out, stderr=subprocess.STDOUT, check=True)

original = FRESH.read_bytes()
assert sha(original) == 'cfe6c07a4f2113928e13198ab2b8adc52924893aa0c239982c2213feb53c5124'
assert original == (OUT.parent / 'native-read-results/spi-current-b.bin').read_bytes()
current_path = PREV / 'SPI-current-with-TCSS-candidate.ANALYSIS-ONLY.bin'
current = current_path.read_bytes()
assert sha(current) == '1ddc33f1e8164e1e0ee888886ebc6b709ba2c266daf69685d27b3e5a3219bdf2'
assert current[:0x1b16000] == original[:0x1b16000] and current[0x1b29000:] == original[0x1b29000:]
assert current[0x1b16000:0x1b29000] == (PREV / 'SPI-01B16000-00013000.CANDIDATE-NOT-FLASH-READY.bin').read_bytes()

pe_rel = 'regions/region-bios/volume-0/file-3417f275-4cf1-42d8-a0c3-b3f60779df4d/section1/volume-3417f275-4cf1-42d8-a0c3-b3f60779df4d/file-80a845ac-210f-43b0-995b-477be41ab4e8/section1/section0.pe'
ffs_rel = str(Path(pe_rel).parent.parent)
orig_tree = PREV / 'fresh-baseline-extracted'
curr_tree = PREV / 'fresh-candidate-extracted'
orig_pe = (orig_tree / pe_rel).read_bytes()
curr_pe = (curr_tree / pe_rel).read_bytes()
assert sha(orig_pe) == 'de17fb9ae71e0cb04fa39102ed1895284640befb719b44ea45b498e29b0c928f'
assert [(i,a,b) for i,(a,b) in enumerate(zip(orig_pe,curr_pe)) if a!=b] == [(0x20304,0xfe,0xf0)]
pattern = bytes.fromhex('81E10000000481C188EF7FF0')
replacement = bytes.fromhex('81E10000000081C188EF7FF0')
assert curr_pe.count(pattern) == 1 and curr_pe[0xf62f:0xf63b] == pattern
expected_pe = bytearray(curr_pe); expected_pe[0xf634] = 0
assert [(i,a,b) for i,(a,b) in enumerate(zip(orig_pe,expected_pe)) if a!=b] == [(0xf634,4,0),(0x20304,0xfe,0xf0)]
patch_file = OUT / 'SiInitFsp-D1-bit26.patch.txt'
patch_file.write_text('# Unica modifica aggiuntiva al candidato D7 gia verificato; solo PE32 del GUID indicato.\n80A845AC-210F-43B0-995B-477BE41AB4E8 10 P:'+pattern.hex().upper()+':'+replacement.hex().upper()+' \n')
combined_path = OUT / 'SPI-D7-D1-combined.ANALYSIS-ONLY.bin'
run_logged([REF/'UEFIPatch-0.28.0/UEFIPatch', current_path, patch_file, '-o', combined_path], OUT/'UEFIPatch.log')
combined = combined_path.read_bytes()
assert len(original) == len(current) == len(combined) == 0x2000000
combo_tree = OUT / 'combined-extracted'
assert not combo_tree.exists(), 'Extraction destination must be new, refusing stale verification'
run_logged([REF/'uefi-tools/bin/uefi-firmware-parser', '-e', '-q', '-o', combo_tree, combined_path], OUT/'extraction.log')
ia,ic,ib = inventory(orig_tree),inventory(curr_tree),inventory(combo_tree)
assert ia and ia.keys() == ic.keys() == ib.keys()
allowed = {
    'flash.fd','regions/region-bios.fd',
    'regions/region-bios/volume-0/file-3417f275-4cf1-42d8-a0c3-b3f60779df4d/file.obj',
    'regions/region-bios/volume-0/file-3417f275-4cf1-42d8-a0c3-b3f60779df4d/section1.fv',
    'regions/region-bios/volume-0/file-3417f275-4cf1-42d8-a0c3-b3f60779df4d/section1/volume-3417f275-4cf1-42d8-a0c3-b3f60779df4d.fv',
    str(Path(ffs_rel).parent / 'filesystem.ffs'),
    ffs_rel+'/file.obj', ffs_rel+'/section1.compressed', pe_rel,
}
comparisons = {}
for name,tree in [('original_to_combined',ia),('current_D7_to_combined',ic)]:
    changes=[]
    for key in sorted(tree):
        a,b=tree[key].read_bytes(),ib[key].read_bytes()
        if a != b:
            assert len(a)==len(b), ('Object size changed',key,len(a),len(b))
            changes.append({'path':key,'bytes':len(a),'differing_bytes':sum(x!=y for x,y in zip(a,b)),'before_sha256':sha(a),'after_sha256':sha(b)})
    assert {x['path'] for x in changes} == allowed
    comparisons[name]=changes
assert ib[pe_rel].read_bytes() == expected_pe
ffs_off=0x1b02b60
ffs_orig=ia[ffs_rel+'/file.obj'].read_bytes()
ffs_curr=ic[ffs_rel+'/file.obj'].read_bytes()
ffs_comb=ib[ffs_rel+'/file.obj'].read_bytes()
assert len(ffs_orig)==len(ffs_curr)==len(ffs_comb)==154845
assert ffs_orig[:24] == ffs_curr[:24] == ffs_comb[:24]
for full,ffs in [(original,ffs_orig),(current,ffs_curr),(combined,ffs_comb)]:
    assert full.count(ffs)==1 and full.find(ffs)==ffs_off
assert original[:ffs_off] == current[:ffs_off] == combined[:ffs_off]
assert original[ffs_off+len(ffs_orig):] == current[ffs_off+len(ffs_orig):] == combined[ffs_off+len(ffs_orig):]
diffs_all=[i for i,(a,b) in enumerate(zip(original,combined)) if a!=b]
diffs_add=[i for i,(a,b) in enumerate(zip(current,combined)) if a!=b]
assert diffs_all and diffs_add
start=min(0x1b16000,diffs_all[0]&~4095,diffs_add[0]&~4095)
end=max(0x1b29000,(diffs_all[-1]+4096)&~4095,(diffs_add[-1]+4096)&~4095)
assert start <= 0x1b16000 and end >= 0x1b29000
assert original[:start] == current[:start] == combined[:start]
assert original[end:] == current[end:] == combined[end:]
profile={'region_start':start,'region_bytes':end-start}
for name,data in [('original',original),('current',current),('candidate',combined)]:
    block=data[start:end]
    (OUT/(name.upper()+'.bin')).write_bytes(block)
    profile[name+'_sha256']=sha(block)
    profile[name+'_crc32']=crc(block)
(OUT/'SiInitFsp-D7-D1-combined.NONFLASHABLE.pe').write_bytes(expected_pe)
(OUT/'flash-profile.json').write_text(json.dumps(profile,indent=2)+'\n')
(OUT/'TcssRegionProfile.h').write_text('/* Generated from verified local original/current/combined SPI blocks. */\n#define REGION_BYTES 0x%XU\n#define ORIGINAL_CRC32 0x%08XU\n#define CURRENT_CRC32 0x%08XU\n#define CANDIDATE_CRC32 0x%08XU\n#define REGION_LABEL "SPI %08X length %08X"\n' % (profile['region_bytes'],profile['original_crc32'],profile['current_crc32'],profile['candidate_crc32'],start,end-start))
result={
    'status':'LOCAL_COMBINED_REPACK_VALIDATED_NOT_BOOT_TESTED',
    'hardware_or_remote_operations':False,
    'full_images':{'fresh_original_sha256':sha(original),'current_D7_sha256':sha(current),'combined_sha256':sha(combined)},
    'pe_sha256':{'original':sha(orig_pe),'current':sha(curr_pe),'combined':sha(expected_pe)},
    'semantic_changes_vs_original':[{'offset':'0xF634','before':'04','after':'00'},{'offset':'0x20304','before':'FE','after':'F0'}],
    'semantic_changes_vs_current':[{'offset':'0xF634','before':'04','after':'00'}],
    'ffs':{'guid':'80a845ac-210f-43b0-995b-477be41ab4e8','offset':hex(ffs_off),'length':len(ffs_orig),'header_exact':True,'offset_and_length_unchanged':True},
    'all_other_modules_exact':True,'all_bytes_outside_target_ffs_exact':True,'objects_checked_each':len(ia),
    'comparisons':comparisons,
    'physical_changes':{'original_to_combined':{'count':len(diffs_all),'first':hex(diffs_all[0]),'last':hex(diffs_all[-1])},'current_to_combined':{'count':len(diffs_add),'first':hex(diffs_add[0]),'last':hex(diffs_add[-1])}},
    'range_includes_previous_19_sectors':True,'range_sectors':(end-start)//4096,'flash_profile':profile,
    'current_block_provenance':'Fresh native original cfe6... plus prior D7-only candidate 1ddc..., with original target FFS and prior patch independently verified. Operator must compare the entire expanded range to CURRENT.bin before writing; no new native read is claimed by this script.',
    'original_block_restores':'Unmodified SiInitFsp only; retains existing SaSetup P2P NV setting outside this range.',
    'limitations':['Boot and D1 hardware acceptance not yet tested.','D1 bit26 silicon semantics not proved by public D6 specification.','The conditional D1 family branch can also affect D1:F1 on applicable SKUs.'],
}
(OUT/'combined-verification.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'profile':profile,'objects':len(ia),'physical_changes':result['physical_changes']},indent=2))
