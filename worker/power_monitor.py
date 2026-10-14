"""Durable, one-second NVIDIA telemetry for high-load worker diagnostics."""

import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / 'runtime' / 'power-monitor'
SAMPLE_FILE = OUTPUT_DIR / 'telemetry.jsonl'
PEAK_FILE = OUTPUT_DIR / 'peak.json'
RUN_FILE = OUTPUT_DIR / 'run.json'
RUNNING = True


def write_json(path, payload, append=False):
    mode = 'a' if append else 'w'
    with path.open(mode, encoding='utf-8') as stream:
        stream.write(json.dumps(payload, separators=(',', ':')) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def sample():
    result = subprocess.run([
        'nvidia-smi',
        '--query-gpu=index,power.draw,power.limit,temperature.gpu,utilization.gpu,memory.used',
        '--format=csv,noheader,nounits',
    ], capture_output=True, text=True, timeout=10, check=True)
    gpus = []
    for line in result.stdout.splitlines():
        values = [value.strip() for value in line.split(',')]
        gpus.append({
            'index': int(values[0]),
            'power_w': float(values[1]),
            'power_limit_w': float(values[2]),
            'temperature_c': int(values[3]),
            'utilization_pct': int(values[4]),
            'memory_mib': int(values[5]),
        })
    return gpus


def host_state():
    """Capture host pressure alongside GPU telemetry for post-reset diagnosis."""
    values = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        values[key] = int(value.split()[0]) * 1024
    load1, load5, load15 = (float(value) for value in Path('/proc/loadavg').read_text().split()[:3])
    return {
        'mem_available_bytes': values['MemAvailable'],
        'swap_free_bytes': values['SwapFree'],
        'load_average': [load1, load5, load15],
    }


def stop(*_):
    global RUNNING
    RUNNING = False


def main():
    global RUNNING
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(OUTPUT_DIR, 0o700)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    started = datetime.now(timezone.utc).isoformat()
    write_json(RUN_FILE, {'started_at': started, 'pid': os.getpid()})
    peak = {'started_at': started, 'total_power_w': 0.0, 'gpus': []}
    while RUNNING:
        timestamp = datetime.now(timezone.utc).isoformat()
        try:
            gpus = sample()
            total = round(sum(gpu['power_w'] for gpu in gpus), 2)
            record = {'timestamp': timestamp, 'total_power_w': total,
                      'gpus': gpus, 'host': host_state()}
            write_json(SAMPLE_FILE, record, append=True)
            if total >= peak['total_power_w']:
                peak = record
                write_json(PEAK_FILE, peak)
        except Exception as exc:
            write_json(SAMPLE_FILE, {'timestamp': timestamp, 'error': str(exc)}, append=True)
        for _ in range(10):
            if not RUNNING:
                break
            time.sleep(0.1)
    write_json(RUN_FILE, {'started_at': started,
                          'stopped_at': datetime.now(timezone.utc).isoformat(),
                          'pid': os.getpid()})


if __name__ == '__main__':
    main()
