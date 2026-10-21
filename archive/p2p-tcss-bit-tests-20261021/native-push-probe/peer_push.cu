#include <cuda.h>
#include <cuda_runtime.h>
#include <algorithm>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <time.h>
#include <unistd.h>
#include <vector>
#include "pcie_diag.h"

// CPU initializes and checks buffers. Only this kernel carries the payload
// between GPUs: its source belongs to the executing GPU, its destination to peer.
__global__ void peer_push_kernel(const uint32_t *local_source,
                                 volatile uint32_t *peer_destination,
                                 size_t words) {
    bool wrote = false;
    for (size_t i = blockIdx.x * blockDim.x + threadIdx.x;
         i < words; i += gridDim.x * blockDim.x) {
        peer_destination[i] = local_source[i];
        wrote = true;
    }
    if (wrote) __threadfence_system();
}

static int kmsg_fd = -1;
static uint64_t ns_now() {
    timespec t{};
    if (clock_gettime(CLOCK_MONOTONIC, &t)) {
        std::printf("FATAL clock_gettime errno=%d\n", errno);
        std::exit(20);
    }
    return uint64_t(t.tv_sec) * 1000000000ULL + uint64_t(t.tv_nsec);
}
static void phase(const char *name, int source=-1, int destination=-1) {
    const uint64_t ns = ns_now();
    char line[256];
    const int n = std::snprintf(line, sizeof(line),
        "CaskLogicPush phase=%s monotonic=%llu.%09llu s=%d d=%d\n",
        name, (unsigned long long)(ns/1000000000ULL),
        (unsigned long long)(ns%1000000000ULL), source, destination);
    std::fputs(line, stdout);
    if (kmsg_fd >= 0 && n > 0 && size_t(n) < sizeof(line)) {
        const ssize_t result = write(kmsg_fd, line, size_t(n));
        if (result != n) std::printf("KMSG_MARKER_FAILED errno=%d\n", errno);
    }
}
static void runtime_check(cudaError_t value, const char *call, int line) {
    if (value == cudaSuccess) return;
    std::printf("CUDA_ERROR call=%s line=%d code=%d error=%s\n", call, line, int(value), cudaGetErrorString(value));
    phase("cuda_error");
    std::exit(21);
}
static void driver_check(CUresult value, const char *call, int line) {
    if (value == CUDA_SUCCESS) return;
    const char *message = "unknown";
    cuGetErrorString(value, &message);
    std::printf("DRIVER_ERROR call=%s line=%d code=%d error=%s\n", call, line, int(value), message);
    phase("driver_error");
    std::exit(22);
}
#define CK(call) runtime_check((call), #call, __LINE__)
#define CUCK(call) driver_check((call), #call, __LINE__)

struct Buffer {
    CUdeviceptr address = 0;
    CUmemGenericAllocationHandle handle = 0;
    size_t allocation_bytes = 0;
    size_t granularity = 0;
    int owner = -1;
    const char *role = nullptr;
};
static constexpr size_t MAX_BYTES = 8ULL * 1024 * 1024;
static Buffer send_buffer[2], receive_buffer[2];

static void allocate(Buffer &buffer, int owner, const char *role) {
    CK(cudaSetDevice(owner));
    CUmemAllocationProp prop{};
    prop.type = CU_MEM_ALLOCATION_TYPE_PINNED;
    prop.location.type = CU_MEM_LOCATION_TYPE_DEVICE;
    prop.location.id = owner;
    CUCK(cuMemGetAllocationGranularity(&buffer.granularity, &prop, CU_MEM_ALLOC_GRANULARITY_MINIMUM));
    if (!buffer.granularity || MAX_BYTES % buffer.granularity != 0) {
        std::printf("FATAL allocation_granularity=%zu exceeds_fixed_buffer_contract\n", buffer.granularity);
        std::exit(23);
    }
    buffer.owner = owner;
    buffer.role = role;
    buffer.allocation_bytes = MAX_BYTES;
    CUCK(cuMemAddressReserve(&buffer.address, MAX_BYTES, 0, 0, 0));
    CUCK(cuMemCreate(&buffer.handle, MAX_BYTES, &prop, 0));
    CUCK(cuMemMap(buffer.address, MAX_BYTES, 0, buffer.handle, 0));
    CUmemAccessDesc access[2]{};
    for (int i=0; i<2; ++i) {
        access[i].location.type = CU_MEM_LOCATION_TYPE_DEVICE;
        access[i].location.id = i;
        access[i].flags = CU_MEM_ACCESS_FLAGS_PROT_READWRITE;
    }
    CUCK(cuMemSetAccess(buffer.address, MAX_BYTES, access, 2));
    std::printf("PUSH_ALLOCATION owner=%d role=%s ptr=%p allocation_bytes=%zu granularity=%zu va_mod_4k=%llu va_mod_64k=%llu va_mod_2m=%llu\n",
        owner, role, (void *)buffer.address, MAX_BYTES, buffer.granularity,
        (unsigned long long)(buffer.address % 4096),
        (unsigned long long)(buffer.address % 65536),
        (unsigned long long)(buffer.address % 2097152));
}
static void release(Buffer &buffer) {
    CK(cudaSetDevice(buffer.owner));
    phase("allocation_free_begin", buffer.owner);
    CUCK(cuMemUnmap(buffer.address, buffer.allocation_bytes));
    CUCK(cuMemRelease(buffer.handle));
    CUCK(cuMemAddressFree(buffer.address, buffer.allocation_bytes));
    phase("allocation_free_done", buffer.owner);
}

