"""Dashboard V2 watchdog.

Monitors the FastAPI dashboard at http://127.0.0.1:5002/api/health.
If the endpoint returns "bot_online: false" with heartbeat_age_s null
for 3 consecutive checks (≈90s) while the heartbeat file IS fresh,
this means the uvicorn process has gone stale (Windows file-handle
issue, OneDrive sync glitch, etc.) and we restart it.

Run as a background task:
    pythonw scripts/dashboard_v2_watchdog.py

Logs to logs/dashboard_v2_watchdog.log
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
HB_FILE = ROOT / "data" / "heartbeat.json"
LOG = ROOT / "logs" / "dashboard_v2_watchdog.log"
LOG.parent.mkdir(parents=True, exist_ok=True)

CHECK_INTERVAL_S = 30
STALE_THRESHOLD = 3   # consecutive bad checks -> restart
HEALTH_URL = "http://127.0.0.1:5002/api/health"


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def heartbeat_fresh() -> bool:
    """True if heartbeat.json was written in the last 3 minutes."""
    try:
        with HB_FILE.open("r", encoding="utf-8-sig") as f:
            d = json.load(f)
        ts = d.get("ts") or d.get("timestamp") or 0
        return (time.time() - float(ts)) < 180
    except Exception:
        return False


def dashboard_healthy() -> bool:
    try:
        with urlopen(HEALTH_URL, timeout=5) as r:
            d = json.loads(r.read().decode("utf-8"))
        # Healthy = bot_online is True OR heartbeat_age_s is a finite number
        age = d.get("heartbeat_age_s")
        return d.get("bot_online") is True or (isinstance(age, (int, float)) and age < 300)
    except (URLError, OSError, json.JSONDecodeError):
        return False


def kill_dashboard() -> None:
    """Kill any python.exe whose CommandLine matches dashboard_v2."""
    if os.name != "nt":
        subprocess.run(["pkill", "-f", "dashboard_v2"], check=False)
        return
    cmd = (
        "Get-Process python -ErrorAction SilentlyContinue | "
        "ForEach-Object { try { $c = (Get-CimInstance Win32_Process -Filter \"ProcessId=$($_.Id)\").CommandLine; "
        "if ($c -match 'dashboard_v2') { Stop-Process -Id $_.Id -Force } } catch {} }"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", cmd], check=False)


def start_dashboard() -> None:
    py = ROOT / ".venv" / "Scripts" / "python.exe"
    if not py.exists():
        py = Path(sys.executable)
    args = [
        str(py), "-m", "uvicorn",
        "tools.dashboard_v2.backend.main:app",
        "--host", "0.0.0.0", "--port", "5002",
        "--log-level", "warning",
    ]
    creationflags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    subprocess.Popen(args, cwd=str(ROOT), creationflags=creationflags,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    log("Watchdog started")
    bad_streak = 0
    last_restart = 0.0
    while True:
        try:
            healthy = dashboard_healthy()
            hb_ok = heartbeat_fresh()
            if not healthy:
                bad_streak += 1
                log(f"unhealthy check {bad_streak}/{STALE_THRESHOLD} (heartbeat_fresh={hb_ok})")
            else:
                if bad_streak:
                    log(f"recovered after {bad_streak} bad checks")
                bad_streak = 0
            # Trigger restart only if heartbeat IS fresh (so it's the dashboard's fault)
            # AND we haven't restarted in the last 5 min (avoid loops).
            if bad_streak >= STALE_THRESHOLD and hb_ok and (time.time() - last_restart) > 300:
                log("=== RESTARTING dashboard (stale uvicorn) ===")
                kill_dashboard()
                time.sleep(2)
                start_dashboard()
                last_restart = time.time()
                bad_streak = 0
                time.sleep(15)  # let it boot
        except Exception as e:  # never die
            log(f"watchdog loop error: {e}")
        time.sleep(CHECK_INTERVAL_S)


if __name__ == "__main__":
    sys.exit(main())
