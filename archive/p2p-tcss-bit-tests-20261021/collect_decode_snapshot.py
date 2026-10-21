from pathlib import Path
import hashlib,json,os,platform,subprocess,time
R=Path('/root/riscrivo-p2p-tcss-bit-tests-20261021')
O=R/'decode-snapshot-20261021'
assert os.geteuid()==0 and platform.node()=='hypervisor-host'
assert not O.exists();O.mkdir()
data={'epoch':time.time(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'pci':{},'hardware_writes':False,'context':'Xen dom0 read-only; native allocation must revalidate before any relocation'}
for d in sorted(Path('/sys/bus/pci/devices').iterdir()):
 v={'vendor':(d/'vendor').read_text().strip(),'device':(d/'device').read_text().strip(),'class':(d/'class').read_text().strip(),'resources':(d/'resource').read_text(),'physical_path':str(d.resolve())}
 if (d/'driver').exists():v['driver']=str((d/'driver').resolve())
 if d.name in ['0000:00:00.0','0000:00:01.0','0000:00:07.0','0000:00:07.2','0000:04:00.0','0000:05:00.0','0000:01:00.0','0000:06:00.0']:
  fd=os.open(str(d/'config'),os.O_RDONLY)
  try:b=os.pread(fd,4096,0)
  finally:os.close(fd)
  v['config_hex']=b.hex();v['config_bytes']=len(b)
 data['pci'][d.name]=v
for n,p in [('iomem','/proc/iomem'),('cmdline','/proc/cmdline')]:
 (O/(n+'.txt')).write_text(Path(p).read_text())
for n,args in [('xen-dmesg',['xl','dmesg']),('pci-vvnn',['lspci','-vvnn'])]:
 z=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True)
 (O/(n+'.txt')).write_text(z.stdout);(O/(n+'.stderr.txt')).write_text(z.stderr);data[n+'_rc']=z.returncode
m=Path('/sys/firmware/memmap');data['firmware_memmap']={}
if m.exists():
 for d in m.iterdir():data['firmware_memmap'][d.name]={n:(d/n).read_text().strip() for n in ['start','end','type']}
(O/'snapshot.json').write_text(json.dumps(data,indent=2)+'\n')
print(json.dumps({'output':str(O),'devices':len(data['pci']),'hardware_writes':False}))
