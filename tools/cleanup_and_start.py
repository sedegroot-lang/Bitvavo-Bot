"""Safely archive logs, stop bot-related processes from this repo, and start a single start_bot.py.

Behavior:
- Archive logs/* to archive/logs/<timestamp>/
- Find running processes that reference repo scripts (same logic as check_bot_processes)
  and that appear to have cwd inside the repo or cmdline containing the repo path.
- For each process: try .terminate(); wait up to 5s; if still alive, .kill().
- Start a single start_bot.py using the venv python via subprocess Start-Process (PowerShell)

This script runs locally and prints a JSON summary at the end.
"""
import shutil
import time
import json
from pathlib import Path
import psutil
import subprocess
import os

BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BASE_DIR / 'logs'
ARCHIVE_DIR = BASE_DIR / 'archive' / 'logs'
SCRIPTS = [
    "start_bot.py",
    "monitor.py",
    "trailing_bot.py",
    "ai_supervisor.py",
    "auto_retrain.py",
    "tools/auto_retrain.py",
    "dashboard_watchdog.py",
]

def archive_logs():
    ts = time.strftime('%Y%m%dT%H%M%S')
    dest = ARCHIVE_DIR / ts
    dest.mkdir(parents=True, exist_ok=True)
    moved = []
    if not LOGS_DIR.exists():
        return moved, str(dest)
    for f in LOGS_DIR.iterdir():
        try:
            if f.is_file():
                shutil.move(str(f), str(dest / f.name))
                moved.append(f.name)
        except Exception:
            continue
    return moved, str(dest)


def find_bot_processes():
    repo_path = str(BASE_DIR)
    found = []
    for p in psutil.process_iter(['pid','cmdline','cwd','exe','name']):
        try:
            pid = int(p.info.get('pid') or 0)
            if pid == os.getpid():
                continue
            cmd = p.info.get('cmdline') or []
            cmdline = ' '.join(str(x) for x in cmd)
            cwd = p.info.get('cwd') or ''
            exe = p.info.get('exe') or ''
            match = False
            for s in SCRIPTS:
                if s in cmdline or os.path.basename(s) in cmdline:
                    match = True
                    break
            if not match:
                continue
            # Ensure this process is from the repo (safety)
            if (cwd and str(cwd).startswith(repo_path)) or (repo_path in cmdline) or (exe and str(exe).startswith(repo_path)):
                found.append({'pid': pid, 'cmdline': cmdline, 'cwd': cwd, 'exe': exe})
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception:
            continue
    return found


def stop_process(pid: int, timeout: float = 5.0):
    try:
        p = psutil.Process(pid)
    except Exception:
        return {'pid': pid, 'status': 'not_found'}
    try:
        p.terminate()
    except Exception:
        pass
    try:
        p.wait(timeout=timeout)
        return {'pid': pid, 'status': 'terminated'}
    except psutil.TimeoutExpired:
        try:
            p.kill()
            p.wait(timeout=3)
            return {'pid': pid, 'status': 'killed'}
        except Exception:
            return {'pid': pid, 'status': 'failed_to_kill'}
    except Exception:
        return {'pid': pid, 'status': 'error'}


def start_start_bot():
    venv_python = BASE_DIR / '.venv' / 'Scripts' / 'python.exe'
    python_exec = str(venv_python) if venv_python.exists() else 'python'
    # Use PowerShell Start-Process to launch detached so it keeps running after this script exits
    cmd = [
        'powershell',
        '-NoProfile',
        '-Command',
        f"Start-Process -FilePath '{python_exec}' -ArgumentList 'start_bot.py --allow-no-operator' -WorkingDirectory '{str(BASE_DIR)}' -WindowStyle Hidden -PassThru | Select-Object -ExpandProperty Id"
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if proc.returncode == 0 and proc.stdout.strip():
            new_pid = int(proc.stdout.strip())
            return {'pid': new_pid, 'status': 'started', 'cmd': ' '.join(cmd)}
        else:
            return {'pid': None, 'status': 'failed', 'stdout': proc.stdout, 'stderr': proc.stderr}
    except Exception as e:
        return {'pid': None, 'status': 'error', 'error': str(e)}


def main():
    summary = {'archived': None, 'found': None, 'stopped': [], 'started': None}
    moved, dest = archive_logs()
    summary['archived'] = {'moved': moved, 'dest': dest}

    found = find_bot_processes()
    summary['found'] = found

    # Stop in order: children first (sort descending pid) to try to stop helpers before managers
    pids = sorted([f['pid'] for f in found], reverse=True)
    for pid in pids:
        res = stop_process(pid, timeout=5.0)
        summary['stopped'].append(res)

    # small pause
    time.sleep(1)
    started = start_start_bot()
    summary['started'] = started

    print(json.dumps(summary, indent=2))

if __name__ == '__main__':
    main()
