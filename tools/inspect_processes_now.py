#!/usr/bin/env python3
import psutil
import sys
targets = ["monitor.py","ai_supervisor.py","dashboard_watchdog.py","trailing_bot.py","start_bot.py","tools/auto_retrain.py"]
found = False
for p in psutil.process_iter(["pid","cmdline","create_time","exe"]):
    try:
        cmd = ' '.join(p.info.get('cmdline') or [])
        for t in targets:
            if t in cmd:
                print(f"{t} ::: {p.pid} ::: {p.info.get('create_time')} ::: {cmd}")
                found = True
                break
    except Exception:
        pass
if not found:
    print('NO_MATCH')
