"""Stop ALL python processes that reference known bot scripts in their commandline, regardless of cwd.
WARNING: This will stop processes even if they were launched from VSCode or other environments.
We attempt graceful termination first, then kill after timeout.
"""
import psutil
import time
import os
from pathlib import Path
import json

SCRIPTS = [
    "start_bot.py",
    "monitor.py",
    "trailing_bot.py",
    "ai_supervisor.py",
    "auto_retrain.py",
    "tools/auto_retrain.py",
    "dashboard_watchdog.py",
]

found = []
for p in psutil.process_iter(['pid','cmdline','name']):
    try:
        pid = int(p.info.get('pid') or 0)
        if pid == os.getpid():
            continue
    except Exception:
        continue
    try:
        cmd = p.info.get('cmdline') or []
        cmdline = ' '.join(str(x) for x in cmd)
        if any(s in cmdline for s in SCRIPTS):
            found.append({'pid': pid, 'cmdline': cmdline})
    except Exception:
        continue

result = {'found': found, 'stopped': []}
for item in found:
    pid = item['pid']
    try:
        proc = psutil.Process(pid)
    except Exception:
        result['stopped'].append({'pid': pid, 'status': 'not_found'})
        continue
    try:
        proc.terminate()
    except Exception:
        pass
    try:
        proc.wait(timeout=5)
        result['stopped'].append({'pid': pid, 'status': 'terminated'})
    except psutil.TimeoutExpired:
        try:
            proc.kill()
            proc.wait(timeout=3)
            result['stopped'].append({'pid': pid, 'status': 'killed'})
        except Exception:
            result['stopped'].append({'pid': pid, 'status': 'failed'})
    except Exception:
        result['stopped'].append({'pid': pid, 'status': 'error'})

print(json.dumps(result, indent=2))
