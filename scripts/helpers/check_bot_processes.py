"""
Toon alle actieve bot-processen en helpers in de Bitvavo Bot map.
Geeft PID, scriptnaam, commandline en werkmap.
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
    print(f"Actieve bot-processen in: {BASE_DIR}\n")
    found = False
    for proc in psutil.process_iter(["pid", "cmdline", "cwd"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            cwd = proc.info.get("cwd") or ""
            pid = proc.info.get("pid")
            for script in SCRIPTS:
                if any(script in str(part) for part in cmdline):
                    print(f"PID: {pid}")
                    print(f"Script: {script}")
                    print(f"Commandline: {' '.join(cmdline)}")
                    print(f"Werkmap: {cwd}")
                    print("-"*40)
                    found = True
        except Exception:
            continue
    if not found:
        print("Geen actieve bot-processen gevonden.")

if __name__ == "__main__":
    main()
