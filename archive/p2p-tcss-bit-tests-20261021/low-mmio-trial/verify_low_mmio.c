// SPDX-License-Identifier: GPL-2.0-only
/* Read-only verifier for this exact 7.0.0-38-generic native RAM trial.
 * No PCI writes, BAR sizing probes, resource allocation or driver operations.
 * Build on Linux: cc -std=c11 -O2 -Wall -Wextra -Werror -static
 *                  verify_low_mmio.c -o verify_low_mmio
 */
#define _POSIX_C_SOURCE 200809L
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#if defined(__i386__) || defined(__x86_64__)
#include <cpuid.h>
#endif

#define PATH_CAP 4096
#define MAX_RES 32
/* Captured kernel enables CONFIG_PCI_IOV: bridge resources start at 13. */
#define PREF_RES 15
#define BRIDGE_FLAGS UINT64_C(0x102201)
#define BAR_FLAGS UINT64_C(0x14220c)

struct identity { const char *bdf; uint16_t vendor, device; };
static const struct identity ids[] = {
    {"0000:00:00.0", 0x8086, 0x4641},
    {"0000:00:01.0", 0x8086, 0x460d},
    {"0000:00:07.0", 0x8086, 0x466e},
    {"0000:04:00.0", 0x1b21, 0x2461},
    {"0000:05:00.0", 0x1b21, 0x2461},
    {"0000:06:00.0", 0x10de, 0x2571},
    {"0000:06:00.1", 0x10de, 0x228e},
    {"0000:01:00.0", 0x10de, 0x28b0},
    {"0000:01:00.1", 0x10de, 0x22be}
};
struct resource { uint64_t start, end, flags; };
static const char *fixture;
static char devices[PATH_CAP];
static unsigned int failures;

static int path_for(char *out, const char *bdf, const char *name)
{
    int n = snprintf(out, PATH_CAP, "%s/%s/%s", devices, bdf, name);
    if (n < 0 || n >= PATH_CAP) {
        fprintf(stderr, "FAIL path too long\n");
        failures++;
        return -1;
    }
    return 0;
}

static int config(const char *bdf, unsigned char out[64])
{
    char path[PATH_CAP];
    size_t done = 0;
    int fd;
    if (path_for(path, bdf, "config"))
        return -1;
    fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0)
        goto fail;
    while (done < 64) {
        ssize_t n = pread(fd, out + done, 64 - done, (off_t)done);
        if (n < 0 && errno == EINTR)
            continue;
        if (n <= 0) {
            if (!n)
                errno = EIO;
            goto fail_close;
        }
        done += (size_t)n;
    }
    if (close(fd))
        goto fail;
    return 0;
fail_close:
    {
        int saved = errno;
        (void)close(fd);
        errno = saved;
    }
fail:
    fprintf(stderr, "FAIL %s read: %s\n", path, strerror(errno));
    failures++;
    return -1;
}

