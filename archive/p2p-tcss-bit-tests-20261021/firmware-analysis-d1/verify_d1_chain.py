#!/usr/bin/env python3
"""Verifica locale sola lettura della catena SaSetup -> CCFG D1 nel BIOS 1.26."""
import hashlib
import json
import pathlib
import struct
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[4]
OUT = pathlib.Path(__file__).resolve().parent
MOD = ROOT / 'runtime/reports/p2p-thunderbolt-firmware-20261020/modules'
pe = (MOD / 'SiInitFsp.pe').read_bytes()
te = (MOD / 'SiliconPolicyPeiPostMem.te').read_bytes()

def sha(b):
    return hashlib.sha256(b).hexdigest()

def checked(data, offset, expected):
    wanted = bytes.fromhex(expected)
    actual = data[offset:offset+len(wanted)]
    assert actual == wanted, (hex(offset), actual.hex(), expected)
    return {'offset': hex(offset), 'bytes': actual.hex()}

assert sha(pe) == 'de17fb9ae71e0cb04fa39102ed1895284640befb719b44ea45b498e29b0c928f'
assert sha(te) == 'f2b08d79335536519b84af1edeed90cd910fec3ae902c6ff418b9b02aec37187'
te_base = struct.unpack_from('<Q', te, 16)[0]
te_delta = struct.unpack_from('<H', te, 6)[0] - 40
assert te_base == 0xFFD38E3C and te_delta == 0x198
guid_pe = uuid.UUID(bytes_le=pe[0x36EA0:0x36EB0])
guid_off = 0xFFD43B4C - te_base - te_delta
guid_te = uuid.UUID(bytes_le=te[guid_off:guid_off+16])
assert guid_pe == guid_te == uuid.UUID('9749a5fb-9130-44f0-8f61-dbff8ef2cac7')
name_off = 0xFFD448B8 - te_base - te_delta
assert te[name_off:name_off+16].decode('utf-16le') == 'SaSetup\0'

checks_pe = [
    checked(pe, 0x6AE3, '83ee017426'),
    checked(pe, 0x6B0E, 'c70701000000'),
    checked(pe, 0x6B73, 'b00159c3'),
    checked(pe, 0xF479, 'a180ce0300'),
    checked(pe, 0xF47F, '69cdf001000083c01c03c1'),
    checked(pe, 0xF61B, 'f6401010741c'),
    checked(pe, 0xF62F, '81e10000000481c188ef7ff0'),
    checked(pe, 0xF63D, 'c74424187700000e'),
    checked(pe, 0xF64B, '81c6d0000000'),
    checked(pe, 0xF658, 'e888720000'),
    checked(pe, 0x10385, '6880ce0300baa06e0300'),
    checked(pe, 0x10C9F, 'e894e7ffff'),
]
checks_te = [
    checked(te, 0x652A-te_delta, '8d442454ba4c3bd4ff'),
    checked(te, 0x65F5-te_delta, '8d8424a8000000'),
    checked(te, 0x660B-te_delta, '681c3ed4ff68b848d4ff'),
    checked(te, 0x6B74-te_delta, '8b742454'),
    checked(te, 0x6BD6-te_delta, '69d7f0010000'),
    checked(te, 0x6C8B-te_delta, '0fb6843c72040000c1e0043344322c83e0103144322c'),
]
base = ROOT / 'runtime/reports/p2p-tcss-bit-tests-20261021/firmware-candidate'
fresh_te = list((base / 'fresh-baseline-extracted').glob('**/file-ce19678f-3f08-4e81-a1f3-1886ca13ada7/section1.te'))
fresh_pe = list((base / 'fresh-baseline-extracted').glob('**/file-80a845ac-210f-43b0-995b-477be41ab4e8/section1/section0.pe'))
candidate_pe = list((base / 'fresh-candidate-extracted').glob('**/file-80a845ac-210f-43b0-995b-477be41ab4e8/section1/section0.pe'))
assert len(fresh_te) == len(fresh_pe) == len(candidate_pe) == 1
assert fresh_te[0].read_bytes() == te
assert fresh_pe[0].read_bytes() == pe
patched = candidate_pe[0].read_bytes()
assert [i for i, (a,b) in enumerate(zip(pe,patched)) if a != b] == [0x20304]
assert len(pe) == len(patched)
assert pe[0xF438:0xF65D] == patched[0xF438:0xF65D]

old = 0x0E008077
enabled_d1 = (old & 0xF47FEF88) | 0x77
enabled_d6 = (old & 0xF07FEF88) | 0x77
assert enabled_d1 == 0x04008077 and enabled_d6 == 0x00008077
result = {
    'status': 'STATIC_CHAIN_PROVEN_D1_BIT26_HARDWARE_SEMANTICS_NOT_PROVEN',
    'modules': {'SiInitFsp_sha256': sha(pe), 'SiliconPolicyPeiPostMem_sha256': sha(te)},
    'fresh_spi_extracted_matches_both_modules': True,
    'existing_d7_candidate_leaves_d1_routine_identical': True,
    'policy_guid': str(guid_pe),
    'policy_source': {'variable': 'SaSetup', 'offset': '0x3E2 + port_index', 'port_index_D1F0': 1},
    'policy_destination': {'base': 'GetConfigBlock(9749a5fb-9130-44f0-8f61-dbff8ef2cac7)', 'field': '0x2C + port_index * 0x1F0', 'bit': 4},
    'code': {'policy_function': 'SiliconPolicyPeiPostMem TE RVA 0x6466', 'policy_copy_rva': '0x6C8B..0x6C9D', 'fsp_init': '0x10371', 'per_port_call': '0x10C9F -> 0xF438', 'port_bdf_helper': '0x6AC0', 'controller_helper': '0x6B54', 'ccfg_write_call': '0xF658 -> 0x168E5', 'register': 'D1:F0 + 0xD0'},
    'ccfg_masks': {'P2P_disabled_AND': '0xFE7FEF88', 'P2P_disabled_OR': '0x0E000077', 'P2P_enabled_D1_AND': '0xF47FEF88', 'P2P_enabled_D6_AND': '0xF07FEF88', 'P2P_enabled_OR': '0x00000077'},
    'evaluated': {'input': hex(old), 'enabled_D1': hex(enabled_d1), 'enabled_D6': hex(enabled_d6)},
    'hypothetical_change_NOT_APPLIED': {'rva_file_offset': '0xF634', 'old': '04', 'new': '00', 'instruction': 'AND ECX,0x04000000 -> AND ECX,0', 'effect': 'clear bit26 at the existing CCFG init write when peer policy is enabled and helper6B54 returns1', 'scope': 'D1:F0 and also D1:F1 on SKUs where index2 maps to that port', 'hardware_effect_and_fix_not_proven': True},
    'checks_pe': checks_pe, 'checks_te_file_offsets': checks_te,
    'no_remote_access': True, 'no_firmware_mutation': True,
}
(OUT/'D1-evidence.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps({'status': result['status'], 'evidence': str(OUT/'D1-evidence.json'), 'checks':len(checks_pe)+len(checks_te)}))
