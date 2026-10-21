#ifndef CASKLOGIC_PCIE_DIAG_H
#define CASKLOGIC_PCIE_DIAG_H

// Sonda esclusivamente in lettura: non cancella status sticky e non modifica PCI.
#include <cstdio>
#include <cstdint>
#include <cstddef>
#include <cerrno>
#include <ctime>
#include <fcntl.h>
#include <unistd.h>

static inline bool cask_pci_fits(size_t n, size_t off, size_t width) {
    return off <= n && width <= n - off;
}
static inline uint16_t cask_pci_u16(const unsigned char *b, size_t off) {
    return uint16_t(b[off]) | (uint16_t(b[off + 1]) << 8);
}
static inline uint32_t cask_pci_u32(const unsigned char *b, size_t off) {
    return uint32_t(b[off]) | (uint32_t(b[off + 1]) << 8) |
           (uint32_t(b[off + 2]) << 16) | (uint32_t(b[off + 3]) << 24);
}
static inline void cask_pci_field32(const unsigned char *b, size_t n,
                                  size_t off, const char *name) {
    if (cask_pci_fits(n, off, 4))
        std::printf(" %s=%08x", name, unsigned(cask_pci_u32(b, off)));
    else
        std::printf(" %s=unread", name);
}

// Ritorna il tipo PCIe solo se la capability standard è leggibile e valida.
static inline int cask_pci_standard(const unsigned char *b, size_t n) {
    if (!cask_pci_fits(n, 0x34, 1) || !cask_pci_fits(n, 0x06, 2)) {
        std::printf(" PCIE=short_config"); return -1;
    }
    std::printf(" PCI_STATUS=%04x", unsigned(cask_pci_u16(b, 0x06)));
    if (!(cask_pci_u16(b, 0x06) & 0x10)) {
        std::printf(" PCIE=no_cap_list"); return -1;
    }
    bool seen[256] = {};
    unsigned pos = b[0x34];
    for (unsigned steps = 0; pos && steps < 64; ++steps) {
        if (pos < 0x40 || pos > 0xfc || (pos & 3) ||
            !cask_pci_fits(n, pos, 2)) {
            std::printf(" PCIE=bad_or_short_cap@%03x", pos); return -1;
        }
        if (seen[pos]) {
            std::printf(" PCIE=cap_cycle@%03x", pos); return -1;
        }
        seen[pos] = true;
        if (b[pos] == 0x10) {
            if (!cask_pci_fits(n, pos + 2, 2)) {
                std::printf(" PCIE=short_flags@%03x", pos); return -1;
            }
            const uint16_t flags = cask_pci_u16(b, pos + 2);
            const unsigned version = flags & 0xf;
            const int type = (flags >> 4) & 0xf;
            std::printf(" PCIE_CAP=%03x PCIE_VERSION=%u PCIE_TYPE=%d", pos, version, type);
            if (!version) { std::printf(" PCIE=invalid_version"); return -1; }
            if (cask_pci_fits(n, pos + 0x0a, 2))
                std::printf(" DEVSTA=%04x", unsigned(cask_pci_u16(b, pos + 0x0a)));
            else std::printf(" DEVSTA=unread");
            return type;
        }
        pos = b[pos + 1];
    }
    std::printf(" PCIE=%s", pos ? "cap_limit" : "absent");
    return -1;
}

