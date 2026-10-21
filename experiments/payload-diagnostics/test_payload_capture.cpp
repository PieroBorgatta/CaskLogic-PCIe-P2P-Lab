#include "payload_capture.h"

#include <cstdlib>
#include <fstream>
#include <functional>
#include <iostream>
#include <iterator>
#include <sys/stat.h>

// CPU-only contract tests. They never load CUDA, access a GPU, or overwrite an
// output directory. Successful runs retain their small fixtures for inspection.
namespace {
unsigned checks = 0;

void require(bool condition, const char* message) {
    ++checks;
    if (!condition) throw std::runtime_error(message);
}

void rejects(const std::function<void()>& call, const char* reason) {
    bool rejected = false;
    try { call(); }
    catch (const std::runtime_error& error) {
        rejected = true;
        require(std::string(error.what()) == reason, "unexpected rejection reason");
    }
    require(rejected, "invalid operation was accepted");
}

std::string contents(const std::string& path) {
    std::ifstream input(path, std::ios::binary);
    require(bool(input), "fixture cannot be read");
    return std::string(std::istreambuf_iterator<char>(input), {});
}

bool exists(const std::string& path) {
    struct stat info{};
    return lstat(path.c_str(), &info) == 0;
}

void private_mode(const std::string& path, unsigned expected) {
    struct stat info{};
    require(stat(path.c_str(), &info) == 0, "fixture stat failed");
    require((info.st_mode & 0777u) == expected, "fixture permissions are not private");
}

uint32_t pattern(uint32_t index, uint32_t seed) {
    uint32_t x = index ^ seed;
    x ^= x >> 16;
    x *= 0x7feb352du;
    x ^= x >> 15;
    x *= 0x846ca68bu;
    x ^= x >> 16;
    return x;
}

void check_summary(const payload_capture::Summary& summary, size_t correct,
                   size_t sentinel, size_t other, size_t first, size_t last) {
    require(summary.correct == correct, "wrong correct count");
    require(summary.sentinel == sentinel, "wrong sentinel count");
    require(summary.other == other, "wrong other count");
    require(summary.first == first, "wrong first mismatch");
    require(summary.last == last, "wrong last mismatch");
}

void require_field(const std::string& json, const char* field) {
    require(json.find(field) != std::string::npos, "metadata field differs");
}

void tests(const std::string& parent) {
    using payload_capture::Capture;
    using payload_capture::classify;
    constexpr uint32_t seed = 0x12345678u;
    std::vector<uint32_t> expected(8), sentinel(8);
    for (size_t i = 0; i < expected.size(); ++i) {
        expected[i] = pattern(uint32_t(i), seed);
        sentinel[i] = ~expected[i];
    }

    check_summary(classify(expected, expected, sentinel, 8), 8, 0, 0, 8, 8);
    check_summary(classify(sentinel, expected, sentinel, 8), 0, 8, 0, 0, 7);
    for (uint32_t constant : {0u, 0xffffffffu}) {
        for (size_t i = 0; i < 8; ++i)
            require(constant != expected[i] && constant != sentinel[i],
                    "constant fixture overlaps expected or sentinel");
        check_summary(classify(std::vector<uint32_t>(8, constant), expected,
                               sentinel, 8), 0, 0, 8, 0, 7);
    }

    std::vector<uint32_t> mixed = expected;
    mixed[1] = sentinel[1];
    mixed[2] = 0x11223344u;
    mixed[3] = 0x89abcdefu;
    mixed[5] = sentinel[5];
    mixed[6] = 0x01020304u;
    for (size_t i : {2u, 3u, 6u})
        require(mixed[i] != expected[i] && mixed[i] != sentinel[i],
                "other fixture overlaps expected or sentinel");
    check_summary(classify(mixed, expected, sentinel, 8), 3, 2, 3, 1, 6);
    check_summary(classify(mixed, expected, sentinel, 1), 1, 0, 0, 1, 1);

    // An initial-sentinel match can simultaneously match a source word at a
    // different index. The primary partition must still count the value match.
    const std::vector<uint32_t> alias_expected{0x11223344u, 0xeeddccbbu};
    const std::vector<uint32_t> alias_sentinel{0xeeddccbbu, 0x11223344u};
    check_summary(classify(alias_sentinel, alias_expected, alias_sentinel, 2),
                  0, 2, 0, 0, 1);

    rejects([&] { classify(mixed, expected, sentinel, 0); }, "payload_capture_bounds");
    rejects([&] { classify(mixed, expected, sentinel, 9); }, "payload_capture_bounds");
    rejects([&] { classify({}, expected, sentinel, 1); }, "payload_capture_bounds");
    rejects([&] { classify(mixed, {}, sentinel, 1); }, "payload_capture_bounds");
    rejects([&] { classify(mixed, expected, {}, 1); }, "payload_capture_bounds");
    auto invalid_sentinel = sentinel;
    invalid_sentinel[7] = expected[7];
    rejects([&] { classify(expected, expected, invalid_sentinel, 8); },
            "payload_sentinel_contract");

    const std::string output = parent + "/capture";
    Capture capture(output.c_str());
    private_mode(output, 0700);
    check_summary(capture.save(1, false, "PUSH", 0, 1, 0, 32, seed,
                               0x123456780000ULL, 0x234567890000ULL,
                               mixed, expected, sentinel), 3, 2, 3, 1, 6);
    const std::string raw_path = output + "/case-001.observed.u32le";
    const std::string json_path = output + "/case-001.json";
    const std::string raw = contents(raw_path);
    const std::string json = contents(json_path);
    require(raw.size() == 32, "raw file has wrong active length");
    // Explicit non-palindromic bytes check the actual on-disk byte order.
    require(raw.substr(8, 4) == std::string("\x44\x33\x22\x11", 4),
            "word 2 is not little endian");
    require(raw.substr(12, 4) == std::string("\xef\xcd\xab\x89", 4),
            "word 3 is not little endian");
    require(raw.substr(24, 4) == std::string("\x04\x03\x02\x01", 4),
            "word 6 is not little endian");
    for (size_t i = 0; i < 8; ++i) {
        uint32_t word = 0;
        for (unsigned j = 0; j < 4; ++j)
            word |= uint32_t(static_cast<unsigned char>(raw[4*i+j])) << (8*j);
        require(word == mixed[i], "raw file changed observed payload");
    }
    private_mode(raw_path, 0600);
    private_mode(json_path, 0600);
    for (const char* field : {
            "\"schema_version\":1", "\"case_id\":1", "\"engine\":\"SM\"",
            "\"mode\":\"PUSH\"", "\"source\":0", "\"destination\":1",
            "\"executor\":0", "\"bytes\":32", "\"seed\":\"12345678\"",
            "\"observed_file\":\"case-001.observed.u32le\"",
            "\"pattern\":\"mix32-index-xor-seed-v1\"",
            "\"sentinel\":\"bitwise-not-expected\"", "\"byte_order\":\"little\"",
            "\"word_bytes\":4", "\"source_va\":\"123456780000\"",
            "\"destination_va\":\"234567890000\"", "\"first_mismatch_word\":1",
            "\"last_mismatch_word\":6", "\"correct_words\":3",
            "\"sentinel_match_words\":2", "\"other_words\":3",
            "\"direct_route_proven\":false", "\"same_allocations_across_modes\":false"})
        require_field(json, field);

    check_summary(capture.save(2, true, "PULL", 0, 1, 1, 32, seed,
                               0x123456780000ULL, 0x234567890000ULL,
                               expected, expected, sentinel), 8, 0, 0, 8, 8);
    const auto correct_json = contents(output + "/case-002.json");
    for (const char* field : {"\"engine\":\"CE_REQUEST\"", "\"mode\":\"PULL\"",
            "\"executor\":1", "\"first_mismatch_word\":null",
            "\"last_mismatch_word\":null", "\"correct_words\":8"})
        require_field(correct_json, field);

    rejects([&] { Capture duplicate(output.c_str()); }, "payload_directory_must_be_new");
    rejects([&] { Capture invalid(nullptr); }, "payload_directory_must_be_new");
    rejects([&] { Capture invalid(""); }, "payload_directory_must_be_new");
    rejects([&] { capture.save(1, true, "PUSH", 0, 1, 0, 32, seed, 1, 2,
                               expected, expected, sentinel); }, "payload_file_create_failed");
    require(contents(raw_path) == raw, "duplicate capture altered raw data");
    require(contents(json_path) == json, "duplicate capture altered metadata");

    const auto save_invalid = [&](uint64_t id, const char* mode, int source,
                                  int destination, int executor, size_t bytes) {
        capture.save(id, false, mode, source, destination, executor, bytes, seed,
                     1, 2, mixed, expected, sentinel);
    };
    rejects([&] { save_invalid(0, "PUSH", 0, 1, 0, 32); }, "payload_case_contract");
    rejects([&] { save_invalid(25, "PUSH", 0, 1, 0, 32); }, "payload_case_contract");
    rejects([&] { save_invalid(3, nullptr, 0, 1, 0, 32); }, "payload_case_contract");
    rejects([&] { save_invalid(3, "INVALID", 0, 1, 0, 32); }, "payload_case_contract");
    rejects([&] { save_invalid(3, "PUSH", -1, 1, 0, 32); }, "payload_case_contract");
    rejects([&] { save_invalid(3, "PUSH", 0, 0, 0, 32); }, "payload_case_contract");
    rejects([&] { save_invalid(3, "PULL", 0, 1, 0, 32); }, "payload_case_contract");
    for (size_t bytes : {size_t(0), size_t(3), size_t(8*1024*1024+4)})
        rejects([&] { save_invalid(3, "PUSH", 0, 1, 0, bytes); }, "payload_case_contract");
    rejects([&] { save_invalid(3, "PUSH", 0, 1, 0, 36); }, "payload_capture_bounds");
    rejects([&] { capture.save(3, false, "PUSH", 0, 1, 0, 32, seed, 1, 2,
                               mixed, expected, invalid_sentinel); }, "payload_sentinel_contract");
    require(!exists(output + "/case-003.observed.u32le"), "invalid input created raw data");
    require(!exists(output + "/case-003.json"), "invalid input created completion marker");

    // A pre-existing symlink cannot redirect a raw-file write outside the run.
    const std::string protected_path = parent + "/protected.txt";
    { std::ofstream file(protected_path); file << "preserve me\n"; }
    require(symlink(protected_path.c_str(), (output + "/case-003.observed.u32le").c_str()) == 0,
            "symlink fixture creation failed");
    rejects([&] { save_invalid(3, "PUSH", 0, 1, 0, 32); }, "payload_file_create_failed");
    require(contents(protected_path) == "preserve me\n", "symlink target was changed");
    require(!exists(output + "/case-003.json"), "failed capture created completion marker");

    std::cout << "PASS checks=" << checks << " fixtures=" << parent << '\n';
}
} // namespace

int main(int argc, char** argv) {
    try {
        std::string parent;
        if (argc == 1) {
            char temporary[] = "/tmp/casklogic-payload-capture-test-XXXXXX";
            char* result = mkdtemp(temporary);
            if (!result) throw std::runtime_error("mkdtemp failed");
            parent = result;
        } else if (argc == 2) {
            parent = argv[1];
            if (parent.empty() || mkdir(parent.c_str(), 0700))
                throw std::runtime_error("test output parent must be new");
        } else {
            throw std::runtime_error("usage: test_payload_capture [NEW_OUTPUT_PARENT]");
        }
        char* canonical = realpath(parent.c_str(), nullptr);
        if (!canonical) throw std::runtime_error("test output parent resolution failed");
        parent = canonical;
        std::free(canonical);
        tests(parent);
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "FAIL " << error.what() << '\n';
        return 1;
    }
}
