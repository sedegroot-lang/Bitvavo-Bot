import time
import psutil
import json
from pathlib import Path

REPO = str(Path(__file__).resolve().parents[1])
TIMEOUT = 60.0
INTERVAL = 0.1

def parent_chain(pid):
    chain = []
    try:
        cur = psutil.Process(pid)
        while cur is not None:
            try:
                chain.append({'pid': cur.pid, 'cmdline': cur.cmdline(), 'exe': cur.exe()})
            except Exception:
                chain.append({'pid': getattr(cur,'pid',None), 'cmdline': [], 'exe': ''})
            try:
                cur = cur.parent()
            except Exception:
                break
    except Exception:
        pass
    return chain

end = time.time() + TIMEOUT
found = False
print(f"[catch_startbot_simple] watching up to {TIMEOUT}s for start_bot.py (repo={REPO})")
while time.time() < end and not found:
    for p in psutil.process_iter(['pid','cmdline','cwd','exe','ppid']):
        info = p.info
        cmd = info.get('cmdline') or []
        if any('start_bot.py' in str(x) for x in cmd):
            pid = info.get('pid')
            cwd = info.get('cwd') or ''
            exe = info.get('exe') or ''
            if cwd.startswith(REPO) or exe.startswith(REPO) or REPO in ' '.join(cmd):
                out = {
                    'pid': pid,
                    'cwd': cwd,
                    'exe': exe,
                    'cmdline': cmd,
                    'ppid': info.get('ppid'),
                    'parent_chain': parent_chain(pid),
                    'time': time.time(),
                }
                print(json.dumps(out, default=str))
                found = True
                break
    if not found:
        time.sleep(INTERVAL)

if not found:
    print('NO_START_BOT_FOUND')
