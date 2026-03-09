#!/usr/bin/env python
"""Ensure only one `start_bot.py` runs for this repo.

Behaviour:
 - find running python processes whose cmdline contains 'start_bot.py' and whose cwd/exe points into this repo
 - terminate them (graceful terminate, then kill if they don't stop)
 - start a new `start_bot.py` with the venv python

Run from project root.
"""
import os
import time
import subprocess
from pathlib import Path

try:
    import psutil
except Exception:
    psutil = None

BASE_DIR = Path(__file__).resolve().parent.parent
VENV_PY = BASE_DIR / '.venv' / 'Scripts' / 'python.exe'
PY = str(VENV_PY) if VENV_PY.exists() else 'python'


def find_repo_startbot_pids():
    pids = []
    repo = str(BASE_DIR)
    if psutil is None:
        return pids
    for p in psutil.process_iter(['pid','cmdline','cwd','exe']):
        try:
            cmd = p.info.get('cmdline') or []
            if any('start_bot.py' in str(c) for c in cmd):
                cwd = (p.info.get('cwd') or '')
                exe = (p.info.get('exe') or '')
                if cwd.startswith(repo) or exe.startswith(repo) or repo in ' '.join(cmd):
                    pids.append(p.info['pid'])
        except Exception:
            continue
    return pids


def terminate_pid(pid: int, timeout: float = 3.0) -> bool:
    if psutil is None:
        return False
    try:
        p = psutil.Process(pid)
        print(f"Stopping PID {pid} (pid.cmdline={p.cmdline()})")
        p.terminate()
        try:
            p.wait(timeout=timeout)
            print(f"PID {pid} terminated cleanly.")
            return True
        except psutil.TimeoutExpired:
            print(f"PID {pid} did not exit within {timeout}s, killing...")
            p.kill()
            try:
                p.wait(timeout=2.0)
            except Exception:
                pass
            return not p.is_running()
    except psutil.NoSuchProcess:
        return True
    except Exception as e:
        print(f"Error stopping pid {pid}: {e}")
        return False


def main():
    print(f"Ensuring single start_bot for repo {BASE_DIR}")
    me = os.getpid()
    MAX_ATTEMPTS = 8
    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"Attempt {attempt}/{MAX_ATTEMPTS}")
        pids = find_repo_startbot_pids()
        pids = [p for p in pids if p != me]
        if pids:
            print("Found existing start_bot pids:", pids)
            for pid in pids:
                terminate_pid(pid)
            time.sleep(0.5)
        else:
            print("No existing start_bot processes found.")

        print("Starting start_bot.py now (capturing initial output)...")
        cmd = [PY, str(BASE_DIR / 'start_bot.py')]
        print('CMD:', cmd)
        try:
            proc = subprocess.Popen(cmd, cwd=str(BASE_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        except Exception as e:
            print(f"Failed to start start_bot.py: {e}")
            return

        # wait briefly to see if it exits immediately due to duplicate detection
        try:
            out, _ = proc.communicate(timeout=4)
        except subprocess.TimeoutExpired:
            # process still running after timeout -> success, stream remaining output
            print("start_bot is running (no immediate duplicate exit). Streaming output below (press Ctrl+C to stop):")
            try:
                for line in proc.stdout:
                    print(line, end='')
            except Exception:
                pass
            return

        # process exited quickly; inspect output
        print("start_bot exited quickly. Output:\n" + (out or ""))
        if 'Andere start_bot processen gedetecteerd' in (out or '') or 'start_bot lijkt al te draaien' in (out or ''):
            print("Detected duplicate exit; will retry after short delay.")
            # give some time for external launcher to settle
            time.sleep(0.8)
            continue
        else:
            # some other exit — show output and stop
            print("start_bot exited for another reason. Not retrying.")
            return

    print(f"Gave up after {MAX_ATTEMPTS} attempts. There may be an external launcher respawning start_bot.")


if __name__ == '__main__':
    main()
