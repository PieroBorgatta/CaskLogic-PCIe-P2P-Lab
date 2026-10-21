from pathlib import Path
import json,struct,uuid,zlib,hashlib,sys
p=Path(sys.argv[1]);b=p.read_bytes();name_size,data_size=struct.unpack_from('<II',b)
assert name_size==16 and data_size==0x578,(name_size,data_size)
o=8;name=b[o:o+name_size].decode('utf-16le').rstrip('\0');o+=name_size
guid=str(uuid.UUID(bytes_le=b[o:o+16]));o+=16
attrs=struct.unpack_from('<I',b,o)[0];o+=4;data=b[o:o+data_size];o+=data_size
assert name=='SaSetup' and guid=='72c5e28c-7783-43a1-8767-fad73fccafa4'
assert len(b)==o+4
assert zlib.crc32(b[:o])&0xffffffff==struct.unpack_from('<I',b,o)[0],'backup CRC mismatch'
assert data[0x3e3] in [0,1]
r={'name':name,'guid':guid,'attributes':attrs,'bytes':data_size,'backup_sha256':hashlib.sha256(b).hexdigest(),'data_sha256':hashlib.sha256(data).hexdigest(),'p2p_gpu_slot_offset':'0x3E3','p2p_gpu_slot_value':data[0x3e3],'gpu_slot_enabled':data[0x279],'other_cpu_port_p2p':[data[0x3e2],data[0x3e4]],'crc_verified':True}
p.with_suffix('.verified.json').write_text(json.dumps(r,indent=2));p.with_suffix('.data.bin').write_bytes(data);print(json.dumps(r,indent=2))
