/* UEFI file-only preparation/checking. Intel vendor FPT performs hardware I/O.
 * Does not call SetVariable or access SPI registers. */
#include <efi.h>
#include <efilib.h>
#include "nvar_p2p.h"
#define PFX L"%homefilesystem%\\EFI\\CaskLogicP2P\\"
#define DIR L"\\EFI\\CaskLogicP2P\\"
static EFI_FILE_HANDLE root;
static EFI_STATUS load(CHAR16 *name,UINTN expected,UINT8 **out) {
  EFI_FILE_HANDLE f=NULL;EFI_FILE_INFO *info;EFI_STATUS s;UINTN n=expected;
  s=root->Open(root,&f,name,EFI_FILE_MODE_READ,0);if(EFI_ERROR(s))return s;
  info=LibFileInfo(f);if(!info||info->FileSize!=expected){if(info)FreePool(info);f->Close(f);return EFI_BAD_BUFFER_SIZE;}FreePool(info);
  *out=AllocatePool(n);if(!*out){f->Close(f);return EFI_OUT_OF_RESOURCES;}
  s=f->Read(f,&n,*out);f->Close(f);if(EFI_ERROR(s)||n!=expected){FreePool(*out);*out=NULL;return EFI_DEVICE_ERROR;}return EFI_SUCCESS;
}
static EFI_STATUS save(CHAR16 *name,VOID *data,UINTN bytes) {
  EFI_FILE_HANDLE f=NULL;EFI_STATUS s;UINTN n=bytes;
  s=root->Open(root,&f,name,EFI_FILE_MODE_READ|EFI_FILE_MODE_WRITE|EFI_FILE_MODE_CREATE,0);if(EFI_ERROR(s))return s;
  s=f->Write(f,&n,data);if(!EFI_ERROR(s)&&n==bytes)s=f->Flush(f);else s=EFI_DEVICE_ERROR;f->Close(f);return s;
}
static EFI_STATUS text(CHAR16 *name,CHAR16 *str){
  UINTN n=StrLen(str)*2;CHAR16 *buffer=AllocatePool(n+2);EFI_STATUS status;
  if(!buffer)return EFI_OUT_OF_RESOURCES;
  buffer[0]=0xfeff;CopyMem(buffer+1,str,n);
  status=save(name,buffer,n+2);FreePool(buffer);return status;
}
EFI_STATUS efi_main(EFI_HANDLE image,EFI_SYSTEM_TABLE *st) {
  EFI_LOADED_IMAGE *li=NULL;EFI_STATUS s;UINT8 *nv=NULL,*original=NULL,*expected=NULL,*actual=NULL;
  InitializeLib(image,st);BS->SetWatchdogTimer(0,0,0,NULL);
  s=BS->HandleProtocol(image,&LoadedImageProtocol,(VOID **)&li);if(EFI_ERROR(s))return s;
  root=LibOpenRoot(li->DeviceHandle);if(!root)return EFI_NOT_FOUND;
#ifdef POST_CHECK
#ifdef RESTORE_CHECK
  s=load(DIR L"P2P-sector-original.bin",4096,&expected);if(EFI_ERROR(s))goto done;
  s=load(DIR L"P2P-sector-restored.bin",4096,&actual);if(EFI_ERROR(s))goto done;
#else
  s=load(DIR L"P2P-sector.bin",4096,&expected);if(EFI_ERROR(s))goto done;
  s=load(DIR L"P2P-sector-after.bin",4096,&actual);if(EFI_ERROR(s))goto done;
#endif
  if(CompareMem(expected,actual,4096)!=0){s=EFI_CRC_ERROR;goto done;}
#ifdef RESTORE_CHECK
  s=text(DIR L"P2P-RESTORED.flag",L"Original sector verified byte-for-byte.\r\n");
#else
  s=text(DIR L"P2P-VERIFIED.flag",L"Patched sector verified byte-for-byte.\r\n");
#endif
#else
  {
    static EFI_GUID guid={0x72c5e28c,0x7783,0x43a1,{0x87,0x67,0xfa,0xd7,0x3f,0xcc,0xaf,0xa4}};
    UINT8 live[0x578],patched[4096];UINTN n=sizeof(live),i,diff=0;UINT32 attrs=0;NP_TARGET target;int code;CHAR16 script[2048],log[512];
    s=RT->GetVariable(L"SaSetup",&guid,&attrs,&n,live);if(EFI_ERROR(s)||attrs!=3||n!=sizeof(live)){s=EFI_COMPROMISED_DATA;goto done;}
    s=load(DIR L"NV-before.bin",0x60000,&nv);if(EFI_ERROR(s))goto done;
    code=np_target(nv,0x60000,live,sizeof(live),&target);
    if(code){SPrint(log,sizeof(log),L"STOP parser %d; nessuna patch autorizzata.\r\n",code);text(DIR L"NvPrepare-log.txt",log);Print(L"%s",log);s=EFI_COMPROMISED_DATA;goto done;}
    CopyMem(patched,nv+target.sector,4096);patched[target.offset-target.sector]=1;
    for(i=0;i<4096;i++)if(patched[i]!=nv[target.sector+i])diff++;
    if(diff!=1){s=EFI_COMPROMISED_DATA;goto done;}
    s=save(DIR L"P2P-sector-original.bin",nv+target.sector,4096);if(EFI_ERROR(s))goto done;
    s=save(DIR L"P2P-sector.bin",patched,4096);if(EFI_ERROR(s))goto done;
    s=load(DIR L"P2P-sector-original.bin",4096,&original);if(EFI_ERROR(s)||CompareMem(original,nv+target.sector,4096)!=0){s=EFI_CRC_ERROR;goto done;}
    s=load(DIR L"P2P-sector.bin",4096,&expected);if(EFI_ERROR(s)||CompareMem(expected,patched,4096)!=0){s=EFI_CRC_ERROR;goto done;}
    SPrint(script,sizeof(script),L"@echo off\r\n%sFpt.efi -f %sP2P-sector.bin -a 0x%08x -l 0x1000 > %sFpt-write-sector.txt\r\n%sFpt.efi -v %sP2P-sector.bin -a 0x%08x -l 0x1000 > %sFpt-verify-sector.txt\r\n%sFpt.efi -d %sP2P-sector-after.bin -a 0x%08x -l 0x1000 > %sFpt-read-sector-after.txt\r\n",PFX,PFX,0x1000000+target.sector,PFX,PFX,PFX,0x1000000+target.sector,PFX,PFX,PFX,0x1000000+target.sector,PFX);
    s=text(DIR L"FlashP2P.nsh",script);if(EFI_ERROR(s))goto done;
    SPrint(script,sizeof(script),L"@echo off\r\n%sFpt.efi -f %sP2P-sector-original.bin -a 0x%08x -l 0x1000 > %sFpt-restore-sector.txt\r\n%sFpt.efi -d %sP2P-sector-restored.bin -a 0x%08x -l 0x1000 > %sFpt-read-sector-restored.txt\r\n",PFX,PFX,0x1000000+target.sector,PFX,PFX,PFX,0x1000000+target.sector,PFX);
    s=text(DIR L"RestoreP2P.nsh",script);if(EFI_ERROR(s))goto done;
    SPrint(log,sizeof(log),L"SaSetup GUID e dati live verificati; banca attiva 0x%x; entry 0x%x; settore SPI 0x%x; byte SPI 0x%x; differenze dati: 1; valore: 0 -> 1.\r\n",target.bank,0x1000000+target.entry,0x1000000+target.sector,0x1000000+target.offset);
    s=text(DIR L"NvPrepare-log.txt",log);if(EFI_ERROR(s))goto done;Print(L"%s",log);
    s=text(DIR L"P2P-READY.flag",L"Fresh live NVAR, one active bank, exact SaSetup, one byte difference, files read back.\r\n");
  }
#endif
done:
  Print(L"CaskLogic NV: %r\r\n",s);
  if(nv)FreePool(nv);
  if(original)FreePool(original);
  if(expected)FreePool(expected);
  if(actual)FreePool(actual);
  root->Close(root);
  return s;
}
