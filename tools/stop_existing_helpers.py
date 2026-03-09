#!/usr/bin/env python3
"""
Helper: stop existing monitor.py and ai_supervisor.py processes that belong to this repo.
Usage: run from project root with the venv python.
"""
import os
import time
import signal

repo = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))

try:
    import psutil
except Exception:
    psutil = None

found = {"monitor": [], "ai_supervisor": []}

if psutil:
    for p in psutil.process_iter(["pid", "cmdline", "cwd"]):
        try:
            pid = int(p.info.get("pid") or 0)
            if pid == os.getpid():
                continue
            cmd = p.info.get("cmdline") or []
            cmdline = " ".join(str(x) for x in cmd)
            cwd = p.info.get("cwd") or ''
            # Heuristic: presence of script name in cmdline and repo path in cwd or cmdline
            if ("monitor.py" in cmdline or os.path.basename("monitor.py") in cmdline) and (cwd.startswith(repo) or repo in cmdline):
                found["monitor"].append(pid)
            if ("ai_supervisor.py" in cmdline or os.path.basename("ai_supervisor.py") in cmdline) and (cwd.startswith(repo) or repo in cmdline):
                found["ai_supervisor"].append(pid)
        except Exception:
            continue
else:
    # Best-effort fallback for Windows without psutil
    import subprocess
    try:
        p = subprocess.run([
            "wmic", "process", "where", "name='python.exe'", "get", "ProcessId,CommandLine", "/format:csv"
        ], capture_output=True, text=True, timeout=10)
        lines = p.stdout.splitlines()
        for line in lines[1:]:
            try:
                parts = line.split(',', 2)
                if len(parts) < 3:
                    continue
                cmdline = parts[1] or ''
                pid = int(parts[2])
                if 'monitor.py' in cmdline and repo in cmdline:
                    found['monitor'].append(pid)
                if 'ai_supervisor.py' in cmdline and repo in cmdline:
                    found['ai_supervisor'].append(pid)
            except Exception:
                continue
    except Exception:
        pass

print("Found candidates:", found)

results = {"stopped": [], "failed": []}

for role in ('monitor', 'ai_supervisor'):
    for pid in list(found[role]):
        try:
            print(f"Stopping pid={pid} for {role}...", flush=True)
            if psutil:
                p = psutil.Process(pid)
                # Try graceful first
                try:
                    if os.name == 'nt':
                        # send CTRL_BREAK_EVENT only works for process groups; try terminate first
                        p.terminate()
                    else:
                        p.terminate()
                except Exception:
                    try:
                        p.kill()
                    except Exception:
                        pass
                try:
                    p.wait(timeout=5)
                    print(f"Stopped pid={pid}")
                    results['stopped'].append(pid)
                    continue
                except Exception:
                    try:
                        p.kill()
                    except Exception:
                        pass
                    try:
                        p.wait(timeout=3)
                        results['stopped'].append(pid)
                        continue
                    except Exception:
                        results['failed'].append(pid)
            else:
                # Windows fallback using taskkill
                try:
                    subprocess.run(["taskkill", "/PID", str(pid), "/T"], timeout=5)
                    results['stopped'].append(pid)
                    continue
                except Exception:
                    try:
                        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=5)
                        results['stopped'].append(pid)
                        continue
                    except Exception:
                        results['failed'].append(pid)
        except Exception as e:
            print(f"Error stopping pid={pid}: {e}")
            results['failed'].append(pid)

print('Results:', results)

# small sleep to let OS clean up
time.sleep(1)

# verify
still = {"monitor": [], "ai_supervisor": []}
if psutil:
    for p in psutil.process_iter(["pid", "cmdline", "cwd"]):
        try:
            pid = int(p.info.get("pid") or 0)
            cmd = p.info.get("cmdline") or []
            cmdline = " ".join(str(x) for x in cmd)
            cwd = p.info.get("cwd") or ''
            if ("monitor.py" in cmdline or os.path.basename("monitor.py") in cmdline) and (cwd.startswith(repo) or repo in cmdline):
                still['monitor'].append(pid)
            if ("ai_supervisor.py" in cmdline or os.path.basename("ai_supervisor.py") in cmdline) and (cwd.startswith(repo) or repo in cmdline):
                still['ai_supervisor'].append(pid)
        except Exception:
            continue

print('Still running after attempts:', still)

if results['failed']:
    print('\nSome processes could not be stopped automatically. You may need to inspect them manually or reboot.')
else:
    print('\nAll targeted processes stopped (or none were found).')
