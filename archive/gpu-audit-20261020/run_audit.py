"""Orchestrazione sul server: strumenti isolati, telemetria e arresto termico."""
import csv
import datetime
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time

ROOT = Path('/mnt/llm/riscrivo/runtime/reports/gpu-audit-20261020')
IMAGE = 'casklogic-riscrivo:torch2.10-cu126'
NAME = 'riscrivo-gpu-audit'
ADA = 'GPU-00000000-0000-0000-0000-000000000001'
A2000 = 'GPU-00000000-0000-0000-0000-000000000002'
STOP = threading.Event()
PHASE = 'initializing'
PHASE_STARTED = time.time()
RESULTS = []
ABORT_REASON = None
MONITOR_DONE = threading.Event()


def atomic(path, value):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2))
    tmp.replace(path)


def status(state='RUNNING'):
    atomic(ROOT / 'status.json', {'state': state, 'phase': PHASE,
           'phase_started': PHASE_STARTED, 'updated_epoch': time.time(),
           'completed_stages': len(RESULTS), 'abort_reason': ABORT_REASON})


def cancel(*_):
    global ABORT_REASON
    ABORT_REASON = ABORT_REASON or 'requested stop'
    STOP.set()


def stop_container():
    subprocess.run(['docker', 'stop', '--timeout', '8', NAME],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)


def telemetry():
    global ABORT_REASON
    fields = ['uuid', 'temperature.gpu', 'utilization.gpu', 'utilization.memory',
              'memory.used', 'power.draw', 'clocks.current.sm', 'clocks.current.memory',
              'pstate', 'clocks_event_reasons.active']
    failures = 0
    with (ROOT / 'telemetry.jsonl').open('a', buffering=1) as f:
        while not MONITOR_DONE.is_set():
            try:
                training = subprocess.run(['systemctl', 'is-active', 'riscrivo-training.service'],
                                          capture_output=True, text=True, timeout=4)
                if training.stdout.strip() == 'active':
                    ABORT_REASON = 'training was started externally; stopping audit'
                    STOP.set()
                p = subprocess.run(['nvidia-smi', '--query-gpu=' + ','.join(fields),
                                    '--format=csv,noheader,nounits'],
                                   capture_output=True, text=True, timeout=8)
                if p.returncode:
                    raise RuntimeError(p.stderr)
                rows = []
                for row in csv.reader(p.stdout.splitlines()):
                    values = dict(zip(fields, [x.strip() for x in row]))
                    rows.append(values)
                    if float(values['temperature.gpu']) >= 90:
                        ABORT_REASON = 'temperature reached 90 C: ' + values['uuid']
                        STOP.set()
                sample = {'epoch': time.time(), 'phase': PHASE, 'gpus': rows,
                          'loadavg': os.getloadavg()}
                f.write(json.dumps(sample) + '\n')
                atomic(ROOT / 'telemetry-latest.json', sample)
                failures = 0
            except Exception as exc:
                failures += 1
                f.write(json.dumps({'epoch': time.time(), 'phase': PHASE,
                                    'monitor_error': repr(exc)}) + '\n')
                if failures >= 3:
                    ABORT_REASON = 'three consecutive telemetry failures'
                    STOP.set()
            if STOP.is_set():
                try:
                    stop_container()
                except Exception:
                    pass
            MONITOR_DONE.wait(2)


def stage(name, command, timeout=150, env=None, visibility=None, cwd='/audit', required=False):
    global PHASE, PHASE_STARTED
    if STOP.is_set():
        raise RuntimeError(ABORT_REASON)
    assert subprocess.check_output(['systemctl', 'show', 'riscrivo-training.service',
                                   '--property=ActiveState', '--value'], text=True).strip() == 'inactive'
    PHASE, PHASE_STARTED = name, time.time()
    status()
    args = ['docker', 'run', '--rm', '--name', NAME, '--gpus', 'all', '--network', 'none',
            '--cpus', '6', '--memory', '8g', '--shm-size', '1g',
            '-v', str(ROOT) + ':/audit', '-w', cwd,
            '-e', 'OMP_NUM_THREADS=2', '-e', 'NCCL_DEBUG=WARN',
            '-e', 'LD_LIBRARY_PATH=/audit/nccl-sdk/lib:/usr/local/cuda/lib64:/usr/local/nvidia/lib64']
    if visibility:
        args += ['-e', 'CUDA_VISIBLE_DEVICES=' + visibility]
    for key, value in (env or {}).items():
        args += ['-e', key + '=' + str(value)]
    args += ['--entrypoint', command[0], IMAGE] + command[1:]
    log = ROOT / (name + '.log')
    print(json.dumps({'event': 'stage_start', 'name': name, 'epoch': PHASE_STARTED}), flush=True)
    timed_out = False
    with log.open('w') as f:
        proc = subprocess.Popen(args, stdout=f, stderr=subprocess.STDOUT)
        while proc.poll() is None:
            if STOP.is_set() or time.time() - PHASE_STARTED > timeout:
                timed_out = not STOP.is_set()
                stop_container()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                break
            time.sleep(1)
        rc = proc.wait()
    text = log.read_text(errors='replace')
    result = {'name': name, 'command': command, 'environment': env or {},
              'cuda_visible_devices': visibility or 'all', 'returncode': rc,
              'timed_out': timed_out, 'seconds': time.time() - PHASE_STARTED,
              'started_epoch': PHASE_STARTED, 'log': log.name}
    if name.startswith('stress_'):
        result['gpu_burn_ok'] = rc == 0 and 'DIED!' not in text and 'WARNING!' not in text and 'FAULTY' not in text
    RESULTS.append(result)
    atomic(ROOT / 'stages.json', RESULTS)
    print(json.dumps({'event': 'stage_end', **result}), flush=True)
    if required and (rc != 0 or timed_out or result.get('gpu_burn_ok') is False):
        raise RuntimeError('required stage failed: ' + name)
    status()
    return result


