#include <cuda.h>
#include "driver/cask_iova_write_ioctl.h"
#include <cerrno>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dirent.h>
#include <fcntl.h>
#include <signal.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <stdexcept>
#include <string>
#include <vector>

static_assert(sizeof(UVM_TEST_CASK_IOVA_WRITE_PARAMS) == 120, "IOVA write ABI size");
static_assert(offsetof(UVM_TEST_CASK_IOVA_WRITE_PARAMS, bar1_physical) == 56, "IOVA write input boundary");

static void check(CUresult result, const char *what)
{
    if (result != CUDA_SUCCESS) {
        const char *message = nullptr;
        cuGetErrorString(result, &message);
        throw std::runtime_error(std::string(what) + ":" + (message ? message : "unknown"));
    }
}

[[noreturn]] static void park()
{
    signal(SIGTERM, SIG_IGN);
    std::puts("IOVA_WRITE_PARKED completion_uncertain=1 resources_retained_until_watchdog=1");
    std::fflush(nullptr);
    for (;;)
        pause();
}

static bool equal_inputs(const UVM_TEST_CASK_IOVA_WRITE_PARAMS &left,
                         const UVM_TEST_CASK_IOVA_WRITE_PARAMS &right)
{
    return !std::memcmp(&left, &right, 56);
}

static bool validation_ok(const UVM_TEST_CASK_IOVA_WRITE_PARAMS &input,
                          const UVM_TEST_CASK_IOVA_WRITE_PARAMS &output,
                          int rv)
{
    return rv == 0 && equal_inputs(input, output) && output.rmStatus == 0 &&
           output.result_flags == CASK_IOVA_WRITE_VALIDATED && output.domain_type == 3 &&
           !output.bar1_physical && !output.bar1_iova && !output.bar1_resource_start &&
           !output.bar1_page_level && !output.host_pass_mask && !output.self_pass_mask &&
           !output.completed_mask && !output.alias_pass_mask && !output.cpu_control_mask &&
           !output.reserved_output;
}

