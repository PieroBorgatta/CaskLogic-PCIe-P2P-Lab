/* CaskLogic: read-only native security observation for this Alder Lake host.
 * Compile GNU-EFI with -DGNU_EFI_USE_MS_ABI and -fshort-wchar.
 * No WRMSR, SetVariable, SPI write, PCI write, reset or driver loading.
 * The only writes are this application's text output on its own filesystem.
 * Sources/interpretation: bootguard-review.md in the same report directory.
 */
#include <efi.h>
#include <efilib.h>

#define OUTPUT L"\\EFI\\CaskLogicTcssTest\\native-security.txt"
#define TXT_PUBLIC_BASE 0xFED30000ULL
static EFI_FILE_HANDLE report;

static EFI_STATUS record(CHAR16 *line)
{
    UINTN bytes = StrLen(line) * sizeof(CHAR16), written = bytes;
    EFI_STATUS status;
    Print(L"%s", line);
    status = report->Write(report, &written, line);
    if (EFI_ERROR(status) || written != bytes)
        return EFI_DEVICE_ERROR;
    return report->Flush(report);
}

static EFI_STATUS value(CHAR16 *name, UINT64 data)
{
    CHAR16 line[160];
    SPrint(line, sizeof(line), L"%s=0x%016lx\r\n", name, data);
    return record(line);
}

static void cpuid(UINT32 leaf, UINT32 *a, UINT32 *b, UINT32 *c, UINT32 *d)
{
    __asm__ volatile("cpuid" : "=a"(*a), "=b"(*b), "=c"(*c), "=d"(*d)
                     : "a"(leaf), "c"(0) : "memory");
}

static UINT64 rdmsr_13a(void)
{
    UINT32 lo, hi;
    __asm__ volatile("rdmsr" : "=a"(lo), "=d"(hi) : "c"(0x13a) : "memory");
    return ((UINT64)hi << 32) | lo;
}

static UINT64 mmio_read64(UINT64 address)
{
    UINT64 data;
    __asm__ volatile("lfence" ::: "memory");
    data = *(volatile UINT64 *)(UINTN)address;
    __asm__ volatile("lfence" ::: "memory");
    return data;
}

static UINT32 mmio_read32(UINT64 address)
{
    UINT32 data;
    __asm__ volatile("lfence" ::: "memory");
    data = *(volatile UINT32 *)(UINTN)address;
    __asm__ volatile("lfence" ::: "memory");
    return data;
}

