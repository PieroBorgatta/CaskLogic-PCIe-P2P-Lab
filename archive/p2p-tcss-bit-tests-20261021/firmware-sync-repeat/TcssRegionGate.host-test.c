/* Host-only memory-filesystem harness. No UEFI boot or hardware access.
 * Build PRE (default), POST_CHECK or RESTORE_CHECK. Tests actual file logic.
 * PRE invokes check_region_files directly; its native guard is never run here.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "TcssRegionGate.c"

typedef struct { char name[80]; UINT8 *data; UINTN size; int exists; } MemFile;
typedef struct { EFI_FILE_PROTOCOL protocol; MemFile *file; UINTN position; } Handle;
static MemFile files[12];
static Handle root_handle;
static EFI_BOOT_SERVICES services;
static EFI_LOADED_IMAGE loaded_image;
EFI_BOOT_SERVICES *BS = &services;
EFI_GUID gEfiLoadedImageProtocolGuid, gEfiFileInfoGuid;
static int fail_flag_flush, fail_delete, fail_read, fail_log_write;
static UINT8 reference_original[REGION_BYTES], reference_current[REGION_BYTES], reference_candidate[REGION_BYTES];

UINTN StrLen(CONST CHAR16 *s) { UINTN n = 0; while (s[n]) ++n; return n; }
UINTN Print(CONST CHAR16 *fmt, ...) { (void)fmt; return 0; }
UINTN UnicodeSPrint(CHAR16 *out, UINTN size, CONST CHAR16 *fmt, ...)
{ (void)fmt; if (size >= 4) { out[0] = 'O'; out[1] = 0; } return 1; }
VOID *AllocatePool(UINTN size) { return malloc(size); }
VOID FreePool(VOID *p) { free(p); }
VOID InitializeLib(EFI_HANDLE h, EFI_SYSTEM_TABLE *st) { (void)h; (void)st; }
EFI_FILE_HANDLE LibOpenRoot(EFI_HANDLE device) { (void)device; return &root_handle.protocol; }

static void ascii_name(CHAR16 *wide, char *name)
{
    UINTN i = 0, start = 0;
    while (wide[i]) { if (wide[i] == '\\') start = i + 1; ++i; }
    for (i = 0; wide[start + i] && i < 79; ++i) name[i] = (char)wide[start + i];
    name[i] = 0;
}
static int is_flag(MemFile *f) { return strstr(f->name, ".flag") != NULL; }
static MemFile *lookup(const char *name)
{
    unsigned i;
    for (i = 0; i < 12; ++i) if (!strcmp(files[i].name, name)) return &files[i];
    return NULL;
}
static EFI_STATUS EFIAPI mock_close(EFI_FILE_HANDLE f)
{ if (f != &root_handle.protocol) free(f); return EFI_SUCCESS; }
static EFI_STATUS EFIAPI mock_delete(EFI_FILE_HANDLE f)
{
    Handle *h = (Handle *)f;
    if (fail_delete) { mock_close(f); return EFI_WARN_DELETE_FAILURE; }
    h->file->exists = 0;
    mock_close(f); return EFI_SUCCESS;
}
static EFI_STATUS EFIAPI mock_read(EFI_FILE_HANDLE f, UINTN *size, VOID *buffer)
{
    Handle *h = (Handle *)f;
    UINTN available = h->file->size - h->position;
    if (fail_read && h->position >= 4096) return EFI_DEVICE_ERROR;
    if (*size > available) *size = available;
    /* Exercise successful partial reads rather than one full-file read. */
    if (*size > 257) *size = 257;
    memcpy(buffer, h->file->data + h->position, *size);
    h->position += *size; return EFI_SUCCESS;
}
static EFI_STATUS EFIAPI mock_write(EFI_FILE_HANDLE f, UINTN *size, VOID *buffer)
{
    Handle *h = (Handle *)f;
    if (fail_log_write && strstr(h->file->name, "gate.txt")) return EFI_DEVICE_ERROR;
    h->file->data = realloc(h->file->data, h->position + *size + 1);
    if (!h->file->data) return EFI_OUT_OF_RESOURCES;
    memcpy(h->file->data + h->position, buffer, *size);
    h->position += *size;
    if (h->file->size < h->position) h->file->size = h->position;
    return EFI_SUCCESS;
}
static EFI_STATUS EFIAPI mock_position(EFI_FILE_HANDLE f, UINT64 pos)
{ ((Handle *)f)->position = (UINTN)pos; return EFI_SUCCESS; }
static EFI_STATUS EFIAPI mock_set_info(EFI_FILE_HANDLE f, EFI_GUID *guid, UINTN size, VOID *info)
{ (void)guid; (void)size; ((Handle *)f)->file->size = (UINTN)((EFI_FILE_INFO *)info)->FileSize; return EFI_SUCCESS; }
static EFI_STATUS EFIAPI mock_flush(EFI_FILE_HANDLE f)
{ return fail_flag_flush && is_flag(((Handle *)f)->file) ? EFI_DEVICE_ERROR : EFI_SUCCESS; }
static EFI_STATUS EFIAPI mock_open(EFI_FILE_HANDLE dir, EFI_FILE_HANDLE *f, CHAR16 *path, UINT64 mode, UINT64 attr)
{
    char name[80]; MemFile *file; Handle *h; unsigned i;
    (void)dir; (void)attr;
    ascii_name(path, name); file = lookup(name);
    if ((!file || !file->exists) && !(mode & EFI_FILE_MODE_CREATE)) return EFI_NOT_FOUND;
    if (!file) {
        for (i = 0; i < 12 && files[i].name[0]; ++i) {}
        if (i == 12) return EFI_OUT_OF_RESOURCES;
        file = &files[i]; strcpy(file->name, name);
    }
    file->exists = 1;
    h = calloc(1, sizeof(*h)); h->file = file;
    h->protocol.Close = mock_close; h->protocol.Delete = mock_delete;
    h->protocol.Read = mock_read; h->protocol.Write = mock_write;
    h->protocol.SetPosition = mock_position; h->protocol.SetInfo = mock_set_info;
    h->protocol.Flush = mock_flush; *f = &h->protocol;
    return EFI_SUCCESS;
}
EFI_FILE_INFO *LibFileInfo(EFI_FILE_HANDLE f)
{
    EFI_FILE_INFO *info = calloc(1, sizeof(*info));
    info->Size = sizeof(*info); info->FileSize = ((Handle *)f)->file->size;
    return info;
}
static EFI_STATUS EFIAPI mock_handle_protocol(EFI_HANDLE h, EFI_GUID *guid, VOID **interface)
{ (void)h; (void)guid; *interface = &loaded_image; return EFI_SUCCESS; }
static void put(unsigned i, const char *name, const UINT8 *data, UINTN size)
{
    strcpy(files[i].name, name); files[i].size = size; files[i].exists = 1;
    files[i].data = malloc(size + 1); memcpy(files[i].data, data, size);
}
static void setup(void)
{
    unsigned i; char name[80];
    for (i = 0; i < 12; ++i) free(files[i].data);
    memset(files, 0, sizeof(files));
    memset(&root_handle, 0, sizeof(root_handle));
    root_handle.protocol.Open = mock_open; root_handle.protocol.Close = mock_close;
    services.HandleProtocol = mock_handle_protocol;
    root = NULL; log_file = NULL;
    fail_flag_flush = fail_delete = fail_read = fail_log_write = 0;
    put(0, "ORIGINAL.bin", reference_original, REGION_BYTES);
    put(1, "CANDIDATE.bin", reference_candidate, REGION_BYTES);
    put(2, "CURRENT.bin", reference_current, REGION_BYTES);
    ascii_name(INPUT_PATH, name);
#if defined(POST_CHECK)
    put(3, name, reference_candidate, REGION_BYTES);
#elif defined(RESTORE_CHECK)
    put(3, name, reference_original, REGION_BYTES);
#else
    put(3, name, reference_current, REGION_BYTES);
#endif
    ascii_name(FLAG_PATH, name); put(4, name, (const UINT8 *)"stale", 5);
}
static int run_case(const char *name, int expect_success, int stale_expected)
{
    EFI_STATUS status;
#if defined(POST_CHECK) || defined(RESTORE_CHECK)
    status = efi_main(NULL, NULL);
#else
    /* Exercise the real PRE file validator with CURRENT as expected baseline.
     * No call to efi_main/native_security_gate: this is not a firmware test.
     */
    root = &root_handle.protocol;
    status = remove_flag(FLAG_PATH);
    if (!EFI_ERROR(status)) status = create_empty(LOG_PATH, &log_file);
    if (!EFI_ERROR(status)) status = note(L"HOST_ONLY_PRE_FILE_VALIDATION\r\n");
    if (!EFI_ERROR(status)) status = check_region_files();
    if (!EFI_ERROR(status)) status = write_success_flag();
    if (EFI_ERROR(status)) remove_flag(FLAG_PATH);
    if (log_file) log_file->Close(log_file);
    root->Close(root);
#endif
    int flag = files[4].exists;
    int passed = ((status == EFI_SUCCESS) == expect_success) &&
                 (flag == (expect_success || stale_expected));
    printf("%s: %s (status=%llx flag=%d)\n", name, passed ? "PASS" : "FAIL",
           (unsigned long long)status, flag);
    return !passed;
}
static void read_reference(const char *path, UINT8 *buffer)
{
    FILE *f = fopen(path, "rb");
    if (!f || fread(buffer, 1, REGION_BYTES, f) != REGION_BYTES || fgetc(f) != EOF) exit(2);
    fclose(f);
}
int main(int argc, char **argv)
{
    int failures = 0;
    if (argc != 4) return 2;
    read_reference(argv[1], reference_original);
    read_reference(argv[2], reference_current);
    read_reference(argv[3], reference_candidate);
    if (crc32_ieee((const UINT8 *)"123456789", 9) != 0xcbf43926U) return 3;
    if (memcmp(reference_original, reference_current, REGION_BYTES) != 0 ||
        memcmp(reference_current, reference_candidate, REGION_BYTES) == 0) return 4;
    setup(); failures += run_case("exact readback; 257-byte read chunks; stale flag replaced", 1, 0);
    setup(); files[0].data[123] ^= 1; failures += run_case("wrong original CRC", 0, 0);
    setup(); files[1].data[456] ^= 1; failures += run_case("wrong candidate CRC", 0, 0);
    setup(); files[2].data[789] ^= 1; failures += run_case("wrong current CRC", 0, 0);
    setup(); files[3].data[REGION_BYTES - 1] ^= 1; failures += run_case("last-byte mismatch", 0, 0);
    setup(); --files[3].size; failures += run_case("truncated readback", 0, 0);
    setup(); ++files[3].size; failures += run_case("oversized readback", 0, 0);
    setup(); files[1].exists = 0; failures += run_case("missing candidate", 0, 0);
    setup(); files[2].exists = 0; failures += run_case("missing current baseline", 0, 0);
    setup(); fail_read = 1; failures += run_case("read error during partial transfer", 0, 0);
    setup(); fail_flag_flush = 1; failures += run_case("flag flush failure removes new flag", 0, 0);
    setup(); fail_log_write = 1; failures += run_case("log write failure", 0, 0);
    setup(); fail_delete = 1; failures += run_case("stale deletion denied returns failure", 0, 1);
    setup();
#if !defined(POST_CHECK) && !defined(RESTORE_CHECK)
    memcpy(files[3].data, reference_original, REGION_BYTES);
    failures += run_case("PRE accepts ORIGINAL readback because CURRENT equals ORIGINAL", 1, 0);
    setup(); memcpy(files[3].data, reference_candidate, REGION_BYTES);
    failures += run_case("PRE rejects CANDIDATE readback because baseline must be CURRENT", 0, 0);
#elif defined(POST_CHECK)
    memcpy(files[3].data, reference_current, REGION_BYTES);
    failures += run_case("POST rejects CURRENT/ORIGINAL readback", 0, 0);
#else
    memcpy(files[3].data, reference_candidate, REGION_BYTES);
    failures += run_case("RESTORE rejects CANDIDATE readback", 0, 0);
#endif
    return failures ? 1 : 0;
}
