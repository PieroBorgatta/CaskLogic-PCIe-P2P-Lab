#!/usr/bin/env python3
"""N3rdware curve: 30% at 40C, 100% at 80C. Restore firmware control on exit."""
import ctypes
import json
import signal
import sys
import time

nvml = ctypes.CDLL('libnvidia-ml.so.1')
nvml.nvmlErrorString.restype = ctypes.c_char_p
handle = ctypes.c_void_p()

def call(name, *args):
    result = getattr(nvml, name)(*args)
    if result:
        raise RuntimeError(name + ': ' + nvml.nvmlErrorString(result).decode())

def restore():
    call('nvmlDeviceSetDefaultFanSpeed_v2', handle, 0)

def stopping(signum, frame):
    raise SystemExit(0)

call('nvmlInit_v2')
call('nvmlDeviceGetHandleByIndex_v2', 0, ctypes.byref(handle))
signal.signal(signal.SIGTERM, stopping)
signal.signal(signal.SIGINT, stopping)
try:
    if '--restore' in sys.argv:
        restore()
    else:
        last = None
        last_log = 0
        while True:
            temperature = ctypes.c_uint()
            call('nvmlDeviceGetTemperature', handle, 0, ctypes.byref(temperature))
            target = max(30, min(100, round(30 + (temperature.value - 40) * 1.75)))
            if last is None or target >= last + 2 or target <= last - 2:
                call('nvmlDeviceSetFanSpeed_v2', handle, 0, target)
                last = target
            if time.monotonic() - last_log >= 30:
                print(json.dumps(dict(temperature_c=temperature.value, fan_percent=last)), flush=True)
                last_log = time.monotonic()
            time.sleep(2)
finally:
    restore()
    nvml.nvmlShutdown()
