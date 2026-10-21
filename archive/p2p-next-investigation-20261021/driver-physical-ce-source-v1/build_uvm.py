#!/usr/bin/env python3
"""Clona la build verificata e compila solo UVM; nessuna installazione o GPU."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,time

HERE=Path(__file__).resolve().parent
ROOT=Path('/mnt/llm/riscrivo/runtime/reports/p2p-next-investigation-20261021')
BASE=ROOT.parent/'p2p-tcss-bit-tests-20261021/driver-instrumented-build-01'
OUTPUT=ROOT/'driver-physical-ce-build-01'
RM_SHA='ab41b0a38e7ab92c0d1468b33c456c5c5c57501c67dfe5a666f49aed9fb6b1b5'
UVM_SHA='9b993671ef066c9d3e58fd52b0d70228861769a2e3dcf304bc3d80bca089c4d0'
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()
def run(args):return subprocess.check_output(args,text=True)
def safe_relative(value):
    p=Path(value)
    assert not p.is_absolute() and '..' not in p.parts and str(p) not in ('','.')
    return p

def main():
    assert os.geteuid()==0 and run(['hostname']).strip()=='gpu-vm'
    assert HERE==ROOT/'driver-physical-ce'
    assert subprocess.run(['systemctl','is-active','riscrivo-training.service'],capture_output=True,text=True).stdout.strip()=='inactive'
    assert not run(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader']).strip()
    assert not OUTPUT.exists() and shutil.disk_usage(ROOT).free>3*1024**3
    c=json.loads((HERE/'build-contract.json').read_text())
    assert c['status']=='reviewed_for_build' and c['builder_sha256']==sha(__file__)
    baseline=json.loads((BASE/'build-manifest.json').read_text())
    assert baseline['status']=='built_not_installed' and baseline['build_returncode']==0
    source=Path(baseline['source_root'])
    assert source==BASE/'source/NVIDIA-open-gpu-kernel-modules-19f3b34'
    assert sha(BASE/'modules/nvidia.ko')==RM_SHA and sha(BASE/'modules/nvidia-uvm.ko')==UVM_SHA
    for n,h in baseline['instrumented_verified'].items():assert sha(source/n)==h,n
    for target,v in c['overlay'].items():
        target=safe_relative(target);local=HERE/safe_relative(v['source'])
        assert str(target).startswith('kernel-open/nvidia-uvm/')
        assert local.is_file() and not local.is_symlink() and sha(local)==v['after']
        if v['before'] is None:assert not (source/target).exists()
        else:assert (source/target).is_file() and not (source/target).is_symlink() and sha(source/target)==v['before']
    for name,digest in c['evidence'].items():assert sha(HERE/safe_relative(name))==digest,name
    OUTPUT.mkdir();tree=OUTPUT/'source'
    evidence={'status':'preparing','started_epoch':time.time(),'contract_sha256':sha(HERE/'build-contract.json'),
              'builder_sha256':sha(__file__),'baseline_manifest_sha256':sha(BASE/'build-manifest.json'),
              'source_root':str(tree),'overlay':c['overlay'],'hardware_operations':False,'installed':False,
              'baseline_rm_sha256':RM_SHA,'baseline_uvm_sha256':UVM_SHA}
    try:
        shutil.copytree(source,tree,symlinks=True)
        for target,v in c['overlay'].items():
            dst=tree/target
            if v['before'] is not None:assert sha(dst)==v['before']
            dst.parent.mkdir(parents=True,exist_ok=True)
            if dst.exists():dst.unlink()
            shutil.copyfile(HERE/v['source'],dst);assert sha(dst)==v['after']
        changed=set(c['overlay'])
        for n,h in baseline['instrumented_verified'].items():
            if n not in changed:assert sha(tree/n)==h,n
        exported=[x for x in (tree/'kernel-open/Module.symvers').read_text().splitlines(True)
                  if len(x.split())>=3 and Path(x.split()[2]).name=='nvidia']
        assert exported
        symvers=OUTPUT/'nvidia-only.symvers';symvers.write_text(''.join(exported))
        command=['nice','-n','10','make','-C',str(tree/'kernel-open'),'-j2','NV_VERBOSE=1',
                 'KERNEL_UNAME=7.0.0-38-generic','NV_KERNEL_MODULES=nvidia-uvm',
                 'KBUILD_EXTRA_SYMBOLS='+str(symvers),'modules']
        evidence.update(status='building',command=command,rm_exports_sha256=sha(symvers),rm_export_count=len(exported))
        (OUTPUT/'build-manifest.json').write_text(json.dumps(evidence,indent=2)+'\n')
        with (OUTPUT/'build.log').open('w') as log:
            result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
        evidence.update(build_returncode=result.returncode,build_log_sha256=sha(OUTPUT/'build.log'))
        assert result.returncode==0,'Compilazione fallita: vedere build.log'
        modules=OUTPUT/'modules';modules.mkdir()
        shutil.copy2(BASE/'modules/nvidia.ko',modules/'nvidia.ko')
        shutil.copy2(tree/'kernel-open/nvidia-uvm.ko',modules/'nvidia-uvm.ko')
        assert sha(modules/'nvidia.ko')==RM_SHA
        evidence['modules']={}
        for n in ['nvidia.ko','nvidia-uvm.ko']:
            f=modules/n;info=run(['modinfo',str(f)])
            assert '595.99.02' in info and '7.0.0-38-generic SMP' in info
            if n=='nvidia-uvm.ko':assert 'uvm_cask_physical_ce:' in info and sha(f)!=UVM_SHA
            evidence['modules'][n]={'sha256':sha(f),'size':f.stat().st_size,'modinfo':info}
        for target,v in c['overlay'].items():assert sha(tree/target)==v['after']
        evidence.update(status='built_not_installed')
        print(json.dumps({'status':evidence['status'],'output':str(OUTPUT),
                          'uvm_sha256':evidence['modules']['nvidia-uvm.ko']['sha256']}))
    except Exception as exc:
        evidence.update(status='failed',error=str(exc));raise
    finally:
        evidence['finished_epoch']=time.time()
        (OUTPUT/'build-manifest.json').write_text(json.dumps(evidence,indent=2)+'\n')

if __name__=='__main__':main()
