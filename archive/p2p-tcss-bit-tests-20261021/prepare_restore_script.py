"""Prepara un ripristino esplicito dopo il collaudo, senza eseguirlo."""
from pathlib import Path
import hashlib
R = Path(__file__).resolve().parent
d = '%homefilesystem%\\EFI\\CaskLogicTcssTest\\'
lines = ['@echo -off', 'echo CaskLogic: ripristino verificato del modulo TCSS originale.']
def add(s): lines.append(s.replace('@D@', d))
def status(label):
    add('if not %lasterror% == 0 then'); add('  goto '+label); add('endif')
def remove(name, label):
    add('if exist @D@'+name+' then'); add('  rm -q @D@'+name); add('endif')
    add('if exist @D@'+name+' then'); add('  goto '+label); add('endif')
def dump(name, log, label):
    remove(name, label)
    add('@researcher@example.invalid -d @D@'+name+' -a 0x01B16000 -l 0x00013000 > @D@'+log)
    status(label)
def gate(app, flag, label):
    remove(flag, label); add('@D@'+app); status(label)
    add('if not exist @D@'+flag+' then'); add('  goto '+label); add('endif')
dump('region-after.bin', 'Fpt-restore-candidate-before.txt', 'abort')
gate('RegionPost.efi', 'VERIFIED.flag', 'abort')
add('@researcher@example.invalid -f @researcher@example.invalid -a 0x01B16000 -l 0x00013000 > @researcher@example.invalid')
add('if not %lasterror% == 0 then')
add('  echo ORIGINAL_WRITE_ERROR_REQUIRES_READBACK > @researcher@example.invalid')
add('endif')
dump('region-restored.bin', 'Fpt-original-readback.txt', 'fatal')
gate('RegionRestore.efi', 'RESTORED.flag', 'fatal')
add('echo ORIGINAL_RESTORED_AND_READBACK_VERIFIED > @researcher@example.invalid')
add('reset -w'); add('goto fatal')
add(':abort'); add('echo RESTORE_ABORTED_BEFORE_FLASH > @researcher@example.invalid')
add('reset -w'); add('goto fatal')
add(':fatal'); add('echo ORIGINAL_RESTORE_UNVERIFIED_DO_NOT_RESET > @researcher@example.invalid')
add('echo ATTENZIONE: ripristino non verificato. NON RIAVVIARE.'); add('pause'); add('exit /b 1')
body = ('\r\n'.join(lines)+'\r\n').encode('utf-16')
(R/'startup-restore.nsh').write_bytes(body)
print(hashlib.sha256(body).hexdigest())
