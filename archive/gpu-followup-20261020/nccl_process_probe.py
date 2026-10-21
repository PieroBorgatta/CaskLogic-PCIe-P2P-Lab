import datetime,json,os,sys,time
from pathlib import Path
import torch
import torch.distributed as dist
import torch.multiprocessing as mp
def work(rank):
 torch.set_num_threads(2);torch.cuda.set_device(rank);os.environ['MASTER_ADDR']='127.0.0.1';os.environ['MASTER_PORT']='29679'
 dist.init_process_group('nccl',rank=rank,world_size=2,timeout=datetime.timedelta(seconds=25))
 print('INIT',rank,flush=True);x=torch.full((16*1024**2,),rank+1.,device=rank)
 dist.all_reduce(x);torch.cuda.synchronize();assert bool(torch.all(x==3));print('ALLREDUCE_OK',rank,flush=True)
 x.fill_(7 if rank==0 else -1);dist.broadcast(x,src=0);torch.cuda.synchronize();assert bool(torch.all(x==7));print('BROADCAST_OK',rank,flush=True)
 dist.destroy_process_group()
if __name__=='__main__':mp.spawn(work,nprocs=2,join=True)