int main(int argc, char **argv)
{
    setvbuf(stdout, nullptr, _IONBF, 0);
    CUcontext contexts[2]{};
    CUdeviceptr va[2]{};
    CUmemGenericAllocationHandle handles[2]{};
    size_t lengths[2]{};
    int owned = -1;
    unsigned int selected_index = 2;
    bool success = false;

    try {
        if (geteuid() != 0)
            throw std::runtime_error("root_required");
        if (argc != 2 || (std::strcmp(argv[1], "--index=0") &&
                          std::strcmp(argv[1], "--index=1")))
            throw std::runtime_error("exact_index_required");
        selected_index = argv[1][8] - '0';
        std::printf("IOVA_WRITE_BEGIN abi=3 private_rm_vidmem_target=1 dma_direction=DMA_FROM_DEVICE self_bar1_loopback=1 cross_gpu_peer_transfer=0 ordinary_peer_access=0 host_staging_for_self=0 owner_gpu_readback_primary=1 cpu_write_control_after_self=1 cpu_control_is_p2p=0 execution_index=%u isolated_process=1\n",
                    selected_index);
        check(cuInit(0), "cuInit");
        int count = 0;
        check(cuDeviceGetCount(&count), "count");
        if (count != 2)
            throw std::runtime_error("two_gpus_required");

        UVM_TEST_CASK_IOVA_WRITE_PARAMS request{};
        request.abi_version = CASK_IOVA_WRITE_ABI;
        const char *envs[] = {"CASKLOGIC_GPU0_UUID", "CASKLOGIC_GPU1_UUID"};
        const char *bdfs[] = {"0000:01:00.0", "0000:06:00.0"};
        for (int index = 0; index < 2; ++index) {
            CUdevice device;
            CUuuid uuid{};
            char bdf[32]{}, hex[33]{};
            check(cuDeviceGet(&device, index), "device");
            check(cuDeviceGetUuid(&uuid, device), "uuid");
            check(cuDeviceGetPCIBusId(bdf, sizeof(bdf), device), "bdf");
            for (int byte = 0; byte < 16; ++byte)
                std::snprintf(hex + 2 * byte, 3, "%02x", (unsigned char)uuid.bytes[byte]);
            const char *wanted = std::getenv(envs[index]);
            if (!wanted || std::strlen(wanted) != 32 || std::strcmp(wanted, hex) || std::strcmp(bdf, bdfs[index]))
                throw std::runtime_error("gpu_identity");
            std::memcpy(request.gpu_uuid[index], uuid.bytes, 16);
            check(cuCtxCreate(&contexts[index], 0, device), "context");
            CUmemAllocationProp property{};
            property.type = CU_MEM_ALLOCATION_TYPE_PINNED;
            property.location.type = CU_MEM_LOCATION_TYPE_DEVICE;
            property.location.id = device;
            check(cuMemGetAllocationGranularity(&lengths[index], &property, CU_MEM_ALLOC_GRANULARITY_MINIMUM), "granularity");
            check(cuMemCreate(&handles[index], lengths[index], &property, 0), "create");
            check(cuMemAddressReserve(&va[index], lengths[index], 0, 0, 0), "reserve");
            check(cuMemMap(va[index], lengths[index], 0, handles[index], 0), "map_local");
            CUmemAccessDesc access{};
            access.location = property.location;
            access.flags = CU_MEM_ACCESS_FLAGS_PROT_READWRITE;
            check(cuMemSetAccess(va[index], lengths[index], &access, 1), "local_access");
            std::printf("IOVA_WRITE_GPU index=%d bdf=%s local_registration_bytes=%zu peer_mapping=0\n",
                        index,
                        bdf,
                        lengths[index]);
        }

        struct stat target{};
        if (stat("/dev/nvidia-uvm", &target) || !S_ISCHR(target.st_mode))
            throw std::runtime_error("uvm_stat");
        DIR *directory = opendir("/proc/self/fd");
        if (!directory)
            throw std::runtime_error("fds");
        std::vector<int> fds;
        while (dirent *entry = readdir(directory)) {
            char *end = nullptr;
            errno = 0;
            long number = std::strtol(entry->d_name, &end, 10);
            if (errno || !end || *end || number < 0 || number > 1048576)
                continue;
            struct stat candidate{};
            if (!fstat((int)number, &candidate) && S_ISCHR(candidate.st_mode) && candidate.st_rdev == target.st_rdev)
                fds.push_back((int)number);
        }
        closedir(directory);

        int selected = -1;
        unsigned int matches = 0;
        request.request_id = 200;
        for (int fd : fds) {
            auto output = request;
            errno = 0;
            int rv = ioctl(fd, CASK_IOVA_WRITE_IOCTL, &output);
            bool valid = validation_ok(request, output, rv);
            std::printf("IOVA_WRITE_FD fd=%d rv=%d status=%x flags=%x domain=%u valid=%d\n",
                        fd,
                        rv,
                        output.rmStatus,
                        output.result_flags,
                        output.domain_type,
                        valid);
            if (valid) {
                selected = fd;
                ++matches;
            }
        }
        if (matches != 1)
            throw std::runtime_error("uvm_matching_fd_not_unique");
        owned = fcntl(selected, F_DUPFD_CLOEXEC, 3);
        if (owned < 0)
            throw std::runtime_error("duplicate_fd");
        std::printf("IOVA_WRITE_FD_SELECTED matches=1 candidate_count=%zu\n", fds.size());

        request.index = selected_index;
        request.request_id = 201 + selected_index;
        request.operation = 1;
        auto output = request;
        struct sigaction ignored{}, previous{};
        ignored.sa_handler = SIG_IGN;
        sigemptyset(&ignored.sa_mask);
        if (sigaction(SIGTERM, &ignored, &previous))
            throw std::runtime_error("signal_guard");
        errno = 0;
        int rv = ioctl(owned, CASK_IOVA_WRITE_IOCTL, &output);
        int saved_errno = errno;
        std::printf("IOVA_WRITE_IOCTL index=%u request=%llu rv=%d errno=%d status=%x flags=%x domain=%u alias_mask=%x host_mask=%x self_mask=%x completed_mask=%x cpu_control_mask=%x bar1_phys=%llx bar1_iova=%llx bar1_start=%llx pte_level=%u inputs_unchanged=%d\n",
                    selected_index,
                    (unsigned long long)request.request_id,
                    rv,
                    saved_errno,
                    output.rmStatus,
                    output.result_flags,
                    output.domain_type,
                    output.alias_pass_mask,
                    output.host_pass_mask,
                    output.self_pass_mask,
                    output.completed_mask,
                    output.cpu_control_mask,
                    (unsigned long long)output.bar1_physical,
                    (unsigned long long)output.bar1_iova,
                    (unsigned long long)output.bar1_resource_start,
                    output.bar1_page_level,
                    equal_inputs(request, output));
        /* A normal driver failure is reported in rmStatus with rv == 0
         * after copying the result back. Only a failed copy, corrupted
         * immutable input, or an explicit retained state is uncertain. */
        if (rv != 0 || !equal_inputs(request, output) ||
            (output.result_flags & CASK_IOVA_WRITE_RETAINED))
            park();
        if (sigaction(SIGTERM, &previous, nullptr))
            throw std::runtime_error("signal_restore");
        const unsigned int complete_flags = CASK_IOVA_WRITE_VALIDATED |
                                            CASK_IOVA_WRITE_MAPPED |
                                            CASK_IOVA_WRITE_SUBMITTED |
                                            CASK_IOVA_WRITE_COMPLETED |
                                            CASK_IOVA_WRITE_UNMAPPED |
                                            CASK_IOVA_WRITE_ALIAS_VERIFIED |
                                            CASK_IOVA_WRITE_CPU_COMPLETED;
        if (output.rmStatus || output.result_flags != complete_flags ||
            output.domain_type != 3 || output.alias_pass_mask != 0xf ||
            output.host_pass_mask != 0x2d || output.completed_mask != 0x3f ||
            output.self_pass_mask > 3 || output.cpu_control_mask > 0xf ||
            !(output.cpu_control_mask & 0x4) || output.reserved_output ||
            !output.bar1_physical ||
            output.bar1_iova == output.bar1_physical ||
            output.bar1_physical < output.bar1_resource_start || !output.bar1_page_level)
            throw std::runtime_error("measurement_not_qualified");
        success = true;
    }
    catch (const std::exception &error) {
        std::printf("IOVA_WRITE_ERROR reason=%s\n", error.what());
    }

    /* No uncertain operation reaches here. Context destruction owns partial
     * local VMM registration resources; no cross-GPU peer mapping was created. */
    if (owned >= 0)
        close(owned);
    for (int index = 1; index >= 0; --index) {
        if (!contexts[index])
            continue;
        cuCtxSetCurrent(contexts[index]);
        if (va[index]) {
            cuMemUnmap(va[index], lengths[index]);
            cuMemAddressFree(va[index], lengths[index]);
        }
        if (handles[index])
            cuMemRelease(handles[index]);
        cuCtxDestroy(contexts[index]);
    }
    std::printf("IOVA_WRITE_END execution_index=%u protocol_complete=%d p2p_solution_claimed=0\n",
                selected_index,
                success);
    return success ? 0 : 20;
}