static uint32_t word_pattern(size_t index, uint32_t seed) {
    uint32_t x = uint32_t(index) ^ seed;
    x ^= x >> 16;
    x *= 0x7feb352du;
    x ^= x >> 15;
    x *= 0x846ca68bu;
    x ^= x >> 16;
    return x;
}
static size_t compare(const std::vector<uint32_t> &got, const std::vector<uint32_t> &expected,
                      size_t words, const char *stage, int owner, int source, int destination,
                      size_t bytes, int iteration) {
    size_t mismatches = 0, first = words;
    for (size_t i=0; i<words; ++i) {
        if (got[i] != expected[i]) {
            if (first == words) first = i;
            ++mismatches;
        }
    }
    std::printf("FULL_COMPARE stage=%s owner=%d s=%d d=%d bytes=%zu iteration=%d checked_words=%zu mismatches=%zu valid=%d",
        stage, owner, source, destination, bytes, iteration, words, mismatches, mismatches == 0);
    if (mismatches) std::printf(" first_index=%zu first_got=%08x first_expected=%08x", first, got[first], expected[first]);
    std::printf("\n");
    return mismatches;
}
static void init_and_verify(const Buffer &buffer, const std::vector<uint32_t> &value,
                            std::vector<uint32_t> &observed, size_t bytes,
                            const char *stage, int source, int destination, int iteration) {
    CK(cudaSetDevice(buffer.owner));
    CK(cudaMemcpy((void *)buffer.address, value.data(), bytes, cudaMemcpyHostToDevice));
    CK(cudaDeviceSynchronize());
    CK(cudaMemcpy(observed.data(), (void *)buffer.address, bytes, cudaMemcpyDeviceToHost));
    CK(cudaDeviceSynchronize());
    if (compare(observed, value, bytes/sizeof(uint32_t), stage, buffer.owner,
                source, destination, bytes, iteration)) {
        phase("owner_validation_failed", source, destination);
        std::exit(24);
    }
}

