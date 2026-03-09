import psutil
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS = [
    "start_bot.py",
    "monitor.py",
    "trailing_bot.py",
    "ai_supervisor.py",
    "auto_retrain.py",
    "tools/auto_retrain.py",
    "dashboard_watchdog.py",
]

def ancestor_chain(pid):
    chain = []
    try:
        p = psutil.Process(pid)
        while True:
            parent = p.parent()
            if not parent:
                break
            chain.append(parent.pid)
            p = parent
    except Exception:
        pass
    return chain

found = []
for p in psutil.process_iter(['pid','ppid','name','username','exe','cmdline','cwd','create_time']):
    try:
        cmdline_list = p.info.get('cmdline') or []
        cmd = ' '.join(cmdline_list)
        for s in SCRIPTS:
            if s in cmd:
                anc = ancestor_chain(p.info['pid'])
                # check if any ancestor commandline contains start_bot.py
                owned_by_start_bot = False
                owner_start_bot_pid = None
                for a in anc:
                    try:
                        pa = psutil.Process(a)
                        plc = ' '.join(pa.cmdline() or [])
                        if 'start_bot.py' in plc:
                            owned_by_start_bot = True
                            owner_start_bot_pid = a
                            break
                    except Exception:
                        continue
                found.append({
                    'pid': p.info['pid'],
                    'ppid': p.info.get('ppid'),
                    'name': p.info.get('name'),
                    'username': p.info.get('username'),
                    'cmdline': cmd,
                    'cwd': p.info.get('cwd'),
                    'create_time': p.info.get('create_time'),
                    'ancestors': anc,
                    'owned_by_start_bot': owned_by_start_bot,
                    'owner_start_bot_pid': owner_start_bot_pid,
                })
                break
    except Exception:
        continue

print(json.dumps(sorted(found, key=lambda x: x['pid']), indent=2))
