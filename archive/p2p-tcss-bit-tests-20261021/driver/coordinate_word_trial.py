"""Esegue una prova autorizzata; apre i gate solo dopo lettura host CCFG."""
from pathlib import Path
import json
import shlex
import subprocess
import time

R = Path(__file__).resolve().parent
V = '/mnt/llm/riscrivo/runtime/reports/p2p-tcss-bit-tests-20261021/driver'
OLD = '/mnt/llm/riscrivo/runtime/reports/gpu-followup-20261020/p2p-driver'
OUT = V + '/candidate'
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5']
args = ['python3', V+'/run_word_trial.py', '--trial-root', OLD,
        '--module', OLD+'/compiled-dynamic/nvidia.ko', '--module-sha256',
        '41a3025b63192242bda4f9eb692d8a000fc85850d009c45f679f9ef46f9bef80',
        '--out', OUT]
events = []
def remote(host, code):
    return subprocess.run(SSH+[host, 'python3 -c '+shlex.quote(code)],
                          capture_output=True, text=True, timeout=8)
def log(**data):
    data['epoch'] = time.time(); events.append(data)
    (R/'coordinator-events.json').write_text(json.dumps(events, indent=2)+'\n')
    print(json.dumps(data), flush=True)

with (R/'candidate-runner-output.txt').open('x') as output:
    proc = subprocess.Popen(SSH+['gpu-vm', shlex.join(args)], stdout=output, stderr=subprocess.STDOUT)
    log(event='runner_started', args=args)
    released = set(); start = time.monotonic()
    while proc.poll() is None and time.monotonic()-start < 180:
        ready = remote('gpu-vm', "from pathlib import Path;p=Path("+repr(OUT+'/config-gate-ready')+");print(p.read_text() if p.exists() else '')")
        token = ready.stdout.strip()
        if ready.returncode == 0 and token in {'0', '1'} and token not in released:
            check = remote('hypervisor-host', "import os,struct,json; r={};\nfor b in ['0000:00:07.0','0000:00:07.2']:\n f=os.open('/sys/bus/pci/devices/'+b+'/config',os.O_RDONLY);r[b]=[struct.unpack('<I',os.pread(f,4,x))[0] for x in [0,0xd0]];os.close(f)\nprint(json.dumps(r))")
            if check.returncode:
                log(event='host_check_failed', output=check.stdout, error=check.stderr); break
            values = json.loads(check.stdout)
            expected = {'0000:00:07.0': [0x466e8086,0x9077], '0000:00:07.2':[0x462f8086,0x9077]}
            log(event='host_registers_at_gpu_gate', gate=token, observed=values, expected=expected)
            if values != expected:
                log(event='gate_not_released_register_mismatch'); break
            release = remote('gpu-vm', "from pathlib import Path;p=Path("+repr(OUT+'/config-gate-go')+");p.write_text("+repr(token+'\n')+")")
            assert release.returncode == 0, release.stderr
            released.add(token); log(event='gate_released', gate=token)
        time.sleep(0.5)
    # Il programma GPU ha timeout20s pergate e il runner65s complessivi.
    # Non uccidere SSH: il finally remoto deve ripristinare i moduli.
    code = proc.wait(timeout=100)
    log(event='runner_finished', rc=code, released=sorted(released))
print((R/'candidate-runner-output.txt').read_text())
