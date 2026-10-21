/* Shared with CPU-only fixtures. No I/O and no kernel state modification. */
#define DMAR_LIMIT 65536U
#define DMAR_FIXED_SIZE 48U
#define MAX_DRHD 32U
struct snapshot_drhd { u64 base; u16 segment; u8 flags; unsigned int scopes; };
struct snapshot_dmar { unsigned int count; u8 host_width, flags, revision; struct snapshot_drhd units[MAX_DRHD]; };
static u16 bytes16(const u8 *p) { return (u16)p[0] | (u16)p[1] << 8; }
static u32 bytes32(const u8 *p) { return (u32)bytes16(p) | (u32)bytes16(p+2) << 16; }
static u64 bytes64(const u8 *p) { return (u64)bytes32(p) | (u64)bytes32(p+4) << 32; }
static int parse_dmar(const u8 *table, size_t bytes, struct snapshot_dmar *out)
{
    unsigned int pos, next, i, len, type;
    u8 sum=0;
    if (!table || !out || bytes < DMAR_FIXED_SIZE || bytes > DMAR_LIMIT ||
        table[0]!='D' || table[1]!='M' || table[2]!='A' || table[3]!='R' ||
        bytes32(table+4)!=bytes || table[36]>63)
        return -EINVAL;
    for (i=0;i<bytes;i++) sum=(u8)(sum+table[i]);
    if (sum) return -EBADMSG;
    memset(out,0,sizeof(*out));
    out->host_width=table[36]; out->flags=table[37]; out->revision=table[8];
    pos=DMAR_FIXED_SIZE;
    while (pos<bytes) {
        if (bytes-pos<4) return -EINVAL;
        type=bytes16(table+pos); len=bytes16(table+pos+2);
        if (len<4 || len>bytes-pos) return -EINVAL;
        next=pos+len;
        if (type==0) {
            struct snapshot_drhd *unit;
            unsigned int scope;
            if (len<16) return -EINVAL;
            if (out->count==MAX_DRHD) return -E2BIG;
            unit=&out->units[out->count];
            unit->flags=table[pos+4]; unit->segment=bytes16(table+pos+6);
            unit->base=bytes64(table+pos+8);
            if (!unit->base || (unit->base&0xfffULL) || unit->base>~0ULL-4095ULL)
                return -EINVAL;
            for (i=0;i<out->count;i++)
                if (out->units[i].base==unit->base && out->units[i].segment==unit->segment)
                    return -EINVAL;
            scope=pos+16;
            while (scope<next) {
                unsigned int scope_bytes;
                if (next-scope<6) return -EINVAL;
                scope_bytes=table[scope+1];
                if (scope_bytes<6 || scope_bytes>next-scope || ((scope_bytes-6)&1))
                    return -EINVAL;
                unit->scopes++;
                scope+=scope_bytes;
            }
            out->count++;
        }
        pos=next;
    }
    return out->count ? 0 : -ENODEV;
}
