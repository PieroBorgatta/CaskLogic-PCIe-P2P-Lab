#ifndef CASKLOGIC_PAYLOAD_CAPTURE_H
#define CASKLOGIC_PAYLOAD_CAPTURE_H

// Host-only capture after the existing synchronized destination readback.
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <stdexcept>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>

namespace payload_capture {
struct Summary {
    size_t correct = 0, sentinel = 0, other = 0, first = 0, last = 0;
};
inline Summary classify(const std::vector<uint32_t>& got,
                        const std::vector<uint32_t>& expected,
                        const std::vector<uint32_t>& sentinel, size_t words) {
    if (!words || words > got.size() || words > expected.size() || words > sentinel.size())
        throw std::runtime_error("payload_capture_bounds");
    Summary s; s.first = s.last = words;
    for (size_t i = 0; i < words; ++i) {
        if (sentinel[i] != ~expected[i]) throw std::runtime_error("payload_sentinel_contract");
        if (got[i] == expected[i]) ++s.correct;
        else {
            if (s.first == words) s.first = i;
            s.last = i;
            if (got[i] == sentinel[i]) ++s.sentinel;
            else ++s.other;
        }
    }
    return s;
}

class Capture {
    int directory_fd_ = -1;
    void write_file(const char* name, const void* data, size_t size) {
        int fd = openat(directory_fd_, name, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
        if (fd < 0) throw std::runtime_error("payload_file_create_failed");
        const unsigned char* p = static_cast<const unsigned char*>(data);
        size_t left = size;
        while (left) {
            const ssize_t n = write(fd, p, left);
            if (n < 0 && errno == EINTR) continue;
            if (n <= 0) { close(fd); throw std::runtime_error("payload_file_write_failed"); }
            p += n; left -= size_t(n);
        }
        if (fsync(fd)) { close(fd); throw std::runtime_error("payload_file_sync_failed"); }
        if (close(fd)) throw std::runtime_error("payload_file_close_failed");
    }
public:
    explicit Capture(const char* directory) {
        if (!directory || !*directory || mkdir(directory, 0700))
            throw std::runtime_error("payload_directory_must_be_new");
        directory_fd_ = open(directory, O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
        if (directory_fd_ < 0) throw std::runtime_error("payload_directory_open_failed");
    }
    ~Capture() { if (directory_fd_ >= 0) close(directory_fd_); }
    Capture(const Capture&) = delete;
    Capture& operator=(const Capture&) = delete;

    Summary save(uint64_t id, bool ce, const char* mode, int source, int destination,
                 int executor, size_t bytes, uint32_t seed, uint64_t source_va,
                 uint64_t destination_va, const std::vector<uint32_t>& got,
                 const std::vector<uint32_t>& expected, const std::vector<uint32_t>& sentinel) {
        if (!id || id > 24 || !mode || (std::strcmp(mode, "PUSH") && std::strcmp(mode, "PULL")) ||
            source < 0 || source > 1 || destination != 1-source ||
            executor != (!std::strcmp(mode, "PUSH") ? source : destination) ||
            !bytes || bytes > 8*1024*1024 || bytes % 4)
            throw std::runtime_error("payload_case_contract");
        const size_t words = bytes/4;
        const Summary s = classify(got, expected, sentinel, words);
        std::vector<unsigned char> raw(bytes);
        for (size_t i=0; i<words; ++i)
            for (unsigned j=0; j<4; ++j) raw[4*i+j] = static_cast<unsigned char>(got[i] >> (8*j));
        char raw_name[80], json_name[80], metadata[2048], first[32], last[32];
        std::snprintf(raw_name, sizeof(raw_name), "case-%03llu.observed.u32le", (unsigned long long)id);
        std::snprintf(json_name, sizeof(json_name), "case-%03llu.json", (unsigned long long)id);
        if (s.first == words) { std::strcpy(first, "null"); std::strcpy(last, "null"); }
        else { std::snprintf(first, sizeof(first), "%zu", s.first); std::snprintf(last, sizeof(last), "%zu", s.last); }
        const int n = std::snprintf(metadata, sizeof(metadata),
            "{\n  \"schema_version\":1,\"case_id\":%llu,\"engine\":\"%s\",\"mode\":\"%s\",\n"
            "  \"source\":%d,\"destination\":%d,\"executor\":%d,\"bytes\":%zu,\"seed\":\"%08x\",\n"
            "  \"observed_file\":\"%s\",\"pattern\":\"mix32-index-xor-seed-v1\",\n"
            "  \"sentinel\":\"bitwise-not-expected\",\"byte_order\":\"little\",\"word_bytes\":4,\n"
            "  \"source_va\":\"%llx\",\"destination_va\":\"%llx\",\n"
            "  \"first_mismatch_word\":%s,\"last_mismatch_word\":%s,\n"
            "  \"correct_words\":%zu,\"sentinel_match_words\":%zu,\"other_words\":%zu,\n"
            "  \"direct_route_proven\":false,\"same_allocations_across_modes\":false\n}\n",
            (unsigned long long)id, ce?"CE_REQUEST":"SM", mode, source, destination, executor,
            bytes, seed, raw_name, (unsigned long long)source_va, (unsigned long long)destination_va,
            first, last, s.correct, s.sentinel, s.other);
        if (n <= 0 || size_t(n) >= sizeof(metadata)) throw std::runtime_error("payload_metadata_overflow");
        // Metadata is a completion marker; it is never created before raw data is durable.
        write_file(raw_name, raw.data(), raw.size());
        write_file(json_name, metadata, size_t(n));
        if (fsync(directory_fd_)) throw std::runtime_error("payload_directory_sync_failed");
        std::printf("PAYLOAD_CAPTURE id=%llu correct_words=%zu sentinel_match_words=%zu other_words=%zu first_mismatch_word=%s last_mismatch_word=%s observed_file=%s complete=1\n",
            (unsigned long long)id, s.correct, s.sentinel, s.other, first, last, raw_name);
        return s;
    }
};
} // namespace payload_capture
#endif
