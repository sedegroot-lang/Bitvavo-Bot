"""Watchdog: monitors bot health and auto-restarts if unhealthy.

Usage:
    python scripts/watchdog.py           # Run once (for Task Scheduler)
    python scripts/watchdog.py --loop    # Continuous monitoring (60s interval)

Checks:
  1. Bot log heartbeat (last write < 120s)
  2. Python process alive (trailing_bot.py running)
  3. Dashboard health endpoint (/api/health)
  4. Memory usage (< 500MB total Python)

On failure: auto-restarts via start_automated.bat + sends Telegram alert.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import argparse
import logging
from pathlib import Path
from typing import Dict, List, Optional

# Project root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Watchdog] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "watchdog.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("watchdog")


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_heartbeat(max_age: float = 120.0) -> Dict:
    """Check if bot_log.txt was updated recently."""
    log_path = ROOT / "logs" / "bot_log.txt"
    if not log_path.exists():
        return {"check": "heartbeat", "ok": False, "reason": "bot_log.txt not found"}
    age = time.time() - log_path.stat().st_mtime
    ok = age < max_age
    return {
        "check": "heartbeat",
        "ok": ok,
        "age_seconds": round(age, 1),
        "reason": f"Last log {age:.0f}s ago" + ("" if ok else " (STALE)"),
    }


def check_process() -> Dict:
    """Check if trailing_bot.py is running."""
    try:
        import psutil
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            cmd = " ".join(proc.info.get("cmdline") or [])
            if "trailing_bot" in cmd and "python" in proc.info.get("name", "").lower():
                return {"check": "process", "ok": True, "pid": proc.info["pid"]}
        return {"check": "process", "ok": False, "reason": "trailing_bot.py not running"}
    except ImportError:
        # Fallback without psutil
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq python.exe"],
                capture_output=True, text=True, timeout=10,
            )
            if "python.exe" in result.stdout:
                return {"check": "process", "ok": True, "reason": "python.exe found (psutil unavailable)"}
            return {"check": "process", "ok": False, "reason": "python.exe not found"}
        except Exception as e:
            return {"check": "process", "ok": False, "reason": str(e)}


def check_dashboard_health() -> Dict:
    """Check /api/health endpoint."""
    try:
        import requests
        resp = requests.get("http://127.0.0.1:5000/api/health", timeout=5)
        if resp.ok:
            data = resp.json()
            status = data.get("status", "unknown")
            return {"check": "dashboard", "ok": status in ("ok", "warning"), "status": status}
        return {"check": "dashboard", "ok": False, "reason": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"check": "dashboard", "ok": False, "reason": str(e)[:100]}


def check_memory(max_mb: float = 500.0) -> Dict:
    """Check total Python memory usage."""
    try:
        import psutil
        total_mb = 0.0
        for proc in psutil.process_iter(["name", "memory_info"]):
            if proc.info.get("name") and "python" in proc.info["name"].lower():
                mem = proc.info.get("memory_info")
                if mem:
                    total_mb += mem.rss / (1024 * 1024)
        ok = total_mb < max_mb
        return {"check": "memory", "ok": ok, "total_mb": round(total_mb, 1), "limit_mb": max_mb}
    except ImportError:
        return {"check": "memory", "ok": True, "reason": "psutil unavailable"}


def check_error_rate(max_errors: int = 50) -> Dict:
    """Count ERROR/CRITICAL in last 500 log lines."""
    log_path = ROOT / "logs" / "bot_log.txt"
    if not log_path.exists():
        return {"check": "error_rate", "ok": True, "count": 0}
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-500:]
        count = sum(1 for l in lines if "ERROR" in l or "CRITICAL" in l)
        return {"check": "error_rate", "ok": count < max_errors, "count": count, "limit": max_errors}
    except Exception as e:
        return {"check": "error_rate", "ok": True, "reason": str(e)[:100]}


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def send_telegram_alert(message: str) -> None:
    """Send alert via Telegram."""
    try:
        config_path = ROOT / "config" / "bot_config.json"
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        token = cfg.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = cfg.get("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            return
        import requests
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": f"🔧 WATCHDOG:\n{message}", "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        log.error(f"Telegram alert failed: {e}")


def restart_bot() -> bool:
    """Restart bot via start_automated.bat."""
    bat_path = ROOT / "start_automated.bat"
    if not bat_path.exists():
        log.error(f"start_automated.bat not found at {bat_path}")
        return False
    try:
        # Kill existing Python processes first
        subprocess.run(["taskkill", "/F", "/IM", "python.exe"],
                       capture_output=True, timeout=10)
        time.sleep(3)
        # Start bot
        subprocess.Popen(
            ["cmd", "/c", str(bat_path)],
            cwd=str(ROOT),
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        log.info("Bot restart initiated via start_automated.bat")
        return True
    except Exception as e:
        log.error(f"Restart failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Main watchdog loop
# ---------------------------------------------------------------------------

def run_checks() -> List[Dict]:
    """Run all health checks and return results."""
    checks = [
        check_heartbeat(),
        check_process(),
        check_dashboard_health(),
        check_memory(),
        check_error_rate(),
    ]
    return checks


def watchdog_cycle() -> bool:
    """Run one watchdog cycle. Returns True if healthy."""
    checks = run_checks()
    failed = [c for c in checks if not c["ok"]]

    if not failed:
        log.info(f"✅ All {len(checks)} checks passed")
        return True

    # Critical failures: no process or stale heartbeat
    critical = [c for c in failed if c["check"] in ("process", "heartbeat")]
    warnings = [c for c in failed if c["check"] not in ("process", "heartbeat")]

    for c in failed:
        log.warning(f"❌ {c['check']}: {c.get('reason', 'FAILED')}")

    if critical:
        msg = "🔴 CRITICAL failures:\n" + "\n".join(
            f"- {c['check']}: {c.get('reason', 'FAILED')}" for c in critical
        )
        log.error(msg)
        send_telegram_alert(msg)

        log.info("Initiating auto-restart...")
        success = restart_bot()
        if success:
            send_telegram_alert("✅ Bot restart initiated by watchdog")
        else:
            send_telegram_alert("❌ Bot restart FAILED — manual intervention needed")
        return False

    if warnings:
        msg = "⚠️ Warnings:\n" + "\n".join(
            f"- {c['check']}: {c.get('reason', str(c))}" for c in warnings
        )
        log.warning(msg)
        send_telegram_alert(msg)

    return True


def main():
    parser = argparse.ArgumentParser(description="Bot health watchdog")
    parser.add_argument("--loop", action="store_true", help="Continuous monitoring (60s interval)")
    parser.add_argument("--interval", type=int, default=60, help="Check interval in seconds")
    args = parser.parse_args()

    log.info(f"Watchdog started (loop={args.loop}, interval={args.interval}s)")

    if args.loop:
        while True:
            try:
                watchdog_cycle()
            except Exception as e:
                log.error(f"Watchdog cycle error: {e}")
            time.sleep(args.interval)
    else:
        healthy = watchdog_cycle()
        sys.exit(0 if healthy else 1)


if __name__ == "__main__":
    main()