EFI_STATUS efi_main(EFI_HANDLE image, EFI_SYSTEM_TABLE *system)
{
    EFI_LOADED_IMAGE *loaded = NULL;
    EFI_FILE_HANDLE root = NULL;
    EFI_FILE_INFO *info = NULL;
    EFI_STATUS status;
    EFI_TIME now;
    UINT32 a, b, c, d, maxleaf, family, model, signature, features;
    UINT64 sacm, didvid, policy, bootstatus;
    UINT32 acmstatus;
    UINTN bytes;
    CHAR16 bom = 0xfeff, line[256];

    InitializeLib(image, system);
    Print(L"CaskLogic BootGuardRead: observation only; no firmware writes.\r\n");
    status = BS->HandleProtocol(image, &LoadedImageProtocol, (VOID **)&loaded);
    if (EFI_ERROR(status)) return status;
    root = LibOpenRoot(loaded->DeviceHandle);
    if (!root) return EFI_NOT_FOUND;
    status = root->Open(root, &report, OUTPUT,
                        EFI_FILE_MODE_READ | EFI_FILE_MODE_WRITE | EFI_FILE_MODE_CREATE, 0);
    if (EFI_ERROR(status)) { root->Close(root); return status; }
    info = LibFileInfo(report);
    if (!info) { status = EFI_DEVICE_ERROR; goto done; }
    info->FileSize = 0;
    status = report->SetInfo(report, &GenericFileInfo, (UINTN)info->Size, info);
    FreePool(info);
    if (EFI_ERROR(status)) goto done;
    status = report->SetPosition(report, 0);
    if (EFI_ERROR(status)) goto done;
    bytes = sizeof(bom);
    status = report->Write(report, &bytes, &bom);
    if (EFI_ERROR(status) || bytes != sizeof(bom)) { status = EFI_DEVICE_ERROR; goto done; }
    status = record(L"CaskLogic BootGuardRead v1\r\nphase=start\r\n"
                    L"scope=CPUID, RDMSR 0x13A, public TXT MMIO reads only\r\n");
    if (EFI_ERROR(status)) goto done;
    if (!EFI_ERROR(RT->GetTime(&now, NULL))) {
        SPrint(line, sizeof(line), L"efi_time=%04d-%02d-%02dT%02d:%02d:%02d\r\n",
               now.Year, now.Month, now.Day, now.Hour, now.Minute, now.Second);
        if (EFI_ERROR((status = record(line)))) goto done;
    }
    cpuid(0, &a, &b, &c, &d);
    maxleaf = a;
    if (EFI_ERROR((status = value(L"cpuid_vendor_ebx", b)))) goto done;
    if (EFI_ERROR((status = value(L"cpuid_vendor_edx", d)))) goto done;
    if (EFI_ERROR((status = value(L"cpuid_vendor_ecx", c)))) goto done;
    if (b != 0x756e6547 || d != 0x49656e69 || c != 0x6c65746e || maxleaf < 1) {
        record(L"STOP=not GenuineIntel or CPUID leaf 1 unavailable\r\n");
        status = EFI_UNSUPPORTED; goto done;
    }
    cpuid(1, &a, &b, &c, &d);
    signature = a; features = c;
    family = (a >> 8) & 15;
    model = (a >> 4) & 15;
    if (family == 6 || family == 15) model |= ((a >> 16) & 15) << 4;
    if (family == 15) family += (a >> 20) & 255;
    if (EFI_ERROR((status = value(L"cpuid_signature", signature)))) goto done;
    if (EFI_ERROR((status = value(L"cpuid_family", family)))) goto done;
    if (EFI_ERROR((status = value(L"cpuid_model", model)))) goto done;
    if (EFI_ERROR((status = value(L"cpuid_1_ecx", features)))) goto done;
    if (EFI_ERROR((status = value(L"cpuid_1_edx", d)))) goto done;
    if (family != 6 || model != 0x9a || (features & (1U << 31)) || !(d & (1U << 5))) {
        record(L"STOP=CPU is not native Intel family 6 model 0x9A with MSR support\r\n");
        status = EFI_UNSUPPORTED; goto done;
    }
    status = record(L"phase=before_rdmsr_13a\r\n"
                    L"cpu_guard=GenuineIntel,family6,model9A,hypervisor_bit0,MSR_supported\r\n");
    if (EFI_ERROR(status)) goto done;
    sacm = rdmsr_13a();
    if (EFI_ERROR((status = value(L"msr_13a_raw", sacm)))) goto done;
    if (EFI_ERROR((status = value(L"sacm_nem_bit0", sacm & 1)))) goto done;
    if (EFI_ERROR((status = value(L"sacm_tpm_type_bits2_1", (sacm >> 1) & 3)))) goto done;
    if (EFI_ERROR((status = value(L"sacm_tpm_success_bit3", (sacm >> 3) & 1)))) goto done;
    if (EFI_ERROR((status = value(L"sacm_measured_boot_bit5", (sacm >> 5) & 1)))) goto done;
    if (EFI_ERROR((status = value(L"sacm_verified_boot_bit6", (sacm >> 6) & 1)))) goto done;
    if (EFI_ERROR((status = value(L"sacm_bootguard_capable_bit32", (sacm >> 32) & 1)))) goto done;
    status = record(L"interpretation=bit32 is capability, not proof of verified boot; bit6 is verified boot\r\n"
                    L"phase=before_public_txt_didvid_read\r\n");
    if (EFI_ERROR(status)) goto done;
    didvid = mmio_read64(TXT_PUBLIC_BASE + 0x110);
    if (EFI_ERROR((status = value(L"txt_didvid_fed30110", didvid)))) goto done;
    if (didvid == 0 || didvid == ~0ULL || (didvid & 0xffff) != 0x8086) {
        status = record(L"txt_mmio=not validated; skip ACM_POLICY_STATUS and ACM_STATUS\r\n"
                        L"phase=complete_msr_only\r\n");
        goto done;
    }
    status = record(L"phase=before_acm_policy_status_read\r\n");
    if (EFI_ERROR(status)) goto done;
    policy = mmio_read64(TXT_PUBLIC_BASE + 0x378);
    if (EFI_ERROR((status = value(L"acm_policy_status_fed30378", policy)))) goto done;
    /* Keep raw policy: its bit definitions vary across platform generations. */
    if (EFI_ERROR((status = value(L"policy_tpm_type_bits14_13", (policy >> 13) & 3)))) goto done;
    if (EFI_ERROR((status = value(L"policy_scrtm_status_bits34_32", (policy >> 32) & 7)))) goto done;
    bootstatus = mmio_read64(TXT_PUBLIC_BASE + 0xa0);
    if (EFI_ERROR((status = value(L"txt_bootstatus_fed300a0", bootstatus)))) goto done;
    acmstatus = mmio_read32(TXT_PUBLIC_BASE + 0x328);
    if (EFI_ERROR((status = value(L"acm_status_fed30328", acmstatus)))) goto done;
    status = record(L"interpretation=policy register is model-specific; raw values retained; no flash approval inferred\r\n"
                    L"phase=complete\r\n");
done:
    Print(L"CaskLogic BootGuardRead status: %r\r\n", status);
    if (report) report->Close(report);
    if (root) root->Close(root);
    return status;
}
