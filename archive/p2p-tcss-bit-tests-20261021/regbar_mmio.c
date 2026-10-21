/* Accessi MMIO scalari, allineati, x86-64. Nessun accesso atomico/LOCK. */
typedef unsigned int uint32_t;
_Static_assert(sizeof(uint32_t) == 4, "Richiesto intero nativo a 32 bit");

#if !defined(__x86_64__)
#error "Questo helper e destinato esclusivamente all'host x86-64 verificato."
#endif

__attribute__((noinline)) uint32_t regbar_read32(const volatile uint32_t *address)
{
    uint32_t value = *address;
    __asm__ __volatile__("" ::: "memory");
    return value;
}

__attribute__((noinline)) void regbar_write32(volatile uint32_t *address, uint32_t value)
{
    *address = value;
    __asm__ __volatile__("mfence" ::: "memory");
}
