/* CPU-only fixtures of the exact DMAR parser: no MMIO or kernel calls. */
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <errno.h>
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef uint64_t u64;
#include "dmar_parse.inc"
static unsigned int tests;
static void need(bool condition,const char *reason)
{ tests++;if(!condition){fprintf(stderr,"failure %u %s\n",tests,reason);exit(1);} }
static void put16(u8 *p,u16 v){p[0]=v;p[1]=v>>8;}
static void put32(u8 *p,u32 v){put16(p,(u16)v);put16(p+2,(u16)(v>>16));}
static void put64(u8 *p,u64 v){put32(p,(u32)v);put32(p+4,(u32)(v>>32));}
static void checksum(u8 *p,unsigned int n)
{ unsigned int i;u8 sum=0;p[9]=0;for(i=0;i<n;i++)sum=(u8)(sum+p[i]);p[9]=(u8)(0-sum); }
static void init(u8 *p,unsigned int n)
{memset(p,0,1024);memcpy(p,"DMAR",4);put32(p+4,n);p[8]=1;p[36]=47;}
static void drhd(u8 *p,u64 base,u16 segment)
{put16(p,0);put16(p+2,16);p[4]=1;put16(p+6,segment);put64(p+8,base);}
int main(void)
{
 u8 p[1024],copy[1024];struct snapshot_dmar out;unsigned int i;
 init(p,64);drhd(p+48,0xfed91000,0);checksum(p,64);
 need(parse_dmar(p,64,&out)==0&&out.count==1&&out.units[0].base==0xfed91000,"known DRHD");
 for(i=0;i<64;i++){memcpy(copy,p,sizeof(copy));copy[i]^=0x80;need(parse_dmar(copy,64,&out)<0,"corrupted byte rejected");}
 for(i=0;i<64;i++)need(parse_dmar(p,i,&out)<0,"truncated actual buffer rejected");
 need(parse_dmar(NULL,64,&out)<0,"null table");need(parse_dmar(p,64,NULL)<0,"null output");
 init(p,80);drhd(p+48,0xfed91000,0);drhd(p+64,0xfed92000,0);checksum(p,80);
 need(parse_dmar(p,80,&out)==0&&out.count==2,"two distinct units");
 put64(p+72,0xfed91000);checksum(p,80);need(parse_dmar(p,80,&out)<0,"duplicate segment/base rejected");
 put16(p+70,1);checksum(p,80);need(parse_dmar(p,80,&out)==0,"different segment remains separate and is not sampled by module");
 init(p,72);drhd(p+48,0xfed91000,0);put16(p+50,24);p[64]=1;p[65]=8;p[70]=7;p[71]=0;checksum(p,72);
 need(parse_dmar(p,72,&out)==0&&out.units[0].scopes==1,"well-formed PCI scope");
 for(i=0;i<16;i++){if(i==8)continue;copy[0]=0;memcpy(copy,p,sizeof(copy));copy[65]=(u8)i;checksum(copy,72);need(parse_dmar(copy,72,&out)<0,"malformed scope length rejected");}
 init(p,68);drhd(p+48,0xfed91000,0);put16(p+64,0x1234);put16(p+66,4);checksum(p,68);
 need(parse_dmar(p,68,&out)==0,"unknown structurally bounded subtable skipped");
 put16(p+66,0);checksum(p,68);need(parse_dmar(p,68,&out)<0,"zero subtable length rejected");
 put16(p+66,5);checksum(p,68);need(parse_dmar(p,68,&out)<0,"overrun subtable rejected");
 init(p,64);drhd(p+48,0,0);checksum(p,64);need(parse_dmar(p,64,&out)<0,"zero base rejected");
 put64(p+56,0xfed91001);checksum(p,64);need(parse_dmar(p,64,&out)<0,"unaligned base rejected");
 put64(p+56,~(u64)0);checksum(p,64);need(parse_dmar(p,64,&out)<0,"all-ones base rejected");
 put64(p+56,0xfed91000);p[36]=64;checksum(p,64);need(parse_dmar(p,64,&out)<0,"invalid host address width rejected");
 init(p,48);checksum(p,48);need(parse_dmar(p,48,&out)<0,"no DRHD rejected");
 init(p,48+33*16);for(i=0;i<33;i++)drhd(p+48+i*16,0xfed00000+(u64)i*4096,0);checksum(p,48+33*16);
 need(parse_dmar(p,48+33*16,&out)==-E2BIG,"bounded unit count");
 printf("{\"status\":\"PASS\",\"cases\":%u,\"hardware_access\":false}\n",tests);
 return 0;
}
