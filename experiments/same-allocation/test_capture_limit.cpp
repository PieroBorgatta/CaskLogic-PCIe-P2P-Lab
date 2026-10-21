#include "payload_capture.h"
#include <fstream>
#include <iterator>
#include <iostream>

// CPU check for the two changes to the previously tested capture header.
int main() {
    char root[] = "/tmp/casklogic-same-allocation-XXXXXX";
    if (!mkdtemp(root)) return 1;
    const std::string directory = std::string(root) + "/payloads";
    payload_capture::Capture capture(directory.c_str());
    const std::vector<uint32_t> expected{0x12345678u}, sentinel{0xedcba987u};
    auto result = capture.save(36, false, "PUSH", 0, 1, 0, 4, 0, 0x1000, 0x2000,
                               expected, expected, sentinel);
    if (result.correct != 1 || result.other || result.sentinel) return 2;
    std::ifstream input(directory + "/case-036.json");
    std::string metadata(std::istreambuf_iterator<char>(input), {});
    if (metadata.find("\"case_id\":36") == std::string::npos ||
        metadata.find("\"same_allocations_across_modes\":true") == std::string::npos)
        return 3;
    bool rejected = false;
    try { capture.save(37, false, "PUSH", 0, 1, 0, 4, 0, 0x1000, 0x2000,
                       expected, expected, sentinel); }
    catch (const std::runtime_error& error) {
        rejected = std::string(error.what()) == "payload_case_contract";
    }
    if (!rejected) return 4;
    std::cout << "PASS case 36 accepted; case 37 rejected; shared allocation metadata; fixtures="
              << root << '\n';
}
