"""Fixture CPU: nessun comando reale, nessun percorso del server usato."""
import gzip,hashlib,importlib.util,json,stat,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
P=Path(__file__).with_name('install_native_probe.py')
spec=importlib.util.spec_from_file_location('installer_fixture',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
BASE='BootCurrent: 0000\nBootOrder: 0000,0001\nBoot0000* XCP-ng original0\nBoot0001* UEFI OS original1\n'
def member(name,data,mode=stat.S_IFREG|0o644):
 name=name.encode()+b'\0';fields=[1,mode,0,0,1,0,len(data),0,0,0,0,len(name),0]
 h=b'070701'+b''.join(('%08x'%x).encode() for x in fields)
 return h+name+b'\0'*((-110-len(name))%4)+data+b'\0'*((-len(data))%4)
INIT=b'CaskLogic-TCSS-next-20261021 EFI/CaskLogicTcssNext timeout 60 /opt/probe/peer_word sleep 180 RM64KBBAR1Mappings=0\n'
class Tests(unittest.TestCase):
 def test_boot_refusals(self):
  self.assertEqual(m.first_free(m.parse_boot(BASE)),'0002')
  for bad in [BASE+'BootNext: 0002\n',BASE.replace('BootCurrent: 0000','BootCurrent: 0002'),BASE.replace('BootOrder: 0000,0001','BootOrder: 0002,0000,0001'),BASE+'Boot0000* duplicate\n',BASE.replace('Boot0001* UEFI OS original1\n','')]:
   with self.subTest(bad=bad),self.assertRaises(RuntimeError):m.parse_boot(bad)
 def test_create_only_identity(self):
  original=m.parse_boot(BASE);line='Boot0002* '+m.LABEL+'\tHD(4,GPT,'+m.PARTUUID+',x)/File('+m.LOADER+')'+''.join(c+'.' for c in m.ARGS)
  entries=dict(original,**{'0002':line});m.verify_new_entry(entries,original,'0002')
  for bad in [dict(entries,**{'0002':line.replace(m.PARTUUID,'bad')}),dict(entries,**{'0002':line.replace(m.LABEL,'other')}),dict(entries,**{'0002':line.replace(m.LOADER,'bad')}),dict(entries,**{'0002':line[:line.index('File(')+len('File('+m.LOADER+')')]}),dict(entries,**{'0000':'changed'}),dict(entries,**{'0004':'unexpected'}),dict(entries,**{'0002':line+' i.o.m.m.u.=.o.n.'}),dict(entries,**{'0002':line.replace('i.n.t.e.l._.i.o.m.m.u.=.o.f.f. ','')})]:
   with self.subTest(bad=bad),self.assertRaises(RuntimeError):m.verify_new_entry(bad,original,'0002')
 def test_payload_stream_fail_closed(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'x.gz';expected={'init':hashlib.sha256(INIT).hexdigest()}
   valid=member('init',INIT)+member('TRAILER!!!',b'')
   for bad,reason in [(valid,'pass'),(member('init',INIT)+member('init',INIT)+member('TRAILER!!!',b''),'duplicate'),(member('init',INIT,stat.S_IFLNK|0o777)+member('TRAILER!!!',b''),'symlink'),(member('init',INIT+b'x')+member('TRAILER!!!',b''),'hash'),(member('TRAILER!!!',b''),'missing'),(valid+b'other','trailing'),(valid[:-20],'short')]:
    p.write_bytes(gzip.compress(bad))
    if reason=='pass':self.assertEqual(m.stream_payloads(p,expected)['payload_files'],expected)
    else:
     with self.subTest(reason=reason),self.assertRaises((RuntimeError,EOFError,ValueError)):m.stream_payloads(p,expected)
 def test_atomic_and_copy_refusals(self):
  with tempfile.TemporaryDirectory() as tmp:
   d=Path(tmp);src=d/'src';src.write_bytes(b'abc');m.copy_verified(src,d/'dst',m.sha(src));m.atomic_json(d/'state',{'stage':'staged'});self.assertEqual(json.loads((d/'state').read_text())['stage'],'staged')
   with self.assertRaises(RuntimeError):m.copy_verified(src,d/'dst',m.sha(src))
   (d/'state.tmp').write_bytes(b'preserve')
   with self.assertRaises(FileExistsError):m.atomic_json(d/'state',{'stage':'armed'})
   self.assertEqual(json.loads((d/'state').read_text())['stage'],'staged')
 def run_flow(self,scenario):
  with tempfile.TemporaryDirectory() as tmp:
   r=Path(tmp);src=r/'pkg';src.mkdir();esp=r/'esp';(esp/'EFI').mkdir(parents=True);dst=esp/'EFI/CaskLogicTcssNext';state=r/'state';backup=r/'backup';baseline=r/'baseline';baseline.write_text('{}')
   for n in m.PACKAGE_NAMES:(src/n).write_bytes((n+' content').encode())
   files={n:m.sha(src/n) for n in ['probe-kernel.efi','probe-initrd.img','IDENTITY.txt']};metadata={n:m.sha(src/n) for n in ['files.json','build-manifest.json']}
   package={'files':files,'metadata_sha256':metadata,'stream':{'payload_files':{},'members':5}}
   b={'source':str(baseline),'sha256':m.sha(baseline),'baseline':{'original_files':{'fake':{'sha256':'abc'}}}}
   ccfg={k:v[1] for k,v in m.CCFG.items()};boot=[BASE];commands=[];running=[False]
   def command(args):
    commands.append(args)
    if args==['efibootmgr','-v']:return boot[0]
    if args[0]=='efibootmgr' and '--create-only' in args:
     entry=args[args.index('--bootnum')+1]
     boot[0]+='Boot'+entry+'* '+m.LABEL+'\tHD(4,GPT,'+m.PARTUUID+',x)/File('+m.LOADER+')'+m.ARGS+'\n'
     if scenario=='create_bad_order':boot[0]=boot[0].replace('BootOrder: 0000,0001','BootOrder: 0002,0000,0001')
     return ''
    if args[0]=='efibootmgr' and '--bootnext' in args:boot[0]='BootNext: '+args[-1]+'\n'+boot[0];return ''
    if args[:2]==['xe','vm-param-get']:return 'running' if running[0] else 'halted'
    if args[:2]==['xe','vm-list']:return ''
    raise AssertionError('Unexpected external command '+repr(args))
   patches={'R':r,'SRC':src,'ESP':esp,'DST':dst,'STATE':state,'BACKUP':backup}
   with patch.multiple(m,**patches),patch.object(m,'host_preflight',return_value=(b,ccfg)),patch.object(m,'verify_package',return_value=package),patch.object(m,'verify_baseline',return_value=b),patch.object(m,'read_ccfg',return_value=ccfg),patch.object(m,'partition_location',return_value=('/dev/fake','4')),patch.object(m,'run',side_effect=command),patch.object(m.os,'sync'),patch('builtins.print'):
    if scenario=='readonly':
     before=set(r.rglob('*'))
     with patch.object(sys,'argv',['fixture']):m.main()
     self.assertEqual(before,set(r.rglob('*')));self.assertEqual(commands,[['efibootmgr','-v']]);return
    with patch.object(sys,'argv',['fixture','--stage']):
     if scenario=='create_bad_order':
      with self.assertRaises(RuntimeError):m.main()
      self.assertEqual(json.loads(state.read_text())['stage'],'entry_create_pending');self.assertNotIn('BootNext:',boot[0]);return
     m.main()
    self.assertEqual(json.loads(state.read_text())['stage'],'staged');self.assertEqual({x.name for x in dst.iterdir()},m.PACKAGE_NAMES);self.assertNotIn('BootNext:',boot[0])
    if scenario=='stage':return
    running[0]=scenario=='running_refusal'
    with patch.object(sys,'argv',['fixture','--arm']):
     if running[0]:
      with self.assertRaises(RuntimeError):m.main()
      self.assertEqual(json.loads(state.read_text())['stage'],'staged');self.assertFalse(any('--bootnext' in c for c in commands))
     else:
      m.main();self.assertEqual(json.loads(state.read_text())['stage'],'armed');self.assertEqual(sum('--bootnext' in c for c in commands),1)
    self.assertFalse(any('reboot' in x for c in commands for x in c))
 def test_default_has_no_mutations(self):self.run_flow('readonly')
 def test_stage_does_not_arm(self):self.run_flow('stage')
 def test_arm_refuses_running_Docker(self):self.run_flow('running_refusal')
 def test_arm_only_sets_BootNext(self):self.run_flow('arm')
 def test_create_bad_order_preserves_partial(self):self.run_flow('create_bad_order')
if __name__=='__main__':unittest.main()
