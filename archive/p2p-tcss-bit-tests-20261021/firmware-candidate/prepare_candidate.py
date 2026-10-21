#!/usr/bin/env python3
"""Preparazione esclusivamente locale; non contiene accessi hardware o flash."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
OLD = ROOT / 'runtime/reports/gpu-followup-20261020'
MODULES = ROOT / 'runtime/reports/p2p-thunderbolt-firmware-20261020/modules'

def sha(data):
    return hashlib.sha256(data).hexdigest()

def read_checked(path, expected):
    data = path.read_bytes()
    assert sha(data) == expected, str(path)
    return data

spi_path = OLD / 'uefi-p2p/spi-backup-a.bin'
spi = read_checked(spi_path, 'ad8ab9c0f7c2d09273bf4fe2f3b12be6cb203495f384f18a86e5d023ae5cfe9b')
assert len(spi) == 0x2000000
nv_path = OLD / 'firmware-mod/NV-before.bin'
nv = read_checked(nv_path, 'd0c9e6340a7da447f2ef3e6076fa1cf7de4c3ffd9ed136148a2106882a672c4a')
assert len(nv) == 0x60000
sector_old = read_checked(OLD / 'firmware-mod/P2P-sector-original.bin', 'ca1aded0358abe9ef109dd95da35aecba8f05b532e293e517fef806f2f4b18e2')
sector_new = read_checked(OLD / 'firmware-mod/P2P-sector-after.bin', 'ba646b781d38136787b8f19db448872860befc8223e386a9e56dc9a5b4b2f68b')
assert sector_old == nv[0x24000:0x25000]
assert [(i, a, b) for i, (a, b) in enumerate(zip(sector_old, sector_new)) if a != b] == [(0x3f9, 0, 1)]
baseline = bytearray(spi)
baseline[0x1000000:0x1060000] = nv
baseline[0x1024000:0x1025000] = sector_new
assert baseline[:0x1000000] == spi[:0x1000000]
assert baseline[0x1060000:] == spi[0x1060000:]
baseline_path = OUT / 'SPI-reconstructed-NV-P2P-enabled.baseline.bin'
baseline_path.write_bytes(baseline)

pe_path = MODULES / 'SiInitFsp.pe'
pe = read_checked(pe_path, 'de17fb9ae71e0cb04fa39102ed1895284640befb719b44ea45b498e29b0c928f')
before = bytes.fromhex('B988CFFFFE')
after = bytes.fromhex('B988CFFFF0')
assert pe.count(before) == 1 and pe[0x20300:0x20305] == before
assert (0xfeffcf88 ^ 0xf0ffcf88) == 0x0e000000
assert (0xf0ffcf88 & ~0xfeffcf88) == 0
patched = bytearray(pe)
patched[0x20304] = 0xf0
assert [(i, a, b) for i, (a, b) in enumerate(zip(pe, patched)) if a != b] == [(0x20304, 0xfe, 0xf0)]
patched_path = OUT / 'SiInitFsp-clear-CCFG25-27.NONFLASHABLE.pe'
patched_path.write_bytes(patched)
index = json.loads((MODULES / 'index.json').read_text())
source_pe = ROOT / next(x['source'] for x in index if x['name'] == 'SiInitFsp')
ffs_path = source_pe.parent.parent / 'file.obj'
ffs = read_checked(ffs_path, 'fcde1a912de75df1a95fdd9553d141712dd49e7bcc89dbb603839535d4a64abf')
assert spi.count(ffs) == 1 and spi.find(ffs) == 0x1b02b60
patch_text = '# Candidato sperimentale: cambia solo la maschera CCFG D7, nessuna scrittura hardware.\n80A845AC-210F-43B0-995B-477BE41AB4E8 10 P:B988CFFFFE:B988CFFFF0\n'
(OUT / 'SiInitFsp-CCFG-mask.patch.txt').write_text(patch_text)
manifest = {
    'status': 'AWAITING_NATIVE_SECURITY_AND_FRESH_DUMP',
    'hardware_writes_by_this_script': False,
    'spi_source': {'path': str(spi_path), 'sha256': sha(spi), 'bytes': len(spi)},
    'baseline': {
        'path': str(baseline_path), 'sha256': sha(baseline),
        'description': 'Ricostruzione da backup SPI reale, NV-before successivo e readback settore P2P gia scritto; NON dump live corrente.',
        'nv_overlay_spi_start': '0x01000000', 'nv_overlay_bytes': len(nv),
        'nv_source_sha256': sha(nv), 'nv_changes_vs_older_spi': sum(a != b for a,b in zip(spi[0x1000000:0x1060000], nv)),
        'verified_sector_spi_start': '0x01024000', 'verified_sector_sha256': sha(sector_new),
        'sa_setup_p2p_spi_offset': '0x010243F9', 'sa_setup_p2p_value': 1,
        'difference_count_vs_spi': sum(a != b for a,b in zip(spi,baseline)),
        'outside_nv_region_exact': True,
    },
    'target': {'ffs_guid':'80a845ac-210f-43b0-995b-477be41ab4e8', 'ffs_spi_offset':'0x01B02B60', 'ffs_original_bytes':len(ffs), 'ffs_original_sha256':sha(ffs), 'pe_original_sha256':sha(pe), 'pe_patched_sha256':sha(patched), 'pe_bytes':len(pe), 'pe_instruction_offset':'0x20300','pe_changed_offset':'0x20304','before':'FE','after':'F0','semantic_bytes_changed':1,'instruction_before':before.hex(),'instruction_after':after.hex(),'and_mask_before':'0xFEFFCF88','and_mask_after':'0xF0FFCF88','or_mask_unchanged':'0x00001077','cleared_mask':'0x0E000000','scope':'Tutte le porte D7 presenti nel ciclo firmware; non limitato a D7:F0.', 'hypothesis':'Clear CCFG bit25,26,27 durante inizializzazione precedente ai lock; semantica dei bit su ADL-P non documentata con certezza.'},
    'preserved': ['Nessuna modifica PE oltre un byte di immediato', 'Nessuna modifica firmware ME/FD/TBT payload/seriali nello script', 'P2P PEG precedentemente attivato mantenuto nella baseline'],
    'limitations': ['Il PE isolato non e una immagine flashabile.', 'Baseline NV storica ricostruita: occorre preservare NV live nella eventuale applicazione.', 'BootGuard enforcement non dimostrato da analisi statica: presenza ACM e riferimenti KM/BPM non basta.', 'Non modificati manifest firmati o protezioni per aggirarli.', 'Avviabilita e vantaggio P2P non verificati; recupero indipendente non confermato, rischio di mancato avvio da registrare.'],
}
(OUT / 'patch-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'baseline_sha256':sha(baseline),'patched_pe_sha256':sha(patched),'baseline_nv_bytes_changed':manifest['baseline']['difference_count_vs_spi'],'semantic_bytes_changed':1},indent=2))
