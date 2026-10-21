"""Confronto locale dei dump nativi e del candidato; nessun accesso hardware."""
from pathlib import Path
import hashlib
import json

R = Path(__file__).resolve().parent
F = R / 'firmware-candidate'
N = R / 'native-read-results'
start, size = 0x1B16000, 0x13000
ffs_start, ffs_size = 0x1B02B60, 154845

def sha(b):
    return hashlib.sha256(b).hexdigest()

a = (N / 'spi-current-a.bin').read_bytes()
b = (N / 'spi-current-b.bin').read_bytes()
assert len(a) == 33554432 and a == b, 'I due dump correnti non coincidono'
original = (F / 'SPI-01B16000-00013000.ORIGINAL.bin').read_bytes()
patched = (F / 'SPI-01B16000-00013000.CANDIDATE-NOT-FLASH-READY.bin').read_bytes()
assert len(original) == len(patched) == size
assert sha(original) == 'b60186e3126a68a06d2fa18cf6b1ac0bb357cab48c7ee06f48ce54a8d77f31e5'
assert sha(patched) == '8c9cd7ecaf9ea50689bd70891eab0e36d66b8b36bf45e55b42f7e1c032ce574e'
assert a[start:start+size] == original, 'Intervallo corrente diverso dalla baseline'
assert sha(a[ffs_start:ffs_start+ffs_size]) == 'fcde1a912de75df1a95fdd9553d141712dd49e7bcc89dbb603839535d4a64abf'
candidate = a[:start] + patched + a[start+size:]
assert len(candidate) == len(a)
assert candidate[:start] == a[:start] and candidate[start+size:] == a[start+size:]
assert candidate[:0x1000000] == a[:0x1000000]
assert candidate[0x1000000:0x1060000] == a[0x1000000:0x1060000]
report = {'fresh_dumps_identical': True, 'fresh_spi_sha256': sha(a),
          'target_ffs_matches': True, 'region_start': hex(start), 'region_bytes': size,
          'region_original_sha256': sha(original), 'region_candidate_sha256': sha(patched),
          'candidate_whole_image_sha256': sha(candidate),
          'outside_target_region_unchanged': True, 'nv_me_descriptor_preserved': True,
          'purpose': 'Analisi locale. La verifica strutturale non equivale a prova di avvio.',
          'hardware_writes': False}
(F / 'SPI-current-with-TCSS-candidate.ANALYSIS-ONLY.bin').write_bytes(candidate)
(R / 'fresh-spi-verification.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
