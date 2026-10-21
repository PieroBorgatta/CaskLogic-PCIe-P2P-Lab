/* Strict, read-only parser for the two MS-01 AHWSA 1.26 NVAR banks.
 * Layout and flags independently checked against LongSoft UEFITool nvram.h.
 * No hardware access. Returns an offset only after matching live SaSetup. */
typedef unsigned char NP_U8;
typedef unsigned int NP_U32;
typedef struct { NP_U32 offset, sector, bank, entry; } NP_TARGET;
static NP_U32 np16(const NP_U8 *p) { return p[0] | ((NP_U32)p[1]<<8); }
static NP_U32 np24(const NP_U8 *p) { return np16(p) | ((NP_U32)p[2]<<16); }
static NP_U32 np32(const NP_U8 *p) { return np24(p) | ((NP_U32)p[3]<<24); }
static int npeq(const NP_U8 *a,const NP_U8 *b,NP_U32 n) {
  NP_U32 i;for(i=0;i<n;i++) if(a[i]!=b[i]) return 0;return 1;
}
static int np_target(const NP_U8 *nv,NP_U32 n,const NP_U8 *live,NP_U32 live_n,NP_TARGET *out) {
  static const NP_U8 fileguid[16]={0xa3,0xb9,0xf5,0xce,0x6d,0x47,0x7f,0x49,0x9f,0xdc,0xe9,0x81,0x43,0xe0,0x42,0x2c};
  static const NP_U8 saguid[16]={0x8c,0xe2,0xc5,0x72,0x83,0x77,0xa1,0x43,0x87,0x67,0xfa,0xd7,0x3f,0xcc,0xaf,0xa4};
  static const NP_U8 name[8]={'S','a','S','e','t','u','p',0};
  NP_U32 bank,active=0,active_bank=0,i,entry=0,found=0;
  if(n!=0x60000 || live_n!=0x578 || live[0x3e3]!=0 || live[0x279]!=1) return 1;
  for(bank=0;bank<0x60000;bank+=0x30000) {
    const NP_U8 *f=nv+bank+0x78;NP_U32 sum=0;
    if(np32(nv+bank+0x28)!=0x4856465f || np32(nv+bank+0x20)!=0x30000 || np32(nv+bank+0x24)!=0) return 2;
    if(np16(nv+bank+0x30)!=0x48) return 3;
    for(i=0;i<0x48;i+=2)sum+=np16(nv+bank+i);
    if((sum&0xffff)!=0) return 4;
    if(!npeq(f,fileguid,16)||f[17]!=0xaa||f[18]!=1||f[19]!=0||np24(f+20)!=0x2ff88) return 5;
    sum=0;for(i=0;i<24;i++)if(i!=17&&i!=23)sum+=f[i];if((sum&255)!=0)return 6;
    if(f[23]==0xf0) {active++;active_bank=bank;}
    else if(f[23]!=0xe0) return 7;
  }
  if(active!=1) return 8;
  bank=active_bank;i=bank+0x90;
  while(i+10<bank+0x30000 && npeq(nv+i,(const NP_U8 *)"NVAR",4)) {
    NP_U32 len=np16(nv+i+4);NP_U8 flags=nv[i+9];
    if(len<10 || len>bank+0x30000-i) return 9;
    if(flags==0x82 && len>=19 && npeq(nv+i+11,name,8)) {
      NP_U32 idx=nv[i+10],g=bank+0x30000-16*(idx+1);
      if(idx>127 || !npeq(nv+g,saguid,16))return 10;
      if(len!=0x58b) return 11;
      entry=i;found++;
    }
    i+=len;
  }
  if(found!=1)return 12;
  for(i=0;i<128;i++) {
    NP_U32 next, len;
    if(entry<bank+0x90 || entry+10>=bank+0x30000 || !npeq(nv+entry,(const NP_U8 *)"NVAR",4))return 13;
    len=np16(nv+entry+4);next=np24(nv+entry+6);
    if(entry+len>bank+0x30000)return 14;
    if(next==0xffffff) {
      if(nv[entry+9]!=0x88||len!=0x582||!npeq(nv+entry+10,live,0x578))return 15;
      out->offset=entry+10+0x3e3;out->sector=out->offset&~4095U;out->bank=bank;out->entry=entry;
      if(out->sector+4096>bank+0x30000 || nv[out->offset]!=0) return 16;
      return 0;
    }
    if(next<10 || next>bank+0x30000-entry)return 17;
    entry+=next;
  }
  return 18;
}
