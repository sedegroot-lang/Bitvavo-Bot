"""Long-running watcher to catch transient start_bot.py processes and print parent chain.

Run this while you attempt to start the bot; it will print JSON for any start_bot process it sees.
"""
import time
import psutil
import json
import os
from pathlib import Path

REPO = str(Path(__file__).resolve().parents[1])
TIMEOUT = 90.0
INTERVAL = 0.2

def parent_chain(p):
    chain = []
    try:
        cur = p
        while cur is not None:
            try:
                info = {'pid': cur.pid, 'exe': cur.exe() if cur.exe() else '', 'cmdline': cur.cmdline()}
            except Exception:
                info = {'pid': getattr(cur, 'pid', None), 'exe': '', 'cmdline': []}
            chain.append(info)
            cur = cur.parent()
    except Exception:
        pass
    return chain

end = time.time() + TIMEOUT
seen = set()
print(f"[catch_startbot_long] watching for up to {TIMEOUT}s in repo {REPO}")
while time.time() < end:
    for p in psutil.process_iter(['pid','cmdline','cwd','exe','ppid']):
        try:
            info = p.info
            cmd = info.get('cmdline') or []
            if any('start_bot.py' in (str(c) or '') for c in cmd):
                pid = info.get('pid')
                if pid in seen:
                    continue
                seen.add(pid)
                p_obj = None
                try:
                    p_obj = psutil.Process(pid)
                except Exception:
                    p_obj = None
                parent = None
                try:
                    if p_obj is not None:
                        parent = parent_chain(p_obj.parent())
                except Exception:
                    parent = None
                out = {
                    'pid': pid,
                    'exe': info.get('exe') or '',
                    'cwd': info.get('cwd') or '',
                    'cmdline': cmd,
                    'ppid': info.get('ppid'),
                    'parent_chain': parent,
                    'time': time.time(),
                }
                print(json.dumps(out, default=str))
        except Exception:
            # ignore processes that disappear or we can't access and continue iteration
            continue
    if seen:
        break
    time.sleep(INTERVAL)

if not seen:
    print('NO_START_BOT_FOUND')
