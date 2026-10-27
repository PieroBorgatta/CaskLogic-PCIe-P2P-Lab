#ifndef CASK_DMAR_DECODE_H
#define CASK_DMAR_DECODE_H
#ifdef __KERNEL__
#include <linux/types.h>
#include <linux/errno.h>
#else
#include <stdint.h>
#include <stddef.h>
#include <errno.h>
typedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;typedef uint64_t u64;
#endif
struct cask_dmar_table {u8 flags;u16 segment;u64 base;unsigned int units;};
static inline u32 cask_le32(const u8*p){return (u32)p[0]|((u32)p[1]<<8)|((u32)p[2]<<16)|((u32)p[3]<<24);}
static inline int cask_decode_dmar(const u8*p,size_t n,struct cask_dmar_table*out){
 size_t pos;unsigned int sum=0;struct cask_dmar_table v={0};
 if(!p || !out || n!=80 || p[0]!='D' || p[1]!='M' || p[2]!='A' || p[3]!='R' || cask_le32(p+4)!=n)return -EINVAL;
 for(pos=0;pos<n;++pos)
  sum+=p[pos];
 if(sum&255)return -EINVAL;
 v.flags=p[37];pos=48;
 while(pos<n){
  unsigned int type,len;
  if(n-pos<4)return -EINVAL;
  type=p[pos]|((unsigned int)p[pos+1]<<8);len=p[pos+2]|((unsigned int)p[pos+3]<<8);
  if(len<4 || len>n-pos)return -EINVAL;
  if(type!=0 || len<16 || ++v.units!=1 || p[pos+4]!=1)return -EINVAL;
  v.segment=p[pos+6]|((u16)p[pos+7]<<8);
  v.base=(u64)cask_le32(p+pos+8)|((u64)cask_le32(p+pos+12)<<32);
  if(v.segment!=0 || v.base!=0xfed91000ULL)return -EINVAL;
  pos+=len;
 }
 if(pos!=n || v.units!=1)return -EINVAL;
 *out=v;return 0;
}
#endif
