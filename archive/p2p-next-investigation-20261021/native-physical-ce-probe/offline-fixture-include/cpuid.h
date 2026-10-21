#pragma once
// Host-only fixture shim: native_identity is compiled but never executed.
inline int __get_cpuid(unsigned, unsigned*, unsigned*, unsigned*, unsigned*) { return 0; }
