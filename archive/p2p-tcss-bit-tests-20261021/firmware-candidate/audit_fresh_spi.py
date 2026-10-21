#!/usr/bin/env python3
"""Revisione indipendente dei dump nativi e del candidato: solo file locali."""
import hashlib
import json
import re
import struct
import uuid
from pathlib import Path

OUT = Path(__file__).resolve().parent
RESULTS = OUT.parent / 'native-read-results'
def sha(x): return hashlib.sha256(x).hexdigest()
def inventory(p): return {str(q.relative_to(p)):q for q in p.rglob('*') if q.is_file()}

a = (RESULTS/'spi-current-a.bin').read_bytes()
b = (RESULTS/'spi-current-b.bin').read_bytes()
c = (OUT/'SPI-current-with-TCSS-candidate.ANALYSIS-ONLY.bin').read_bytes()
assert len(a) == len(b) == len(c) == 0x2000000 and a == b
assert sha(a) == 'cfe6c07a4f2113928e13198ab2b8adc52924893aa0c239982c2213feb53c5124'
assert sha(a[0x1b02b60:0x1b2883d]) == 'fcde1a912de75df1a95fdd9553d141712dd49e7bcc89dbb603839535d4a64abf'
assert a[0x1b16000:0x1b29000] == (OUT/'SPI-01B16000-00013000.ORIGINAL.bin').read_bytes()
assert c[0x1b16000:0x1b29000] == (OUT/'SPI-01B16000-00013000.CANDIDATE-NOT-FLASH-READY.bin').read_bytes()
assert a[:0x1b16000] == c[:0x1b16000] and a[0x1b29000:] == c[0x1b29000:]
fit_pointer = struct.unpack_from('<Q',a,len(a)-64)[0]
assert fit_pointer == 0xffe90980
fit = fit_pointer - (0x100000000-len(a))
assert a[fit:fit+8] == b'_FIT_   '
entries = []
for n in range(int.from_bytes(a[fit+8:fit+11],'little')):
    p=fit+n*16
    entries.append({'index':n,'physical_address':hex(struct.unpack_from('<Q',a,p)[0]),'type':a[p+14]&127,'bytes':a[p:p+16].hex()})
assert entries[6]['type']==11 and entries[6]['physical_address']=='0xfff3fb00'
assert entries[7]['type']==12 and entries[7]['physical_address']=='0xfff3f080'
manifests=[]
for name,offset,expected_guid,expected_size in [
    ('Boot Policy Manifest',0x1f3f068,'c30fff4a-10c6-4c0f-a454-fd319baf6ce6',0xa18),
    ('Key Manifest',0x1f3fae8,'7c9a98f8-2b2b-4027-8f16-f7d277d58025',0x418),
]:
    header=a[offset:offset+24]
    guid=str(uuid.UUID(bytes_le=header[:16]));size=int.from_bytes(header[20:23],'little')
    assert guid==expected_guid and size==expected_size and header[18]==1
    payload=a[offset+24:offset+size]
    assert payload==b'\xff'*len(payload)
    manifests.append({'name':name,'ffs_guid':guid,'ffs_offset':hex(offset),'ffs_bytes':size,'body_offset':hex(offset+24),'body_bytes':len(payload),'body_all_ff':True,'body_sha256':sha(payload)})
ami=[]
for off in [0x1f92c60,0x1fd2c60]:
    d=a[off:off+0x6c]
    assert d[28:]==b'\xff'*80
    ami.append({'ffs_offset':hex(off),'range_and_hash_data_bytes':80,'range_and_hash_data_all_ff':True})
native=(RESULTS/'native-security.txt').read_text(encoding='utf-16')
values={k:int(v,16) for k,v in re.findall(r'^([a-zA-Z0-9_]+)=0x([0-9A-Fa-f]+)',native,re.M)}
assert values['msr_13a_raw']==0x1000000000
assert values['cpuid_signature']==0x906a3 and 'phase=complete' in native
native_fields={k:hex(values[k]) for k in ['cpuid_signature','cpuid_1_ecx','msr_13a_raw','txt_didvid_fed30110','acm_policy_status_fed30378','txt_bootstatus_fed300a0','acm_status_fed30328']}
ia=inventory(OUT/'fresh-baseline-extracted');ic=inventory(OUT/'fresh-candidate-extracted')
assert ia and ia.keys()==ic.keys()
changed=[]
for key in sorted(ia):
    x,y=ia[key].read_bytes(),ic[key].read_bytes()
    if x!=y:
        assert len(x)==len(y)
        changed.append({'path':key,'bytes':len(x),'differing_bytes':sum(q!=r for q,r in zip(x,y))})
assert len(changed)==9
leaves=[x for x in changed if x['path'].endswith('.pe')]
assert len(leaves)==1 and 'file-80a845ac-210f-43b0-995b-477be41ab4e8' in leaves[0]['path'] and leaves[0]['differing_bytes']==1
assert ic[leaves[0]['path']].read_bytes()==(OUT/'SiInitFsp-clear-CCFG25-27.NONFLASHABLE.pe').read_bytes()
assert not any(a.find(s)>=0 for s in [b'__KEYM__',b'__ACBP__',b'__IBBS__'])
result={
 'scope':'Independent local file audit; no SSH, hardware writes or flash',
 'two_native_dumps_identical':True,'fresh_spi_sha256':sha(a),'candidate_sha256':sha(c),
 'target_ffs_identical_to_reviewed_original':True,'target_19_sectors_identical_to_reviewed_original':True,
 'outside_19_sectors_exact_to_fresh_spi':True,'fresh_nv_ME_descriptor_and_other_regions_preserved':True,
 'extracted_objects_each':len(ia),'extracted_missing_or_added':[],'changed_objects':changed,
 'only_changed_leaf':'SiInitFsp.pe, offset 0x20304, FE -> F0',
 'fit_pointer':hex(fit_pointer),'fit_entries':entries,'manifest_placeholder_files':manifests,
 'manifest_signatures_absent_in_entire_spi':['__KEYM__','__ACBP__','__IBBS__'],
 'ami_protected_ranges_files':ami,'native_observations':native_fields,
 'native_msr_only_set_bit':36,'native_msr_bit32':0,'native_msr_bit6':0,
 'interpretation':'FIT points to all-FF KM/BPM placeholder bodies, not populated manifest headers; native verified-boot indication is zero. These are evidence about this boot and image, not proof the modified firmware will boot.',
 'unresolved':['Meaning of MSR13A bit36 and absent capability bit32 on this ADL-P platform is being independently reviewed.','P2P bit semantics and patch effect remain unverified.','Independent recovery capability not confirmed.'],
}
(OUT/'fresh-independent-audit.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:result[k] for k in ['fresh_spi_sha256','candidate_sha256','extracted_objects_each','two_native_dumps_identical','target_ffs_identical_to_reviewed_original','target_19_sectors_identical_to_reviewed_original','outside_19_sectors_exact_to_fresh_spi','manifest_placeholder_files']},indent=2))
