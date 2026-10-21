/* CaskLogic: local-file gates for the combined D7/D1 SiInitFsp experiment.
 * This application NEVER writes MSRs, SPI, PCI or variables and never resets.
 * PRE additionally reads CPUID/MSR13A and public TXT MMIO, independently of
 * prior report files; it requires the independently observed native profile.
 * It does not establish recovery capability or authorize a flash operation.
 * Compile with GNU_EFI_USE_MS_ABI; default PRE, -DPOST_CHECK or -DRESTORE_CHECK.
 * CRC32 values are IEEE/zlib CRC32, computed from the three verified local blocks.
 */
#include <efi.h>
#include <efilib.h>

#if defined(POST_CHECK) && defined(RESTORE_CHECK)
#error Select exactly one mode
#endif

#define DIR L"\\EFI\\CaskLogicTcssD1Test\\"
#include "TcssRegionProfile.h"
#if !defined(REGION_BYTES) || !defined(ORIGINAL_CRC32) || !defined(CANDIDATE_CRC32) || !defined(CURRENT_CRC32) || !defined(REGION_LABEL)
#error A verified TcssRegionProfile.h is required
#endif
#if REGION_BYTES == 0 || (REGION_BYTES % 4096) != 0
#error Region must contain a nonzero whole number of 4-KiB sectors
#endif
#define WIDE_LITERAL_(text) L##text
#define WIDE_LITERAL(text) WIDE_LITERAL_(text)
#define OBSERVED_CPUID 0x000906a3U
#define OBSERVED_SACM 0x0000001000000000ULL
#define OBSERVED_DIDVID 0x00000001b00c8086ULL

#if defined(POST_CHECK)
#define MODE L"POST_CHECK"
#define INPUT_PATH DIR L"region-after.bin"
#define FLAG_PATH DIR L"VERIFIED.flag"
#define LOG_PATH DIR L"region-post-gate.txt"
#elif defined(RESTORE_CHECK)
#define MODE L"RESTORE_CHECK"
#define INPUT_PATH DIR L"region-restored.bin"
#define FLAG_PATH DIR L"RESTORED.flag"
#define LOG_PATH DIR L"region-restore-gate.txt"
#else
#define MODE L"PRE_CHECK"
#define INPUT_PATH DIR L"region-before.bin"
#define FLAG_PATH DIR L"READY.flag"
#define LOG_PATH DIR L"region-pre-gate.txt"
#endif

static EFI_FILE_HANDLE root, log_file;

static EFI_STATUS note(CHAR16 *line)
{
    UINTN wanted = StrLen(line) * sizeof(CHAR16), written = wanted;
    EFI_STATUS s;
    Print(L"%s", line);
    if (!log_file) return EFI_DEVICE_ERROR;
    s = log_file->Write(log_file, &written, line);
    if (EFI_ERROR(s)) return s;
    if (written != wanted) return EFI_DEVICE_ERROR;
    return log_file->Flush(log_file);
}

static EFI_STATUS number(CHAR16 *name, UINT64 value)
{
    CHAR16 line[192];
    SPrint(line, sizeof(line), L"%s=0x%016lx\r\n", name, value);
    return note(line);
}

static EFI_STATUS remove_flag(CHAR16 *path)
{
    EFI_FILE_HANDLE f = NULL;
    EFI_STATUS s = root->Open(root, &f, path, EFI_FILE_MODE_READ | EFI_FILE_MODE_WRITE, 0);
    if (s == EFI_NOT_FOUND) return EFI_SUCCESS;
    if (EFI_ERROR(s)) return s;
    /* Delete closes the handle even on failure. A warning is not success here. */
    s = f->Delete(f);
    return s == EFI_SUCCESS ? EFI_SUCCESS : EFI_DEVICE_ERROR;
}

static EFI_STATUS create_empty(CHAR16 *path, EFI_FILE_HANDLE *f)
{
    EFI_FILE_INFO *info;
    EFI_STATUS s = root->Open(root, f, path,
        EFI_FILE_MODE_READ | EFI_FILE_MODE_WRITE | EFI_FILE_MODE_CREATE, 0);
    if (EFI_ERROR(s)) return s;
    info = LibFileInfo(*f);
    if (!info) { (*f)->Close(*f); *f = NULL; return EFI_DEVICE_ERROR; }
    info->FileSize = 0;
    s = (*f)->SetInfo(*f, &GenericFileInfo, (UINTN)info->Size, info);
    FreePool(info);
    if (!EFI_ERROR(s)) s = (*f)->SetPosition(*f, 0);
    if (EFI_ERROR(s)) { (*f)->Close(*f); *f = NULL; }
    return s;
}

