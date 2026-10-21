"""Crea il pacchetto locale di prova. Non accede all'hardware."""
from pathlib import Path
import hashlib
import json
import shutil

R = Path(__file__).resolve().parent
F = R / 'firmware-candidate'
P = R / 'native-flash-package'
P.mkdir(exist_ok=True)
verification = json.loads((R / 'fresh-spi-verification.json').read_text())
assert verification['fresh_dumps_identical'] and verification['target_ffs_matches']
for source, target in [
    (F / 'SPI-01B16000-00013000.ORIGINAL.bin', 'ORIGINAL.bin'),
    (F / 'SPI-01B16000-00013000.CANDIDATE-NOT-FLASH-READY.bin', 'CANDIDATE.bin'),
    (F / 'RegionPre.efi', 'RegionPre.efi'),
    (F / 'RegionPost.efi', 'RegionPost.efi'),
    (F / 'RegionRestore.efi', 'RegionRestore.efi'),
]:
    shutil.copyfile(source, P / target)

d = '%homefilesystem%\\EFI\\CaskLogicTcssTest\\'
lines = ['@echo -off', 'echo CaskLogic: prova TCSS nei 19 settori verificati.']
def command(s):
    lines.append(s.replace('@D@', d))
def remove(name, failure):
    command('if exist @D@' + name + ' then')
    command('  rm -q @D@' + name)
    command('endif')
    command('if exist @D@' + name + ' then')
    command('  goto ' + failure)
    command('endif')
def status(failure):
    command('if not %lasterror% == 0 then')
    command('  goto ' + failure)
    command('endif')
def require(name, failure):
    command('if not exist @D@' + name + ' then')
    command('  goto ' + failure)
    command('endif')
def dump(name, log, failure):
    remove(name, failure)
    command('@researcher@example.invalid -d @D@' + name + ' -a 0x01B16000 -l 0x00013000 > @D@' + log)
    status(failure)
def gate(app, flag, failure):
    remove(flag, failure)
    command('@D@' + app)
    status(failure)
    require(flag, failure)

for flag in ['READY.flag', 'VERIFIED.flag', 'RESTORED.flag']:
    remove(flag, 'abort')
dump('region-before.bin', 'Fpt-region-before.txt', 'abort')
gate('RegionPre.efi', 'READY.flag', 'abort')
command('@researcher@example.invalid -f @researcher@example.invalid -a 0x01B16000 -l 0x00013000 > @researcher@example.invalid')
status('rollback')
dump('region-after.bin', 'Fpt-region-after.txt', 'rollback')
gate('RegionPost.efi', 'VERIFIED.flag', 'rollback')
command('echo CANDIDATE_WRITTEN_AND_READBACK_VERIFIED > @researcher@example.invalid')
command('reset -w')
command('goto fatal')
command(':rollback')
command('echo Controllo se i settori originali sono ancora intatti.')
dump('region-restored.bin', 'Fpt-region-check-original.txt', 'do_restore')
gate('RegionRestore.efi', 'RESTORED.flag', 'do_restore')
command('goto restored')
command(':do_restore')
command('echo Verifica fallita: ripristino dei 19 settori originali.')
command('@researcher@example.invalid -f @researcher@example.invalid -a 0x01B16000 -l 0x00013000 > @researcher@example.invalid')
command('if not %lasterror% == 0 then')
command('  echo RESTORE_COMMAND_ERROR_READBACK_REQUIRED > @researcher@example.invalid')
command('endif')
dump('region-restored.bin', 'Fpt-region-restored.txt', 'fatal')
gate('RegionRestore.efi', 'RESTORED.flag', 'fatal')
command(':restored')
command('echo ORIGINAL_RESTORED_AND_READBACK_VERIFIED > @researcher@example.invalid')
command('reset -w')
command('goto fatal')
command(':abort')
command('echo ABORTED_BEFORE_FLASH > @researcher@example.invalid')
command('reset -w')
command('goto fatal')
command(':fatal')
command('echo FLASH_OR_RESTORE_UNVERIFIED_DO_NOT_RESET > @researcher@example.invalid')
command('echo ATTENZIONE: verifica incompleta. NON RIAVVIARE. Consultare i log.')
command('pause')
command('exit /b 1')
(P / 'startup.nsh').write_bytes(('\r\n'.join(lines) + '\r\n').encode('utf-16'))
manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(P.iterdir()) if p.is_file() and p.name != 'files.json'}
(P / 'files.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps(manifest, indent=2))
