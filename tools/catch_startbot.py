# Watch for start_bot.py processes and print details when found
import time
import psutil
import json
import os

REPO = os.path.abspath(os.getcwd())
TIMEOUT = 15.0
INTERVAL = 0.5

end = time.time() + TIMEOUT
seen = set()
while time.time() < end:
    for p in psutil.process_iter(['pid','cmdline','exe','cwd','create_time','ppid']):
        try:
            info = p.info
            cmd = info.get('cmdline') or []
            if any('start_bot.py' in (str(c) or '') for c in cmd):
                pid = info.get('pid')
                if pid in seen:
                    continue
                seen.add(pid)
                parent = None
                try:
                    par = p.parent()
                    parent = {'pid': par.pid, 'cmdline': par.cmdline()}
                except Exception:
                    parent = None
                out = {
                    'pid': pid,
                    'exe': info.get('exe') or '',
                    'cwd': info.get('cwd') or '',
                    'cmdline': cmd,
                    'ppid': info.get('ppid'),
                    'parent': parent,
                    'create_time': info.get('create_time'),
                }
                print(json.dumps(out, default=str))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if seen:
        break
    time.sleep(INTERVAL)

if not seen:
    print('NO_START_BOT_FOUND')
