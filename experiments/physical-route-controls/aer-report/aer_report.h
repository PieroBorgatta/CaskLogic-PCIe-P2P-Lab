#ifndef CASKLOGIC_AER_REPORT_H
#define CASKLOGIC_AER_REPORT_H
// Native-only error reporting. Never clears status, enables interrupts,
// changes routing/address windows, changes DPC, or writes vendor registers.
// 16-bit writes to Device Control do NOT touch adjacent RW1C Device Status.
#include <stdexcept>
#include <cstdint>
#include <cstdio>
#include <fcntl.h>
#include <unistd.h>

namespace cask_aer {
constexpr uint16_t REPORT_MASK = 0x000a; // NFERE | URRE, PCI_EXP_DEVCTL.
constexpr uint32_t UEM_MASK = 0x00010000; // Unexpected Completion, PEG only.
inline uint16_t desired_devctl(uint16_t before) { return before | REPORT_MASK; }
inline uint16_t restore_devctl(uint16_t now, uint16_t before) {
    return (now & ~REPORT_MASK) | (before & REPORT_MASK);
}
inline uint32_t restore_uem(uint32_t now, uint32_t before) {
    return (now & ~UEM_MASK) | (before & UEM_MASK);
}
struct Record {
    const char *bdf;
    uint32_t id;
    unsigned cap, aer, type;
    int fd = -1;
    uint16_t old_ctl = 0;
    uint32_t old_uem = 0;
    bool owned = false;
};
class Scope {
    Record records[6] = {
        {"0000:00:01.0",0x460d8086,0x40,0x100,4},
        {"0000:00:07.0",0x466e8086,0x40,0x100,4},
        {"0000:04:00.0",0x24611b21,0x80,0x100,5},
        {"0000:05:00.0",0x24611b21,0x80,0x100,6},
        {"0000:01:00.0",0x28b010de,0x78,0x420,1},
        {"0000:06:00.0",0x257110de,0x78,0x420,1}
    };
    bool active = false;
    template<class T> static T read(Record &r,unsigned off) {
        T v = 0;
        if (pread(r.fd,&v,sizeof(v),off) != ssize_t(sizeof(v))) throw std::runtime_error("aer_config_read");
        return v;
    }
    template<class T> static void write(Record &r,unsigned off,T value) {
        if (pwrite(r.fd,&value,sizeof(value),off) != ssize_t(sizeof(value))) throw std::runtime_error("aer_config_write");
        if (read<T>(r,off) != value) throw std::runtime_error("aer_config_readback");
    }
    void log(Record &r,const char *phase) {
        std::printf("CASKAER phase=%s bdf=%s id=%08x cap=%03x aer=%03x type=%u old_devctl=%04x devctl=%04x old_uem=%08x uem=%08x ues=%08x ces=%08x capctl=%08x header0=%08x header1=%08x header2=%08x header3=%08x",
            phase,r.bdf,r.id,r.cap,r.aer,r.type,r.old_ctl,read<uint16_t>(r,r.cap+8),r.old_uem,
            read<uint32_t>(r,r.aer+8),read<uint32_t>(r,r.aer+4),read<uint32_t>(r,r.aer+0x10),
            read<uint32_t>(r,r.aer+0x18),read<uint32_t>(r,r.aer+0x1c),read<uint32_t>(r,r.aer+0x20),
            read<uint32_t>(r,r.aer+0x24),read<uint32_t>(r,r.aer+0x28));
        if (r.type == 4)
            std::printf(" rootctl=%04x rootcmd=%08x rootsta=%08x rootsource=%08x",
                read<uint16_t>(r,r.cap+0x1c),read<uint32_t>(r,r.aer+0x2c),
                read<uint32_t>(r,r.aer+0x30),read<uint32_t>(r,r.aer+0x34));
        std::printf(" status_clears=0 interrupt_enables=0\n");
    }
public:
    void begin() {
        if (active) throw std::runtime_error("aer_duplicate_begin");
        // Finish ALL identity and system-error guards before ANY write.
        for (auto &r:records) {
            char path[100]; std::snprintf(path,sizeof(path),"/sys/bus/pci/devices/%s/config",r.bdf);
            r.fd = open(path,O_RDWR|O_CLOEXEC);
            if (r.fd < 0 || read<uint32_t>(r,0) != r.id ||
                (read<uint16_t>(r,r.cap)&0xff) != 0x10 ||
                ((read<uint16_t>(r,r.cap+2)>>4)&0xf) != r.type ||
                (read<uint32_t>(r,r.aer)&0xffff) != 1 ||
                (read<uint16_t>(r,4)&0x100)) throw std::runtime_error("aer_identity_or_serr_guard");
            if (r.type == 4 && ((read<uint16_t>(r,r.cap+0x1c)&7) || (read<uint32_t>(r,r.aer+0x2c)&7)))
                throw std::runtime_error("aer_root_interrupt_guard");
            if (r.id == 0x466e8086 && ((read<uint32_t>(r,0xa00)&0xffff) != 0x1d || (read<uint16_t>(r,0xa06)&3)))
                throw std::runtime_error("aer_dpc_guard");
            r.old_ctl = read<uint16_t>(r,r.cap+8);
            r.old_uem = read<uint32_t>(r,r.aer+8);
            log(r,"saved");
        }
        active = true;
        for (auto &r:records) {
            r.owned = true; // Roll back even if the following write/readback fails.
            write<uint16_t>(r,r.cap+8,desired_devctl(r.old_ctl));
            if (r.id == 0x460d8086) write<uint32_t>(r,r.aer+8,r.old_uem & ~UEM_MASK);
            log(r,"enabled");
        }
        std::printf("CASKAER_BEGIN devices=6 devctl_mask=000a peg_unmask=00010000 status_clears=0 interrupt_enables=0\n");
    }
    bool restore() noexcept {
        bool ok = true;
        if (active) {
            for (auto &r:records) if (r.owned) {
                try {
                    log(r,"pre_restore");
                    const auto ctl = read<uint16_t>(r,r.cap+8);
                    const auto uem = read<uint32_t>(r,r.aer+8);
                    const bool other_bits_stable = (ctl & ~REPORT_MASK) == (r.old_ctl & ~REPORT_MASK) &&
                        (r.id == 0x460d8086 ? (uem & ~UEM_MASK) == (r.old_uem & ~UEM_MASK) : uem == r.old_uem);
                    write<uint16_t>(r,r.cap+8,restore_devctl(ctl,r.old_ctl));
                    if (r.id == 0x460d8086) write<uint32_t>(r,r.aer+8,restore_uem(uem,r.old_uem));
                    log(r,"restored");
                    ok &= other_bits_stable;
                    r.owned = false;
                } catch (...) { ok = false; }
            }
            std::printf("CASKAER_END restored=%d devices=6 status_clears=0 interrupt_enables=0\n",int(ok));
        }
        active = false;
        for (auto &r:records) if (r.fd >= 0) { close(r.fd); r.fd = -1; }
        return ok;
    }
    ~Scope() { restore(); }
};
} // namespace cask_aer
#endif
