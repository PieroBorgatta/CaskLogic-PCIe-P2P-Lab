#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include "nvar_p2p.h"
int main(int argc,char **argv) {
  unsigned char *nv=malloc(0x60000),live[0x578],*copy=malloc(0x60000);NP_TARGET t;FILE *f;
  assert(argc==3);f=fopen(argv[1],"rb");assert(f);assert(fread(nv,1,0x60000,f)==0x60000);fclose(f);
  f=fopen(argv[2],"rb");assert(f);assert(fread(live,1,0x578,f)==0x578);fclose(f);
  assert(np_target(nv,0x60000,live,0x578,&t)==0);assert(t.offset==0x243f9 && t.sector==0x24000 && t.bank==0);
  printf("VALID target flash address 0x%x sector 0x%x\n",0x1000000+t.offset,0x1000000+t.sector);
  memcpy(copy,nv,0x60000);copy[0x30000+0x78+23]=0xf0;assert(np_target(copy,0x60000,live,0x578,&t)!=0);
  memcpy(copy,nv,0x60000);copy[0x78+23]=0xe0;assert(np_target(copy,0x60000,live,0x578,&t)!=0);
  memcpy(copy,nv,0x60000);copy[0x243f9]=1;assert(np_target(copy,0x60000,live,0x578,&t)!=0);
  memcpy(copy,nv,0x60000);copy[0x2ffb0]^=1;assert(np_target(copy,0x60000,live,0x578,&t)!=0);
  memcpy(copy,nv,0x60000);memset(copy+0x5bb1+6,0,3);assert(np_target(copy,0x60000,live,0x578,&t)!=0);
  memcpy(copy,nv,0x60000);copy[0x20]^=1;assert(np_target(copy,0x60000,live,0x578,&t)!=0);
  assert(np_target(nv,0x60000-1,live,0x578,&t)!=0);
  puts("PASS valid image and 7 corruption/ambiguity rejection checks");free(nv);free(copy);return 0;
}
