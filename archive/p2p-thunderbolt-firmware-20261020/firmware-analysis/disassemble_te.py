from pathlib import Path
import sys,struct,json,hashlib
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'python-libs'))
from capstone import Cs,CS_ARCH_X86,CS_MODE_32,CS_MODE_64
root=Path('runtime/reports/gpu-followup-20261020/driver-reference/bios-1.26/extracted')
manifest=[]
for p in root.rglob('*.te'):
 u=list(p.parent.glob('*.ui'));name=u[0].read_bytes().decode('utf-16le',errors='ignore').strip('\x00') if u else p.parent.name
 if name not in ['SiInitPreMemFsp','SiliconPolicyPeiPostMem','PlatformInitPreMem','FspInitPreMem','FspWrapperPeim','FspsWrapperPeim','PlatformInitAdvancedPostMem']:continue
 b=p.read_bytes();sig,machine,ns,subsystem,stripped,entry,basecode,imagebase=struct.unpack_from('<HHBBHIIQ',b)
 assert sig==0x5a56
 delta=stripped-40
 md=Cs(CS_ARCH_X86,CS_MODE_32 if machine==0x14c else CS_MODE_64);md.skipdata=True
 lines=[];secs=[]
 for n in range(ns):
  off=40+n*40;rawname,vsize,va,rawsize,rawptr,relptr,lineptr,nr,nl,flags=struct.unpack_from('<8sIIIIIIHHI',b,off)
  sn=rawname.decode(errors='ignore').strip('\x00');secs.append({'name':sn,'rva':hex(va),'raw_offset':hex(rawptr-delta),'rawsize':rawsize})
  if not flags&0x20:continue
  data=b[rawptr-delta:rawptr-delta+rawsize]
  for i in md.disasm(data,va):lines.append(f'{i.address:08x} [file {i.address-va+rawptr-delta:08x}] {i.bytes.hex():<30} {i.mnemonic} {i.op_str}')
 (HERE/(name+'-TE-disassembly.txt')).write_text('\n'.join(lines))
 manifest.append({'name':name,'source':str(p.resolve()),'sha256':hashlib.sha256(b).hexdigest(),'stripped':stripped,'imagebase':hex(imagebase),'machine':hex(machine),'sections':secs})
 print(name,len(lines),secs)
(HERE/'te-manifest.json').write_text(json.dumps(manifest,indent=2))