static inline void cask_pci_decode(const unsigned char *b, size_t n) {
    if (n > 4096) n = 4096;
    if (cask_pci_fits(n, 0, 4)) {
        std::printf(" VID=%04x DID=%04x", unsigned(cask_pci_u16(b, 0)),
                    unsigned(cask_pci_u16(b, 2)));
        if (cask_pci_u16(b, 0) == 0xffff || cask_pci_u16(b, 0) == 0) {
            std::printf(" CONFIG=unavailable"); return;
        }
    } else { std::printf(" CONFIG=short_header"); return; }
    const int type = cask_pci_standard(b, n);
    if (cask_pci_fits(n, 0x1e, 2) && (b[0x0e] & 0x7f) == 1)
        std::printf(" SECONDARY_STATUS=%04x", unsigned(cask_pci_u16(b, 0x1e)));
    bool seen[1024] = {};
    unsigned pos = 0x100;
    bool found = false;
    for (unsigned steps = 0; steps < 1024; ++steps) {
        if (pos < 0x100 || pos > 0xffc || (pos & 3) ||
            !cask_pci_fits(n, pos, 4)) {
            std::printf(" EXTCAPS=bad_or_short@%03x", pos); break;
        }
        if (seen[pos / 4]) { std::printf(" EXTCAPS=cycle@%03x", pos); break; }
        seen[pos / 4] = true;
        const uint32_t header = cask_pci_u32(b, pos);
        if (header == 0 || header == 0xffffffff) {
            std::printf(" EXTCAPS=end@%03x", pos); break;
        }
        const unsigned id = header & 0xffff;
        const unsigned version = (header >> 16) & 0xf;
        if (id == 1 && version) {
            found = true;
            std::printf(" AER_CAP=%03x AER_VERSION=%u", pos, version);
            cask_pci_field32(b, n, pos + 0x04, "UES");
            cask_pci_field32(b, n, pos + 0x08, "UEM");
            cask_pci_field32(b, n, pos + 0x0c, "UESEV");
            cask_pci_field32(b, n, pos + 0x10, "CES");
            cask_pci_field32(b, n, pos + 0x14, "CEM");
            cask_pci_field32(b, n, pos + 0x18, "AER_CAPCTL");
            cask_pci_field32(b, n, pos + 0x1c, "HEADER0");
            cask_pci_field32(b, n, pos + 0x20, "HEADER1");
            cask_pci_field32(b, n, pos + 0x24, "HEADER2");
            cask_pci_field32(b, n, pos + 0x28, "HEADER3");
            if (type == 4) {
                cask_pci_field32(b, n, pos + 0x2c, "ROOTCMD");
                cask_pci_field32(b, n, pos + 0x30, "ROOTSTA");
                cask_pci_field32(b, n, pos + 0x34, "ROOTSOURCE");
            }
        }
        const unsigned next = header >> 20;
        if (!next) break;
        pos = next;
    }
    if (!found) std::printf(" AER=not_observed");
}

static inline void pcie_snapshot(const char *label) {
    static const char *const devices[] = {
        "0000:00:01.0", "0000:00:07.0", "0000:04:00.0",
        "0000:05:00.0", "0000:01:00.0", "0000:06:00.0"
    };
    for (const char *device : devices) {
        struct timespec ts = {};
        const int clock_rc = clock_gettime(CLOCK_MONOTONIC, &ts);
        char path[128];
        const int plen = std::snprintf(path, sizeof(path),
                                      "/sys/bus/pci/devices/%s/config", device);
        std::printf("PCIE_SNAPSHOT phase=%s monotonic=%lld.%09ld clock_ok=%d bdf=%s",
                    label ? label : "unspecified", (long long)ts.tv_sec,
                    ts.tv_nsec, clock_rc == 0, device);
        if (plen < 0 || size_t(plen) >= sizeof(path)) {
            std::printf(" ERROR=path_length\n"); continue;
        }
        const int fd = open(path, O_RDONLY | O_CLOEXEC);
        if (fd < 0) { std::printf(" OPEN_ERRNO=%d\n", errno); continue; }
        unsigned char config[4096] = {};
        size_t count = 0;
        int read_errno = 0;
        while (count < sizeof(config)) {
            const ssize_t got = pread(fd, config + count, sizeof(config) - count,
                                      static_cast<off_t>(count));
            if (got < 0) {
                if (errno == EINTR) continue;
                read_errno = errno; break;
            }
            if (!got) break;
            count += static_cast<size_t>(got);
        }
        close(fd);
        std::printf(" CONFIG_BYTES=%zu READ_ERRNO=%d", count, read_errno);
        cask_pci_decode(config, count);
        std::printf("\n");
    }
    std::fflush(stdout);
}
#endif
