"""Lettura sola dei registri dopo il firmware; nessuna baseline imposta."""
from pathlib import Path
import contextlib
import json
import os
import platform
import struct
import sys
import regbar_probe as p

R = Path(__file__).resolve().parent
output = R / sys.argv[1]
assert not output.exists()
assert platform.node() == 'hypervisor-host'
assert p.pci_u32('0000:00:07.0', 0) == 0x466e8086
assert struct.unpack('<Q', p.pci_read('0000:00:00.0', 0x48, 8))[0] == 0xfedc0001
ecam, mcfg_hash = p.ecam_address()
helper, helper_info = p.load_helper(R, str(R/'regbar_mmio.so'))
result = {'utc': p.stamp(), 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
          'hardware_writes': False, 'pci': {}, 'regbar': {}, 'mcfg_sha256': mcfg_hash}
for bdf in ['0000:00:01.0', '0000:00:07.0', '0000:00:07.2']:
    data = p.pci_read(bdf, 0, 256)
    result['pci'][bdf] = {'id': hex(struct.unpack_from('<I', data, 0)[0]),
        'ccfg_d0': hex(struct.unpack_from('<I', data, 0xd0)[0]),
        'd8': hex(struct.unpack_from('<I', data, 0xd8)[0]), 'config_hex': data.hex()}
with contextlib.ExitStack() as stack:
    fd = os.open('/dev/mem', os.O_RDONLY | os.O_SYNC)
    stack.callback(os.close, fd)
    mch = p.PhysicalPage(fd, 0xfedc7110, helper)
    stack.callback(mch.close)
    assert mch.read32(0xfedc7110) == 0xfb000001 and mch.read32(0xfedc7114) == 0
    for name, addr in [('C6_D0', 0xfbc600d0), ('CE_D0', 0xfbce00d0),
                       ('ECAM_D7F0_D0', ecam+0xd0)]:
        page = p.PhysicalPage(fd, addr, helper)
        stack.callback(page.close)
        result['regbar'][name] = hex(page.read32(addr))
p.save_new_json(output, result)
print(json.dumps(result, indent=2))
