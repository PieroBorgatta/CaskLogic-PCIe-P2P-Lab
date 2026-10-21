from pathlib import Path
import hashlib,json,ctypes
p=Path(__file__).parent/'libcuda-experiment/libcuda.so.1'
b=bytearray(p.read_bytes());original=hashlib.sha256(b).hexdigest()
assert original=='192d4eedb1b39f0568f2b5423d35227d13b32b9025599e1968a9081982da207d',original
patches=[(0x2a8566,'48 39 d0 74 44',0x2a85ac),(0x2a8661,'48 39 d0 74 45',0x2a86a8),(0x2cfed3,'48 39 d0 74 41',0x2cff16),(0x43ad7c,'48 39 d0 74 6a',0x43ade8)]
for offset,signature,target in patches:
 assert b[offset-3:offset+2]==bytes.fromhex(signature)
 assert offset+2+b[offset+1]==target
 assert bytes(b[target:target+3]) in [bytes.fromhex(x) for x in ['41 8b 83','41 8b 87','41 8b 80','41 8b 84','8b 87 10','8b 83 10','41 8b 94']],b[target:target+8].hex()
 b[offset]=0xeb
p.write_bytes(b)
meta={'original_sha256':original,'patched_sha256':hashlib.sha256(b).hexdigest(),'changes':[{'offset':hex(a),'before':'74','after':'eb','target':hex(c)} for a,_,c in patches],'scope':'isolated experimental copy; system library untouched','basis':'aikitoria mixed architecture patch, ported to 595.99.02 with disassembly'}
(p.parent/'patch.json').write_text(json.dumps(meta,indent=2));print(json.dumps(meta))