int main() {
    setbuf(stdout, nullptr);
    kmsg_fd = open("/dev/kmsg", O_WRONLY | O_CLOEXEC);
    if (kmsg_fd < 0) std::printf("KMSG_UNAVAILABLE errno=%d\n", errno);
    phase("program_start");
    const uint64_t wall_start = ns_now();
    int count = 0;
    CK(cudaGetDeviceCount(&count));
    if (count != 2) { std::printf("FATAL expected_gpu_count=2 actual=%d\n", count); return 25; }
    CUCK(cuInit(0));
    for (int i=0; i<2; ++i) {
        cudaDeviceProp props{};
        char pci[32]{};
        CK(cudaGetDeviceProperties(&props, i));
        CK(cudaDeviceGetPCIBusId(pci, sizeof(pci), i));
        std::printf("PUSH_GPU index=%d name=%s pci=%s uuid=", i, props.name, pci);
        for (int n=0; n<16; ++n) std::printf("%02x", (unsigned char)props.uuid.bytes[n]);
        std::printf("\n");
        int can = 0;
        CK(cudaDeviceCanAccessPeer(&can, i, 1-i));
        std::printf("PUSH_PEER executor=%d peer=%d can=%d\n", i, 1-i, can);
        if (!can) return 26;
    }
    pcie_snapshot("push_global_before");
    phase("allocations_begin");
    for (int i=0; i<2; ++i) {
        allocate(send_buffer[i], i, "send");
        allocate(receive_buffer[i], i, "receive");
    }
    phase("allocations_done");
    cudaEvent_t begin[2], end[2];
    for (int i=0; i<2; ++i) {
        CK(cudaSetDevice(i));
        CK(cudaEventCreate(&begin[i]));
        CK(cudaEventCreate(&end[i]));
    }
    std::vector<uint32_t> expected(MAX_BYTES/4), poison(MAX_BYTES/4), observed(MAX_BYTES/4);
    const size_t sizes[] = {4, 4096, 65536, 1048576, MAX_BYTES};
    int failed_transfers = 0, completed_transfers = 0;
    for (size_t bytes : sizes) {
        const size_t words = bytes / sizeof(uint32_t);
        for (int iteration=0; iteration<3; ++iteration) {
            for (int source=0; source<2; ++source) {
                const int destination = 1-source;
                const uint32_t seed = 0x6b8b4567u ^ uint32_t(bytes) ^
                                      (0x9e3779b9u * uint32_t(iteration+1)) ^
                                      (0x13579bdfu * uint32_t(source+1));
                for (size_t i=0; i<words; ++i) {
                    expected[i] = word_pattern(i, seed);
                    poison[i] = ~expected[i];
                }
                std::printf("PUSH_CASE s=%d d=%d bytes=%zu iteration=%d seed=%08x\n", source, destination, bytes, iteration, seed);
                init_and_verify(send_buffer[source], expected, observed, bytes,
                                "source_initialized", source, destination, iteration);
                init_and_verify(receive_buffer[destination], poison, observed, bytes,
                                "destination_poisoned", source, destination, iteration);
                phase("owners_ready", source, destination);
                std::printf("PROBE_PTR s=%d d=%d src=%p dst=%p bytes=%zu iteration=%d\n",
                    source, destination, (void *)send_buffer[source].address,
                    (void *)receive_buffer[destination].address, bytes, iteration);
                CK(cudaSetDevice(source));
                const unsigned blocks = unsigned(std::min<size_t>(256, (words+255)/256));
                phase("push_begin", source, destination);
                const uint64_t start = ns_now();
                CK(cudaEventRecord(begin[source]));
                peer_push_kernel<<<blocks,256>>>((const uint32_t *)send_buffer[source].address,
                                                (volatile uint32_t *)receive_buffer[destination].address, words);
                CK(cudaGetLastError());
                CK(cudaEventRecord(end[source]));
                CK(cudaDeviceSynchronize());
                const uint64_t finish = ns_now();
                float gpu_ms = 0;
                CK(cudaEventElapsedTime(&gpu_ms, begin[source], end[source]));
                phase("push_complete", source, destination);
                CK(cudaSetDevice(destination));
                CK(cudaMemcpy(observed.data(), (void *)receive_buffer[destination].address, bytes, cudaMemcpyDeviceToHost));
                CK(cudaDeviceSynchronize());
                const size_t mismatches = compare(observed, expected, words, "peer_payload", destination,
                                                   source, destination, bytes, iteration);
                ++completed_transfers;
                if (mismatches) ++failed_transfers;
                std::printf("REMOTE_PUSH s=%d d=%d bytes=%zu iteration=%d seed=%08x valid=%d mismatches=%zu gpu_ms=%.6f wall_ms=%.6f\n",
                    source, destination, bytes, iteration, seed, mismatches == 0, mismatches,
                    double(gpu_ms), double(finish-start)/1000000.0);
                phase("comparison_done", source, destination);
            }
        }
    }
    pcie_snapshot("push_global_after");
    std::printf("PUSH_TOTAL completed=%d expected=30 failed=%d payload_max=%zu allocations=4 allocation_bytes_each=%zu wall_ms=%.6f\n",
        completed_transfers, failed_transfers, MAX_BYTES, MAX_BYTES, double(ns_now()-wall_start)/1000000.0);
    phase("data_done");
    for (int i=0; i<2; ++i) {
        release(send_buffer[i]);
        release(receive_buffer[i]);
        CK(cudaEventDestroy(begin[i]));
        CK(cudaEventDestroy(end[i]));
    }
    phase("context_exit_begin");
    if (kmsg_fd >= 0) close(kmsg_fd);
    return failed_transfers ? 5 : 0;
}
