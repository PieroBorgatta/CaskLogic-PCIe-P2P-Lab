#include "pcie_diag.h"
#include <algorithm>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>

static unsigned checks = 0;
static void expect(bool ok, const char *message) {
    ++checks;
    if (!ok) throw std::runtime_error(message);
}
static void put16(std::vector<unsigned char>& b, size_t o, unsigned v) {
    b.at(o) = v & 255; b.at(o + 1) = (v >> 8) & 255;
}
static void put32(std::vector<unsigned char>& b, size_t o, uint32_t v) {
    for (unsigned i = 0; i < 4; ++i) b.at(o + i) = (v >> (8 * i)) & 255;
}
static std::vector<unsigned char> fixture() {
    std::vector<unsigned char> b(4096);
    put16(b, 0, 0x8086); put16(b, 2, 0x466e);
    put16(b, 4, 0x0406); put16(b, 6, 0x0010);
    b[0x0e] = 1; b[0x34] = 0x40; b[0x40] = 0x10;
    put16(b, 0x42, 0x42); put16(b, 0x48, 0x2810);
    put32(b, 0x100, 0x0001001d); // DPC v1, no next capability.
    put16(b, 0x104, 0x0420); // RP extensions, four log DWORDs.
    put16(b, 0x106, 0x0000); put16(b, 0x108, 0x1000);
    put16(b, 0x10a, 0x0600); put32(b, 0x10c, 0x00010001);
    put32(b, 0x110, 0x00070707);
    for (unsigned i = 0; i < 4; ++i) put32(b, 0x120 + i * 4, 0x12345670 + i);
    return b;
}
static std::string render(const std::vector<unsigned char>& b, size_t claimed = 0) {
    FILE *tmp = std::tmpfile();
    if (!tmp) throw std::runtime_error("tmpfile");
    std::fflush(stdout);
    int saved = dup(STDOUT_FILENO);
    if (saved < 0 || dup2(fileno(tmp), STDOUT_FILENO) < 0)
        throw std::runtime_error("redirect stdout");
    cask_pci_decode(b.data(), claimed ? claimed : b.size());
    std::fflush(stdout);
    if (dup2(saved, STDOUT_FILENO) < 0) throw std::runtime_error("restore stdout");
    close(saved);
    std::rewind(tmp);
    std::string out; char chunk[1024]; size_t n;
    while ((n = std::fread(chunk, 1, sizeof(chunk), tmp))) out.append(chunk, n);
    std::fclose(tmp);
    return out;
}
static bool has(const std::string& s, const char *v) { return s.find(v) != std::string::npos; }

int main() {
    try {
        auto b = fixture(); auto s = render(b);
        expect(has(s, " COMMAND=0406"), "COMMAND absent");
        expect(has(s, " DEVCTL=2810"), "DEVCTL absent");
        expect(has(s, " DPC_CAP=100 DPC_VERSION=1"), "DPC capability absent");
        expect(has(s, " DPC_CTL=0000 DPC_STA=1000 DPC_SOURCE=0600"), "DPC words wrong");
        expect(has(s, " DPC_RP_EXT=1 DPC_PIO_LOG_DWORDS=4"), "DPC capabilities wrong");
        expect(has(s, " RP_PIO_STATUS=00010001 RP_PIO_MASK=00070707"), "RP PIO status wrong");
        expect(has(s, " RP_PIO_HEADER0=12345670") && has(s, " RP_PIO_HEADER3=12345673"), "header words wrong");
        put16(b, 0x104, 0x0400); s = render(b);
        expect(has(s, " DPC_RP_PIO=not_supported"), "RP extensions absence ignored");
        expect(!has(s, " RP_PIO_STATUS=") && !has(s, " RP_PIO_HEADER0="), "RP bank read without extensions");
        put16(b, 0x104, 0x0020); s = render(b);
        expect(has(s, " RP_PIO_STATUS=00010001"), "logsize0 hid valid status bank");
        expect(has(s, " RP_PIO_HEADER=unsupported_log_size") && !has(s, " RP_PIO_HEADER0="), "logsize0 header read");
        put16(b, 0x104, 0x0320); s = render(b);
        expect(!has(s, " RP_PIO_HEADER0="), "short declared log decoded");
        put16(b, 0x104, 0x0a20); s = render(b);
        expect(!has(s, " RP_PIO_HEADER0="), "unsupported future log decoded");
        put16(b, 0x104, 0xffff); s = render(b);
        expect(has(s, " DPC_RP_PIO=unavailable_capability") && !has(s, " RP_PIO_STATUS="), "unavailable capability decoded");
        b = fixture(); put32(b, 0x100, 0x0001000e); s = render(b);
        expect(has(s, " DPC=not_observed") && !has(s, " DPC_CAP="), "opaque words mistaken for DPC");
        b = fixture(); put32(b, 0x100, 0x0000001d); s = render(b);
        expect(has(s, " DPC=not_observed"), "zero capability version accepted");
        b = fixture(); put32(b, 0x100, 0x1001001d); s = render(b);
        expect(has(s, " EXTCAPS=cycle@100"), "extended self cycle unhandled");
        b = fixture(); put32(b, 0x100, 0x1801001d); put32(b, 0x180, 0x1001000e); s = render(b);
        expect(has(s, " EXTCAPS=cycle@100"), "extended multi-node cycle unhandled");
        b = fixture(); put32(b, 0x100, 0x1011001d); s = render(b);
        expect(has(s, " EXTCAPS=bad_or_short@101"), "unaligned extended pointer accepted");
        b = fixture(); put32(b, 0x100, 0x0fc1001d); s = render(b);
        expect(has(s, " EXTCAPS=bad_or_short@0fc"), "out-of-range extended pointer accepted");
        b = fixture(); b[0x40] = 0x05; b[0x41] = 0x40; s = render(b);
        expect(has(s, " PCIE=cap_cycle@040"), "standard capability cycle unhandled");
        b = fixture(); b.resize(0x105); s = render(b);
        expect(has(s, " DPC_CAPR=unread") && has(s, " DPC_RP_PIO=unread_capability"), "truncated DPC flags decoded");
        b = fixture(); b.resize(0x122); s = render(b);
        expect(has(s, " RP_PIO_HEADER0=unread") && has(s, " RP_PIO_HEADER3=unread"), "truncated header decoded");
        b = fixture(); put32(b, 0x100, 0x1201001d); put32(b, 0x120, 0x0001000e); s = render(b);
        expect(has(s, " RP_PIO_HEADER0=unread"), "read into following capability");
        b = fixture(); put32(b, 0x100, 0x18010001); put32(b, 0x180, 0x0001001d); put16(b, 0x184, 0x0020); s = render(b);
        expect(has(s, " AER_CAP=100") && has(s, " DPC_CAP=180"), "AER/DPC coexistence failed");
        b = fixture(); s = render(b, 8192);
        expect(has(s, " RP_PIO_HEADER3=12345673"), "4096-byte cap failed");
        const auto full = fixture();
        for (size_t n = 0; n <= 4096; ++n) {
            const std::vector<unsigned char> short_buffer(full.begin(), full.begin() + n);
            (void)render(short_buffer); // Real short buffers, covered by ASan/UBSan.
        }
        std::printf("PASS %u assertions; all 4097 actual truncation lengths decoded without out-of-bounds access.\n", checks);
        return 0;
    } catch (const std::exception& e) {
        std::fprintf(stderr, "FAIL: %s\n", e.what()); return 1;
    }
}
