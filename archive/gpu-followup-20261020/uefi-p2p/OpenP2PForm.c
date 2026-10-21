/* Local diagnostic application. No SetVariable, flash, or IFR modification.
 * ABI/structures: UEFI 2.10 HII Database and FormBrowser2 protocols.
 * Targets only the verified MS-01 BIOS 1.26 form and question. */
#include <efi.h>
#include <efilib.h>

typedef VOID *HII_HANDLE;
typedef struct HII_DB HII_DB;
typedef EFI_STATUS (EFIAPI *LIST_PACKAGES)(HII_DB *, UINT8, EFI_GUID *, UINTN *, HII_HANDLE *);
typedef EFI_STATUS (EFIAPI *EXPORT_PACKAGES)(HII_DB *, HII_HANDLE, UINTN *, VOID *);
struct HII_DB { VOID *New; VOID *Remove; VOID *Update; LIST_PACKAGES List; EXPORT_PACKAGES Export; };
typedef struct FORM_BROWSER FORM_BROWSER;
typedef EFI_STATUS (EFIAPI *SEND_FORM)(FORM_BROWSER *, HII_HANDLE *, UINTN, EFI_GUID *, UINT16, VOID *, UINTN *);
struct FORM_BROWSER { SEND_FORM SendForm; VOID *Callback; };
static EFI_GUID DbGuid = {0xef9fc172,0xa1b2,0x4693,{0xb3,0x27,0x6d,0x32,0xfc,0x41,0x60,0x42}};
static EFI_GUID BrowserGuid = {0xb9d4c360,0xbcfb,0x4f9b,{0x92,0x98,0x53,0xc1,0x36,0x98,0x22,0x58}};
static EFI_GUID FormGuid = {0x7b59104a,0xc00d,0x4158,{0x87,0xff,0xf0,0x4d,0x63,0x96,0xa9,0x15}};
static EFI_GUID SaGuid = {0x72c5e28c,0x7783,0x43a1,{0x87,0x67,0xfa,0xd7,0x3f,0xcc,0xaf,0xa4}};
static EFI_FILE_HANDLE LogFile;
static UINT16 u16(UINT8 *b) { return b[0] | ((UINT16)b[1]<<8); }
static UINT32 u24(UINT8 *b) { return b[0] | ((UINT32)b[1]<<8) | ((UINT32)b[2]<<16); }
static VOID logline(CHAR16 *s) {
  UINTN n=StrLen(s)*sizeof(CHAR16);
  Print(L"%s",s);
  if(LogFile) { LogFile->Write(LogFile,&n,s); LogFile->Flush(LogFile); }
}
static BOOLEAN contains_target(UINT8 *b, UINTN n) {
  UINTN p=20, end, i, len; UINT16 form=0; BOOLEAN own=FALSE;
  if(n<24) return FALSE;
  while(p+4<=n) {
    UINT32 plen=u24(b+p); UINT8 type=b[p+3];
    if(plen<4 || plen>n-p) return FALSE;
    end=p+plen;
    if(type==2) for(i=p+4;i+2<=end;i+=len) {
      len=b[i+1]&0x7f;
      if(len<2 || len>end-i) return FALSE;
      if(b[i]==0x0e && len>=23) own=CompareMem(b+i+2,&FormGuid,16)==0;
      if(b[i]==1 && len>=6) form=u16(b+i+2);
      if(own && form==0x27c4 && b[i]==5 && len>=17 &&
         u16(b+i+6)==0xad0 && u16(b+i+8)==4 && u16(b+i+10)==0x3e3)
        return TRUE;
    }
    p=end;
  }
  return FALSE;
}
EFI_STATUS efi_main(EFI_HANDLE image, EFI_SYSTEM_TABLE *st) {
  HII_DB *db=NULL; FORM_BROWSER *browser=NULL; EFI_STATUS s; EFI_LOADED_IMAGE *li=NULL;
  EFI_FILE_HANDLE root=NULL; HII_HANDLE *handles=NULL, target=NULL;
  UINTN bytes=0,i,count=0,sz=0x578,action=0; UINT8 sa[0x578]; UINT32 attrs=0;
  InitializeLib(image,st);
  BS->SetWatchdogTimer(0,0,0,NULL);
  if(!EFI_ERROR(BS->HandleProtocol(image,&LoadedImageProtocol,(VOID **)&li))) {
    root=LibOpenRoot(li->DeviceHandle);
    if(root) root->Open(root,&LogFile,L"\\EFI\\CaskLogicP2P\\native-form-log.txt",EFI_FILE_MODE_READ|EFI_FILE_MODE_WRITE|EFI_FILE_MODE_CREATE,0);
  }
  logline(L"CaskLogic: apertura pagina P2P nativa; nessuna modifica automatica.\r\n");
  s=RT->GetVariable(L"SaSetup",&SaGuid,&attrs,&sz,sa);
  if(EFI_ERROR(s)||sz!=0x578||attrs!=3||sa[0x279]!=1||sa[0x3e3]>1) { logline(L"STOP: configurazione inattesa.\r\n"); goto done; }
  s=BS->LocateProtocol(&DbGuid,NULL,(VOID **)&db); if(EFI_ERROR(s)) goto done;
  s=BS->LocateProtocol(&BrowserGuid,NULL,(VOID **)&browser); if(EFI_ERROR(s)) goto done;
  s=db->List(db,2,NULL,&bytes,NULL); if(s!=EFI_BUFFER_TOO_SMALL||bytes>65536) goto done;
  handles=AllocatePool(bytes); if(!handles) { s=EFI_OUT_OF_RESOURCES; goto done; }
  s=db->List(db,2,NULL,&bytes,handles); if(EFI_ERROR(s)) goto done;
  for(i=0;i<bytes/sizeof(HII_HANDLE);i++) {
    UINTN n=0; UINT8 *b;
    s=db->Export(db,handles[i],&n,NULL); if(s!=EFI_BUFFER_TOO_SMALL||n>8388608) continue;
    b=AllocatePool(n); if(!b) continue;
    s=db->Export(db,handles[i],&n,b);
    if(!EFI_ERROR(s)&&contains_target(b,n)) {target=handles[i];count++;}
    FreePool(b);
  }
  if(count!=1) {logline(L"STOP: pagina P2P univoca non trovata.\r\n");s=EFI_NOT_FOUND;goto done;}
  logline(L"Pagina e voce verificate. Apertura PCI Express Root Port2 (27C4).\r\n");
  s=browser->SendForm(browser,&target,1,&FormGuid,0x27c4,NULL,&action);
  logline(L"Ritorno dal browser BIOS.\r\n");
done:
  {CHAR16 line[128]; SPrint(line,sizeof(line),L"Stato finale: %r\r\n",s);logline(line);}
  if(handles) FreePool(handles);
  if(LogFile) LogFile->Close(LogFile);
  if(root) root->Close(root);
  return s;
}