static uint32_t le32(const unsigned char *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static int hex_field(char **cursor, uint64_t *out)
{
    char *p = *cursor, *end;
    unsigned long long value;
    while (isspace((unsigned char)*p))
        p++;
    if (!isxdigit((unsigned char)*p))
        return -1;
    errno = 0;
    value = strtoull(p, &end, 16);
    if (errno || end == p || (*end && !isspace((unsigned char)*end)))
        return -1;
    *out = (uint64_t)value;
    *cursor = end;
    return 0;
}

static int resources(const char *bdf, struct resource out[MAX_RES], size_t *count)
{
    char path[PATH_CAP], line[256];
    FILE *f;
    size_t n = 0;
    int bad = 0;
    if (path_for(path, bdf, "resource"))
        return -1;
    f = fopen(path, "r");
    if (!f) {
        fprintf(stderr, "FAIL %s open: %s\n", path, strerror(errno));
        failures++;
        return -1;
    }
    while (fgets(line, sizeof(line), f)) {
        char *p = line;
        if (n == MAX_RES || !strchr(line, '\n') ||
            hex_field(&p, &out[n].start) || hex_field(&p, &out[n].end) ||
            hex_field(&p, &out[n].flags)) {
            bad = 1;
            break;
        }
        while (isspace((unsigned char)*p))
            p++;
        if (*p) {
            bad = 1;
            break;
        }
        n++;
    }
    if (ferror(f))
        bad = 1;
    if (fclose(f))
        bad = 1;
    if (bad || !n) {
        fprintf(stderr, "FAIL %s malformed, truncated or unreadable\n", path);
        failures++;
        return -1;
    }
    *count = n;
    return 0;
}

static void want(const char *bdf, const char *field, uint64_t got, uint64_t expected)
{
    if (got != expected) {
        fprintf(stderr, "FAIL %s %s got=0x%" PRIx64 " expected=0x%" PRIx64 "\n",
                bdf, field, got, expected);
        failures++;
    }
}

static void native_identity(void)
{
    unsigned int eax = 0, ecx = 0;
    if (fixture) {
        char path[PATH_CAP], line[128], *p;
        uint64_t a = 0, c = 0;
        FILE *f;
        int n = snprintf(path, sizeof(path), "%s/cpu.identity", fixture);
        int bad = 0;
        if (n < 0 || (size_t)n >= sizeof(path)) {
            failures++;
            return;
        }
        f = fopen(path, "r");
        if (!f) {
            fprintf(stderr, "FAIL fixture cpu.identity missing\n");
            failures++;
            return;
        }
        if (!fgets(line, sizeof(line), f))
            bad = 1;
        else {
            p = line;
            if (hex_field(&p, &a) || hex_field(&p, &c))
                bad = 1;
            while (isspace((unsigned char)*p))
                p++;
            if (*p || a > UINT32_MAX || c > UINT32_MAX)
                bad = 1;
        }
        if (fgetc(f) != EOF || ferror(f))
            bad = 1;
        if (fclose(f))
            bad = 1;
        if (bad) {
            fprintf(stderr, "FAIL malformed fixture cpu.identity\n");
            failures++;
            return;
        }
        eax = (unsigned int)a;
        ecx = (unsigned int)c;
    } else {
#if defined(__i386__) || defined(__x86_64__)
        unsigned int ebx, edx;
        if (!__get_cpuid(1, &eax, &ebx, &ecx, &edx)) {
            fprintf(stderr, "FAIL CPUID leaf 1 unavailable\n");
            failures++;
            return;
        }
#else
        fprintf(stderr, "FAIL native verifier requires x86 CPUID\n");
        failures++;
        return;
#endif
    }
    want("CPU", "CPUID.1:EAX", eax, 0x906a3);
    want("CPU", "hypervisor flag", ecx & 0x80000000U, 0);
    printf("CPU signature=%08x hypervisor=%u mode=%s\n", eax, ecx >> 31,
           fixture ? "FIXTURE_ONLY" : "NATIVE");
}

static void resource_want(const char *bdf, const struct resource *r,
                          unsigned int index, uint64_t start, uint64_t end,
                          uint64_t flags)
{
    char label[64];
    (void)snprintf(label, sizeof(label), "resource[%u].start", index);
    want(bdf, label, r->start, start);
    (void)snprintf(label, sizeof(label), "resource[%u].end", index);
    want(bdf, label, r->end, end);
    (void)snprintf(label, sizeof(label), "resource[%u].flags", index);
    want(bdf, label, r->flags, flags);
    printf("%s resource[%u]=%08" PRIx64 "-%08" PRIx64 " flags=%08" PRIx64 "\n",
           bdf, index, r->start, r->end, r->flags);
}

static void check_target(size_t i, const unsigned char before[64])
{
    const char *bdf = ids[i].bdf;
    struct resource r[MAX_RES];
    unsigned char after[64];
    size_t n = 0;
    unsigned int k;
    if (resources(bdf, r, &n))
        return;
    if (i >= 2 && i <= 4) {
        want(bdf, "header type", before[0x0e] & 0x7f, 1);
        want(bdf, "primary bus", before[0x18], i == 2 ? 0 : i + 1);
        want(bdf, "secondary bus", before[0x19], i + 2);
        if (before[0x1a] < before[0x19]) {
            fprintf(stderr, "FAIL %s subordinate bus excludes secondary\n", bdf);
            failures++;
        }
        want(bdf, "PMBL@24", le32(before + 0x24), 0x91f18001);
        want(bdf, "PMBU@28", le32(before + 0x28), 0);
        want(bdf, "PMLU@2c", le32(before + 0x2c), 0);
        if (n != 17) {
            fprintf(stderr, "FAIL %s requires 17 resource lines, got %zu\n", bdf, n);
            failures++;
        } else
            resource_want(bdf, &r[PREF_RES], PREF_RES, 0x80000000,
                          0x91ffffff, BRIDGE_FLAGS);
        printf("%s PMBL=%08x PMBU=%08x PMLU=%08x\n", bdf,
               le32(before + 0x24), le32(before + 0x28), le32(before + 0x2c));
    } else {
        want(bdf, "header type", before[0x0e] & 0x7f, 0);
        want(bdf, "BAR1.low@14", le32(before + 0x14), 0x8000000c);
        want(bdf, "BAR1.high@18", le32(before + 0x18), 0);
        want(bdf, "BAR3.low@1c", le32(before + 0x1c), 0x9000000c);
        want(bdf, "BAR3.high@20", le32(before + 0x20), 0);
        if (n != 13) {
            fprintf(stderr, "FAIL %s requires 13 resource lines, got %zu\n", bdf, n);
            failures++;
        } else {
            resource_want(bdf, &r[1], 1, 0x80000000, 0x8fffffff, BAR_FLAGS);
            resource_want(bdf, &r[3], 3, 0x90000000, 0x91ffffff, BAR_FLAGS);
        }
        printf("%s BAR1=%08x/%08x (256 MiB), BAR3=%08x/%08x (32 MiB)\n", bdf,
               le32(before + 0x14), le32(before + 0x18),
               le32(before + 0x1c), le32(before + 0x20));
    }
    if (config(bdf, after))
        return;
    want(bdf, "identity reread", le32(after), le32(before));
    /* Only static fields: COMMAND/STATUS may change while the driver runs. */
    if (i <= 4) {
        want(bdf, "bus numbers reread", le32(after + 0x18), le32(before + 0x18));
        for (k = 0x24; k <= 0x2c; k += 4)
            want(bdf, "prefetch config reread", le32(after + k), le32(before + k));
    } else {
        for (k = 0x14; k <= 0x20; k += 4)
            want(bdf, "BAR config reread", le32(after + k), le32(before + k));
    }
}

int main(int argc, char **argv)
{
    unsigned char c[64];
    size_t i;
    int n;
    if (argc == 3 && !strcmp(argv[1], "--fixture")) {
        fixture = argv[2];
        n = snprintf(devices, sizeof(devices), "%s/sys/bus/pci/devices", fixture);
    } else if (argc == 1) {
        n = snprintf(devices, sizeof(devices), "/sys/bus/pci/devices");
    } else {
        fprintf(stderr, "Usage: %s [--fixture ROOT]\n", argv[0]);
        return 2;
    }
    if (n < 0 || (size_t)n >= sizeof(devices))
        return 2;
    printf("CaskLogic low-MMIO read-only verification: BAR1 80000000-8fffffff; "
           "BAR3 90000000-91ffffff; three bridge windows 80000000-91ffffff.\n");
    if (fixture)
        printf("FIXTURE ONLY: success does not certify the running hardware.\n");
    native_identity();
    for (i = 0; i < sizeof(ids) / sizeof(ids[0]); i++) {
        if (config(ids[i].bdf, c))
            continue;
        want(ids[i].bdf, "vendor/device", le32(c),
             ((uint32_t)ids[i].device << 16) | ids[i].vendor);
        if (i >= 2 && i <= 5)
            check_target(i, c);
    }
    if (failures) {
        fprintf(stderr, "LOW_MMIO_VERIFY_FAIL errors=%u mode=%s\n", failures,
                fixture ? "FIXTURE_ONLY" : "NATIVE");
        return 1;
    }
    puts(fixture ? "LOW_MMIO_FIXTURE_PASS" : "LOW_MMIO_NATIVE_PASS");
    return 0;
}
