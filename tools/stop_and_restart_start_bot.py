"""
Stops all python processes that appear to belong to this repository (commandline contains repo path),
then starts a single `start_bot.py` instance.

Run from the repository venv: python tools/stop_and_restart_start_bot.py
"""
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
print(f"Repo path: {REPO}")

try:
    import psutil
except Exception as exc:
    print("psutil is required for this script. Install with: pip install psutil")
    raise

me = os.getpid()
stopped = []
for p in psutil.process_iter(["pid", "cmdline", "exe"]):
    try:
        pid = int(p.info["pid"])
        if pid == me:
            continue
        cmd = p.info.get("cmdline") or []
        cmdstr = " ".join(cmd)
        exe = p.info.get("exe") or ""
        # consider process part of repo if repo path appears in cmdline or exe
        if str(REPO) in cmdstr or str(REPO) in str(exe):
            try:
                print(f"Stopping pid={pid}: {cmdstr}")
                p.kill()
                stopped.append(pid)
            except Exception as e:
                print(f"Could not stop pid={pid}: {e}")
    except Exception:
        continue

print(f"Stopped processes: {stopped}")
# small pause to let OS clear handles
time.sleep(1)

# Start a single start_bot.py using the venv python
python_exe = sys.executable
start_script = REPO / 'start_bot.py'
if not start_script.exists():
    print("start_bot.py not found, aborting.")
    sys.exit(1)

print(f"Starting start_bot.py with {python_exe}")
import subprocess
subprocess.Popen([python_exe, str(start_script)], cwd=str(REPO))
print("Launched start_bot.py; give it one second to initialize...")
time.sleep(1)

# Show remaining python processes in repo
remain = []
for p in psutil.process_iter(["pid", "cmdline", "exe"]):
    try:
        pid = int(p.info["pid"])
        cmd = p.info.get("cmdline") or []
        cmdstr = " ".join(cmd)
        exe = p.info.get("exe") or ""
        if str(REPO) in cmdstr or str(REPO) in str(exe):
            remain.append((pid, cmdstr))
    except Exception:
        continue

print("Remaining project-related python processes:")
for pid, cmd in remain:
    print(pid, cmd)

print("Done.")
