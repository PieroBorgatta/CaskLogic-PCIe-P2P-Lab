#pragma once
// Finite experiment specification. Host-only and independent of CUDA/driver IO.
#include <cstdint>
#include <stdexcept>
namespace physical_pull_protocol {
constexpr unsigned CASES = 12;
constexpr uint64_t ALLOCATION_BYTES = 8ULL * 1024 * 1024;
enum class Transfer { SM, PHYSICAL_PUSH, PHYSICAL_PULL };
struct Case {
    unsigned id, group, step;
    int executor, source, destination;
    Transfer transfer;
    unsigned source_mode, destination_mode;
    uint32_t seed;
    const char* name;
    const char* mode;
    bool physical() const { return transfer != Transfer::SM; }
};
inline uint32_t pattern(uint32_t index, uint32_t seed) {
    uint32_t x=index^seed;x^=x>>16;x*=0x7feb352du;x^=x>>15;x*=0x846ca68bu;x^=x>>16;return x;
}
inline Case describe(unsigned id) {
    if(!id || id>CASES)throw std::runtime_error("physical_pull_case_range");
    const unsigned step=(id-1)%6;
    const int executor=id<=6?1:0;
    const bool pull=step==2 || step==3 || step==4;
    static const char*names[]={"SM_PUSH_BEFORE","PHYS_PUSH_CONTROL","PHYS_PULL_NC","PHYS_PULL_COH","SM_PULL","SM_PUSH_AFTER"};
    Case c{id,(id-1)/6+1,step,executor,pull?1-executor:executor,pull?executor:1-executor,
           step==1?Transfer::PHYSICAL_PUSH:(step==2||step==3)?Transfer::PHYSICAL_PULL:Transfer::SM,
           step==2?2U:step==3?1U:0U,step==1?2U:0U,
           0x4287a1c9u^(0x13579bdfu*uint32_t(executor+1))^(uint32_t(id)*0x9e3779b9u),
           names[step],pull?"PULL":"PUSH"};
    return c;
}
} // namespace physical_pull_protocol
