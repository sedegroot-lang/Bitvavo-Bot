"""
Controleer op dubbele bot-processen in de Bitvavo Bot map.
Toont scripts die meer dan één keer actief zijn, met hun PID's en commandlines.
"""
import os
from pathlib import Path
try:
    import psutil
except ImportError:
    print("psutil is vereist. Installeer met: pip install psutil")
    exit(1)

BASE_DIR = Path(__file__).resolve().parent
SCRIPTS = [
    "start_bot.py",
    "monitor.py",
    "trailing_bot.py",
    "ai_supervisor.py",
    "auto_retrain.py",
    "tools/auto_retrain.py",
    "dashboard_watchdog.py",
]

def main():
    print(f"Dubbele bot-processen in: {BASE_DIR}\n")
    script_pids = {}
    for proc in psutil.process_iter(["pid", "cmdline", "cwd"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            pid = proc.info.get("pid")
            for script in SCRIPTS:
                if any(script in str(part) for part in cmdline):
                    script_pids.setdefault(script, []).append((pid, ' '.join(cmdline)))
        except Exception:
            continue
    found = False
    for script, plist in script_pids.items():
        if len(plist) > 1:
            found = True
            print(f"Script: {script} - {len(plist)} instanties:")
            for pid, cmd in plist:
                print(f"  PID: {pid} | Commandline: {cmd}")
            print("-"*40)
    if not found:
        print("Geen dubbele bot-processen gevonden.")

if __name__ == "__main__":
    main()