static UINT32 crc32_ieee(const UINT8 *data, UINTN size)
{
    UINT32 crc = 0xffffffffU;
    UINTN i;
    UINT32 bit;
    for (i = 0; i < size; ++i) {
        crc ^= data[i];
        for (bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ ((crc & 1U) ? 0xedb88320U : 0);
    }
    return ~crc;
}

static EFI_STATUS load_exact(CHAR16 *path, UINT8 **data)
{
    EFI_FILE_HANDLE f = NULL;
    EFI_FILE_INFO *info = NULL;
    EFI_STATUS s, close_status;
    UINTN offset = 0, got;
    UINT8 extra;
    *data = NULL;
    s = root->Open(root, &f, path, EFI_FILE_MODE_READ, 0);
    if (EFI_ERROR(s)) return s;
    info = LibFileInfo(f);
    if (!info) { s = EFI_DEVICE_ERROR; goto end; }
    if (info->FileSize != REGION_BYTES || (info->Attribute & EFI_FILE_DIRECTORY)) {
        s = EFI_BAD_BUFFER_SIZE; goto end;
    }
    *data = AllocatePool(REGION_BYTES);
    if (!*data) { s = EFI_OUT_OF_RESOURCES; goto end; }
    while (offset < REGION_BYTES) {
        got = REGION_BYTES - offset;
        s = f->Read(f, &got, *data + offset);
        if (EFI_ERROR(s)) goto end;
        if (got == 0 || got > REGION_BYTES - offset) { s = EFI_DEVICE_ERROR; goto end; }
        offset += got;
    }
    got = 1;
    s = f->Read(f, &got, &extra);
    if (!EFI_ERROR(s) && got != 0) s = EFI_BAD_BUFFER_SIZE;
end:
    if (info) FreePool(info);
    close_status = f->Close(f);
    if (!EFI_ERROR(s) && EFI_ERROR(close_status)) s = close_status;
    if (EFI_ERROR(s) && *data) { FreePool(*data); *data = NULL; }
    return s;
}

#if !defined(POST_CHECK) && !defined(RESTORE_CHECK)
static UINT64 txt_read64(UINT64 address)
{
    UINT64 value;
    __asm__ volatile("lfence" ::: "memory");
    value = *(volatile UINT64 *)(UINTN)address;
    __asm__ volatile("lfence" ::: "memory");
    return value;
}

static UINT32 txt_read32(UINT64 address)
{
    UINT32 value;
    __asm__ volatile("lfence" ::: "memory");
    value = *(volatile UINT32 *)(UINTN)address;
    __asm__ volatile("lfence" ::: "memory");
    return value;
}

static EFI_STATUS native_security_gate(void)
{
    UINT32 a, b, c, d, model, family, lo, hi;
    UINT64 sacm, didvid, policy, bootstatus;
    UINT32 acmstatus;
    EFI_STATUS s;
    __asm__ volatile("cpuid" : "=a"(a), "=b"(b), "=c"(c), "=d"(d)
                     : "a"(0), "c"(0) : "memory");
    if (a < 1 || b != 0x756e6547U || d != 0x49656e69U || c != 0x6c65746eU)
        return EFI_UNSUPPORTED;
    __asm__ volatile("cpuid" : "=a"(a), "=b"(b), "=c"(c), "=d"(d)
                     : "a"(1), "c"(0) : "memory");
    if (EFI_ERROR((s = number(L"cpuid_signature", a)))) return s;
    family = (a >> 8) & 15;
    model = (a >> 4) & 15;
    if (family == 6 || family == 15) model |= ((a >> 16) & 15) << 4;
    if (family == 15) family += (a >> 20) & 255;
    if (a != OBSERVED_CPUID || family != 6 || model != 0x9a ||
        (c & (1U << 31)) || !(d & (1U << 5)))
        return EFI_UNSUPPORTED;
    s = note(L"phase=before_native_rdmsr_13a\r\n");
    if (EFI_ERROR(s)) return s;
    __asm__ volatile("rdmsr" : "=a"(lo), "=d"(hi) : "c"(0x13a) : "memory");
    sacm = ((UINT64)hi << 32) | lo;
    if (EFI_ERROR((s = number(L"msr_13a_raw", sacm)))) return s;
    if (EFI_ERROR((s = number(L"verified_boot_bit6", (sacm >> 6) & 1)))) return s;
    /* Intel SBL CommonSocPkg/BootGuardLibCBnT (used by AlderLake BoardConfig)
     * reports Boot Guard unsupported when capability bit32 is clear. It does
     * NOT define bit36. Do not reinterpret bit36 or require bit32=1 as proof
     * of a valid read. Match only the observed native profile, with explicit
     * rejection of active Verified Boot and corroborating native TXT values.
     * Sources and fresh FIT/KM/BPM evidence: ../firmware-candidate/bootguard-review.md.
     */
    if (sacm & (1ULL << 6)) return EFI_SECURITY_VIOLATION;
    if (sacm != OBSERVED_SACM) return EFI_SECURITY_VIOLATION;
    if (EFI_ERROR((s = note(L"phase=before_public_txt_profile_read\r\n")))) return s;
    didvid = txt_read64(0xfed30110ULL);
    if (EFI_ERROR((s = number(L"txt_didvid_fed30110", didvid)))) return s;
    if (didvid != OBSERVED_DIDVID) return EFI_SECURITY_VIOLATION;
    policy = txt_read64(0xfed30378ULL);
    bootstatus = txt_read64(0xfed300a0ULL);
    acmstatus = txt_read32(0xfed30328ULL);
    if (EFI_ERROR((s = number(L"acm_policy_status_fed30378", policy)))) return s;
    if (EFI_ERROR((s = number(L"txt_bootstatus_fed300a0", bootstatus)))) return s;
    if (EFI_ERROR((s = number(L"acm_status_fed30328", acmstatus)))) return s;
    if (policy != 0 || bootstatus != 0 || acmstatus != 0)
        return EFI_SECURITY_VIOLATION;
    return note(L"native_security_gate=observed_profile_match\r\n"
                L"bootguard_capability_bit32=0; Intel SBL reports unsupported; verified_boot_bit6=0\r\n"
                L"bit36=uninterpreted; no proof of general firmware integrity or bootability inferred\r\n");
}
#endif

static EFI_STATUS write_success_flag(void)
{
    EFI_FILE_HANDLE f = NULL;
    EFI_STATUS s, close_status;
    CHAR16 text[512];
    UINTN wanted, written;
    s = create_empty(FLAG_PATH, &f);
    if (EFI_ERROR(s)) return s;
    SPrint(text, sizeof(text), L"\xfeff" L"CaskLogic TcssRegionGate D1 v3 %s PASS\r\n"
           L"region=%s original_crc=%08x current_crc=%08x candidate_crc=%08x\r\n",
           MODE, WIDE_LITERAL(REGION_LABEL), ORIGINAL_CRC32, CURRENT_CRC32, CANDIDATE_CRC32);
    wanted = StrLen(text) * sizeof(CHAR16); written = wanted;
    s = f->Write(f, &written, text);
    if (!EFI_ERROR(s) && written != wanted) s = EFI_DEVICE_ERROR;
    if (!EFI_ERROR(s)) s = f->Flush(f);
    close_status = f->Close(f);
    if (!EFI_ERROR(s) && EFI_ERROR(close_status)) s = close_status;
    if (EFI_ERROR(s)) remove_flag(FLAG_PATH);
    return s;
}

/* Pure file validation, separated so PRE/CURRENT semantics can be tested on
 * the host without executing the native-only CPUID/MSR/MMIO guard. The EFI
 * entry point always runs that guard first in PRE mode.
 */
static EFI_STATUS check_region_files(void)
{
    EFI_STATUS s;
    UINT8 *original = NULL, *current = NULL, *candidate = NULL, *observed = NULL, *expected;
    UINT32 original_crc, current_crc, candidate_crc, observed_crc, expected_crc;
    UINTN i, differences = 0;
    if (EFI_ERROR((s = load_exact(DIR L"ORIGINAL.bin", &original)))) goto done;
    if (EFI_ERROR((s = load_exact(DIR L"CURRENT.bin", &current)))) goto done;
    if (EFI_ERROR((s = load_exact(DIR L"CANDIDATE.bin", &candidate)))) goto done;
    if (EFI_ERROR((s = load_exact(INPUT_PATH, &observed)))) goto done;
    original_crc = crc32_ieee(original, REGION_BYTES);
    current_crc = crc32_ieee(current, REGION_BYTES);
    candidate_crc = crc32_ieee(candidate, REGION_BYTES);
    observed_crc = crc32_ieee(observed, REGION_BYTES);
    if (EFI_ERROR((s = number(L"original_crc32", original_crc)))) goto done;
    if (EFI_ERROR((s = number(L"current_crc32", current_crc)))) goto done;
    if (EFI_ERROR((s = number(L"candidate_crc32", candidate_crc)))) goto done;
    if (EFI_ERROR((s = number(L"observed_crc32", observed_crc)))) goto done;
    if (original_crc != ORIGINAL_CRC32 || current_crc != CURRENT_CRC32 || candidate_crc != CANDIDATE_CRC32) {
        s = EFI_CRC_ERROR; goto done;
    }
#if defined(POST_CHECK)
    expected = candidate; expected_crc = CANDIDATE_CRC32;
#elif defined(RESTORE_CHECK)
    expected = original; expected_crc = ORIGINAL_CRC32;
#else
    expected = current; expected_crc = CURRENT_CRC32;
#endif
    /* Check every byte as well as CRC; never accept a partial prefix. */
    for (i = 0; i < REGION_BYTES; ++i) if (observed[i] != expected[i]) ++differences;
    if (EFI_ERROR((s = number(L"readback_byte_mismatches", differences)))) goto done;
    if (differences != 0 || observed_crc != expected_crc) { s = EFI_COMPROMISED_DATA; goto done; }
    s = EFI_SUCCESS;
done:
    if (original) FreePool(original);
    if (current) FreePool(current);
    if (candidate) FreePool(candidate);
    if (observed) FreePool(observed);
    return s;
}

EFI_STATUS efi_main(EFI_HANDLE image, EFI_SYSTEM_TABLE *system)
{
    EFI_LOADED_IMAGE *loaded = NULL;
    EFI_STATUS s;
    UINTN bytes = sizeof(CHAR16);
    CHAR16 bom = 0xfeff;
    InitializeLib(image, system);
    Print(L"CaskLogic TcssRegionGate %s: no hardware writes.\r\n", MODE);
    s = BS->HandleProtocol(image, &LoadedImageProtocol, (VOID **)&loaded);
    if (EFI_ERROR(s)) return s;
    root = LibOpenRoot(loaded->DeviceHandle);
    if (!root) return EFI_NOT_FOUND;
    /* A failed run must never leave its previous success marker valid. */
    s = remove_flag(FLAG_PATH);
    if (EFI_ERROR(s)) goto done;
#if !defined(POST_CHECK) && !defined(RESTORE_CHECK)
    if (EFI_ERROR((s = remove_flag(DIR L"VERIFIED.flag")))) goto done;
    if (EFI_ERROR((s = remove_flag(DIR L"RESTORED.flag")))) goto done;
#endif
    s = create_empty(LOG_PATH, &log_file);
    if (EFI_ERROR(s)) goto done;
    s = log_file->Write(log_file, &bytes, &bom);
    if (EFI_ERROR(s) || bytes != sizeof(CHAR16)) { s = EFI_DEVICE_ERROR; goto done; }
    if (EFI_ERROR((s = note(L"CaskLogic TcssRegionGate D1 v3\r\nphase=start\r\nmode=" MODE L"\r\n")))) goto done;
#if !defined(POST_CHECK) && !defined(RESTORE_CHECK)
    if (EFI_ERROR((s = native_security_gate()))) goto done;
#endif
    if (EFI_ERROR((s = check_region_files()))) goto done;
    if (EFI_ERROR((s = note(L"phase=all_checks_passed_before_flag\r\n")))) goto done;
    s = write_success_flag();
done:
    if (EFI_ERROR(s)) {
        /* Removing a flag is best effort; a deletion error still returns failure. */
        if (root) remove_flag(FLAG_PATH);
        if (log_file) { number(L"failure_status", s); note(L"result=FAIL\r\n"); }
    }
    Print(L"TcssRegionGate %s result: %r\r\n", MODE, s);
    if (log_file) log_file->Close(log_file);
    if (root) root->Close(root);
    return s;
}