def bandwidth(name, test, size=512, samples=3, timeout=150):
    return stage(name, ['/audit/build/nvbandwidth/nvbandwidth', '-t', test,
                        '-b', str(size), '-i', str(samples), '-F', 'json'], timeout=timeout)


def main():
    global PHASE, PHASE_STARTED
    assert not (ROOT / 'stages.json').exists(), 'Do not overwrite an audit'
    assert subprocess.run(['systemctl', 'is-enabled', 'riscrivo-training.service'],
                          capture_output=True, text=True).stdout.strip() == 'disabled'
    before = {'started_epoch': time.time(), 'driver': subprocess.check_output(['nvidia-smi', '-q'], text=True),
              'kernel': subprocess.check_output(['journalctl', '-k', '-b', '--no-pager'], text=True),
              'power_settings_changed': False, 'training_started': False}
    atomic(ROOT / 'before.json', before)
    monitor = threading.Thread(target=telemetry, daemon=True)
    monitor.start()
    try:
        for dev in [0, 1]:
            stage('memory_gpu' + str(dev), ['python', '-u', '/audit/compute_checks.py',
                  '--mode', 'memory', '--device', str(dev), '--output', '/audit/memory_gpu' + str(dev) + '.json'],
                  timeout=240, required=True)
            stage('compute_gpu' + str(dev), ['python', '-u', '/audit/compute_checks.py',
                  '--mode', 'compute', '--device', str(dev), '--output', '/audit/compute_gpu' + str(dev) + '.json'],
                  timeout=240, required=True)
        # Tre taglie: overhead per piccoli blocchi e banda sostenuta su blocchi grandi.
        for size in [1, 16, 512]:
            for test in ['host_to_device_memcpy_ce', 'device_to_host_memcpy_ce']:
                bandwidth(test + '_' + str(size), test, size, samples=5)
        for test in ['device_local_copy', 'device_local_read_sm', 'device_local_write_sm',
                     'host_to_device_bidirectional_memcpy_ce', 'device_to_host_bidirectional_memcpy_ce',
                     'host_to_all_memcpy_ce', 'all_to_host_memcpy_ce', 'host_device_latency_sm']:
            bandwidth(test, test)
        # Stress con verifica dei risultati e circa l'80% della VRAM disponibile.
        for label, uuid in [('ada', ADA), ('a2000', A2000)]:
            stage('stress_single_' + label, ['./gpu_burn', '-m', '80%', '-tc', '300'],
                  timeout=360, visibility=uuid, cwd='/audit/sources/gpu-burn', required=True)
        stage('stress_dual_15min', ['./gpu_burn', '-m', '80%', '-tc', '900'],
              timeout=970, cwd='/audit/sources/gpu-burn', required=True)
        for dev in [0, 1]:
            stage('compute_hot_gpu' + str(dev), ['python', '-u', '/audit/compute_checks.py', '--mode', 'compute',
                  '--device', str(dev), '--output', '/audit/compute_hot_gpu' + str(dev) + '.json'],
                  timeout=240, required=True)
        # P2P dopo i collaudi individuali: un OK nel driver non prova il trasporto.
        sanity = bandwidth('peer_sanity_1MiB', 'device_to_device_memcpy_write_ce', 1, samples=1, timeout=45)
        if sanity['returncode'] == 0 and not sanity['timed_out']:
            for test in ['device_to_device_memcpy_read_ce', 'device_to_device_memcpy_write_ce',
                         'device_to_device_bidirectional_memcpy_write_ce',
                         'device_to_device_memcpy_read_sm', 'device_to_device_memcpy_write_sm',
                         'device_to_device_latency_sm']:
                bandwidth(test, test)
        stage('host_staged_gpu_transfers', ['python', '-u', '/audit/compute_checks.py', '--mode', 'staged',
                                          '--output', '/audit/host_staged_gpu_transfers.json'], timeout=120)
        for mode, env in [('default', {}), ('host_staged', {'NCCL_P2P_DISABLE': '1'})]:
            args = ['/audit/sources/nccl-tests/build/all_reduce_perf', '-b', '8', '-e', '128M', '-f', '2',
                    '-g', '2', '-w', '3', '-n', '10', '-c', '2', '-T', '25',
                    '-J', '/audit/nccl_' + mode + '.json']
            stage('nccl_allreduce_' + mode, args, env=env, timeout=120)
        PHASE, PHASE_STARTED = 'completed', time.time()
        status('COMPLETED')
    except Exception as exc:
        atomic(ROOT / 'error.json', {'error': repr(exc), 'phase': PHASE, 'epoch': time.time()})
        status('ABORTED' if STOP.is_set() else 'FAILED')
        raise
    finally:
        MONITOR_DONE.set()
        monitor.join(timeout=12)
        after = {'finished_epoch': time.time(),
                 'driver': subprocess.check_output(['nvidia-smi', '-q'], text=True, timeout=15),
                 'kernel': subprocess.check_output(['journalctl', '-k', '-b', '--no-pager'], text=True),
                 'training_service': subprocess.check_output(['systemctl', 'show', 'riscrivo-training.service',
                                      '--property=ActiveState,UnitFileState'], text=True)}
        atomic(ROOT / 'after.json', after)


if __name__ == '__main__':
    for sig in [signal.SIGTERM, signal.SIGINT]:
        signal.signal(sig, cancel)
    main()
