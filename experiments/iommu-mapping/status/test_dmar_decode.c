#include <stdio.h>
#include <string.h>
#include <assert.h>
#include "dmar_decode.h"
static void sum(u8*p){unsigned int s=0;unsigned int i;p[9]=0;for(i=0;i<80;++i)s+=p[i];p[9]=(u8)(0-s);}
int main(void){u8 p[80]={0},q[80];struct cask_dmar_table d;memcpy(p,"DMAR",4);p[4]=80;p[50]=32;p[52]=1;p[56]=0;p[57]=0x10;p[58]=0xd9;p[59]=0xfe;sum(p);assert(!cask_decode_dmar(p,80,&d));assert(d.base==0xfed91000ULL && d.units==1);assert(cask_decode_dmar(p,79,&d));memcpy(q,p,80);q[9]++;assert(cask_decode_dmar(q,80,&d));memcpy(q,p,80);q[59]=0xfd;sum(q);assert(cask_decode_dmar(q,80,&d));memcpy(q,p,80);q[54]=1;sum(q);assert(cask_decode_dmar(q,80,&d));memcpy(q,p,80);q[50]=0;sum(q);assert(cask_decode_dmar(q,80,&d));memcpy(q,p,80);q[48]=1;sum(q);assert(cask_decode_dmar(q,80,&d));memcpy(q,p,80);q[52]=0;sum(q);assert(cask_decode_dmar(q,80,&d));memcpy(q,p,80);q[50]=31;sum(q);assert(cask_decode_dmar(q,80,&d));puts("PASS 9 DMAR parser identity/bounds/checksum cases");return 0;}
