from pathlib import Path
import subprocess,os,json,time
root=Path('/audit');src=root/'sources'
def run(args,cwd=None):
 print('BUILD',args,flush=True)
 subprocess.run(args,cwd=cwd,check=True)
run(['cmake','-S',str(src/'nvbandwidth'),'-B',str(root/'build/nvbandwidth'),'-DCMAKE_CUDA_ARCHITECTURES=86;89','-DFETCHCONTENT_SOURCE_DIR_ARGPARSE='+str(src/'argparse'),'-DCMAKE_EXE_LINKER_FLAGS=-L/usr/local/cuda/lib64/stubs'])
run(['cmake','--build',str(root/'build/nvbandwidth'),'-j','4'])
run(['make','-j','4','COMPUTE=','NVCCFLAGS=-gencode=arch=compute_86,code=sm_86 -gencode=arch=compute_89,code=sm_89'],src/'gpu-burn')
sdk=root/'nccl-sdk';sdk.mkdir(exist_ok=True)
(sdk/'include').symlink_to('/usr/local/lib/python3.12/dist-packages/nvidia/nccl/include')
(sdk/'lib').mkdir(exist_ok=True)
for name in ['libnccl.so','libnccl.so.2']:
 (sdk/'lib'/name).symlink_to('/usr/local/lib/python3.12/dist-packages/nvidia/nccl/lib/libnccl.so.2')
run(['make','-j','4','NCCL_HOME='+str(sdk),'NVCC_GENCODE=-gencode=arch=compute_86,code=sm_86 -gencode=arch=compute_89,code=sm_89'],src/'nccl-tests')
(root/'build.complete').write_text(str(time.time()))
print('BUILD_COMPLETE',flush=True)
