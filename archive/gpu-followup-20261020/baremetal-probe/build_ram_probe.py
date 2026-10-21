from pathlib import Path
import subprocess,shutil,re,hashlib,json,os
R=Path('/mnt/llm/riscrivo/runtime/reports/gpu-followup-20261020/baremetal-probe')
ROOT=R/'unpacked';D=R.parent/'p2p-driver';K='7.0.0-38-generic'
assert ROOT.is_dir() and (ROOT/'init').is_file()
assert subprocess.run(['systemctl','is-active','riscrivo-training.service'],capture_output=True,text=True).stdout.strip()=='inactive'
def put(src,dest):
    src=Path(src);dest=ROOT/dest.lstrip('/')
    dest.parent.mkdir(parents=True,exist_ok=True)
    assert dest.parent.resolve().is_relative_to(ROOT.resolve()),dest
    # Extracted initramfs applets can be hard links: never truncate in place.
    if dest.exists() or dest.is_symlink():dest.unlink()
    shutil.copy2(src.resolve(),dest)
def binary(src,dest=None):
    put(src,dest or src)
    s=subprocess.run(['ldd',str(src)],capture_output=True,text=True).stdout
    assert 'not found' not in s,s
    for line in s.splitlines():
        m=re.search(r'(/[^\s]+)',line)
        if m:
            lib=Path(m[1]).resolve()
            put(lib,'/usr/lib/x86_64-linux-gnu/'+Path(m[1]).name)
for exe in ['/usr/bin/setpci','/usr/bin/nvidia-smi','/usr/sbin/blkid']:
    binary(exe)
binary(str(R/'peer_vmm_word_native'),'/opt/probe/peer_word')
binary(str(D/'libcuda-experiment/libcuda.so.1'),'/usr/lib/x86_64-linux-gnu/libcuda.so.1')
binary('/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.1','/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.1')
binary('/usr/bin/busybox','/usr/bin/busybox')
binary('/usr/bin/sh','/usr/bin/sh')
for mod in ['nvme','vfat','thunderbolt','nls_cp437','nls_iso8859-1']:
    s=subprocess.check_output(['modprobe','--show-depends',mod],text=True)
    for line in s.splitlines():
        if line.startswith('insmod '):
            f=line.split()[1];put(f,f)
uvm=Path(subprocess.check_output(['modinfo','-n','nvidia_uvm'],text=True).strip())
put(uvm,'/opt/probe/nvidia_uvm.ko.zst')
put(D/'compiled-diagnostic/nvidia.ko','/opt/probe/nvidia-diagnostic.ko')
put(D/'compiled-coherent/nvidia.ko','/opt/probe/nvidia-coherent.ko')
put('/usr/lib/firmware/nvidia/595.99.02/gsp_ga10x.bin','/usr/lib/firmware/nvidia/595.99.02/gsp_ga10x.bin')
put(R/'init-probe.sh','/init');(ROOT/'init').chmod(0o755)
for name in ['proc','sys','dev','tmp','mnt/esp','run']: (ROOT/name).mkdir(parents=True,exist_ok=True)
subprocess.check_call(['depmod','-b',str(ROOT),K])
subprocess.check_call(['chroot',str(ROOT),'/bin/sh','-n','/init'])
loader=subprocess.run(['chroot',str(ROOT),'/lib64/ld-linux-x86-64.so.2','--list','/opt/probe/peer_word'],capture_output=True,text=True)
assert loader.returncode==0 and 'not found' not in loader.stdout+loader.stderr,loader.stdout+loader.stderr
applets=subprocess.check_output(['chroot',str(ROOT),'/bin/busybox','--list'],text=True).splitlines()
assert all(x in applets for x in ['timeout','reboot','mknod','awk','mount'])
for exe in ['/usr/bin/nvidia-smi','/usr/bin/setpci','/usr/sbin/blkid']:
    p=subprocess.run(['chroot',str(ROOT),exe,'--help'],capture_output=True,text=True)
    assert 'error while loading shared libraries' not in p.stderr,p.stderr
with (R/'probe-initrd.img').open('wb') as out:
    find=subprocess.Popen(['find','.','-print0'],cwd=ROOT,stdout=subprocess.PIPE)
    cpio=subprocess.Popen(['cpio','--null','-o','--format=newc','--quiet'],cwd=ROOT,stdin=find.stdout,stdout=subprocess.PIPE);find.stdout.close()
    gzip=subprocess.Popen(['gzip','-1'],stdin=cpio.stdout,stdout=out);cpio.stdout.close()
    assert gzip.wait()==0 and cpio.wait()==0 and find.wait()==0
put_manifest={'kernel':K,'initrd_bytes':(R/'probe-initrd.img').stat().st_size,'initrd_sha256':hashlib.sha256((R/'probe-initrd.img').read_bytes()).hexdigest(),'kernel_sha256':hashlib.sha256(Path('/boot/vmlinuz-'+K).read_bytes()).hexdigest(),'device_access':'physical GPUs, IOMMU disabled by temporary kernel command line','disks':'only known ESP mounted for result log; XCP and VM filesystems never mounted','automatic_return':'180-second watchdog and normal end both reboot; EFI BootNext consumed'}
(R/'build-manifest.json').write_text(json.dumps(put_manifest,indent=2));print(json.dumps(put_manifest,indent=2))
