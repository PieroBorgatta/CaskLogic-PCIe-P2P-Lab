"""Compila in VM le tre applicazioni GNU-EFI, senza installarle o eseguirle."""
from pathlib import Path
import hashlib
import json
import subprocess

R = Path(__file__).resolve().parent
E = Path('/mnt/llm/riscrivo/runtime/reports/gpu-followup-20261020/uefi-p2p')
assert subprocess.check_output(['hostname'], text=True).strip() == 'gpu-vm'
builds = {}
for name, defines in [('RegionPre', []), ('RegionPost', ['-DPOST_CHECK']),
                      ('RegionRestore', ['-DRESTORE_CHECK'])]:
    subprocess.run(['gcc', '-I'+str(E/'efi-headers'), '-I'+str(E/'efi-headers/x86_64'),
        '-fpic', '-ffreestanding', '-fno-stack-protector', '-fno-stack-check',
        '-fshort-wchar', '-mno-red-zone', '-maccumulate-outgoing-args',
        '-DGNU_EFI_USE_MS_ABI', '-Wall', '-Wextra', '-Werror', '-O2', *defines,
        '-c', str(R/'TcssRegionGate.c'), '-o', str(R/(name+'.o'))], check=True)
    subprocess.run(['ld', '-nostdlib', '-znocombreloc', '-T', str(E/'elf_x86_64_efi.lds'),
        '-shared', '-Bsymbolic', str(E/'crt0-efi-x86_64.o'), str(R/(name+'.o')),
        '-L'+str(E), '-lefi', '-lgnuefi', '-o', str(R/(name+'.so'))], check=True)
    args = ['objcopy']
    for section in ['.text', '.sdata', '.data', '.dynamic', '.dynsym', '.rel', '.rela', '.reloc']:
        args += ['-j', section]
    subprocess.run(args + ['-O', 'efi-app-x86_64', str(R/(name+'.so')), str(R/(name+'.efi'))], check=True)
    dis = subprocess.check_output(['objdump', '-d', str(R/(name+'.o'))], text=True)
    assert 'wrmsr' not in dis
    assert dis.count('rdmsr') == (1 if name == 'RegionPre' else 0)
    (R/(name+'.disassembly.txt')).write_text(dis)
    builds[name] = {'sha256': hashlib.sha256((R/(name+'.efi')).read_bytes()).hexdigest(),
                    'bytes': (R/(name+'.efi')).stat().st_size, 'defines': defines}
out = {'source_sha256': hashlib.sha256((R/'TcssRegionGate.c').read_bytes()).hexdigest(), 'builds': builds}
(R/'region-gates-build.json').write_text(json.dumps(out, indent=2)+'\n')
print(json.dumps(out, indent=2))
