#!/usr/bin/env python3
"""List running processes containing trailing_bot.py or start_bot.py in their commandline.
Prints lines of the form: <pid>::: <commandline>
Prints NO_MATCH if none found.
"""
import psutil
found = False
for proc in psutil.process_iter(['pid','cmdline']):
    try:
        info = proc.info
        cmd = ' '.join(info.get('cmdline') or [])
        if 'trailing_bot.py' in cmd or 'start_bot.py' in cmd:
            print(f"{info.get('pid')}::: {cmd}")
            found = True
    except Exception:
        continue
if not found:
    print('NO_MATCH')
