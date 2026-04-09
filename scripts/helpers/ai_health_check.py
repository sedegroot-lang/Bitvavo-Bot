"""
AI Health Check — comprehensive bot diagnostics for Copilot sessions.

Run with:  python scripts/helpers/ai_health_check.py
Output:    JSON report + human-readable summary to stdout

Checks:
  1. Config vs Roadmap alignment (MAX_OPEN_TRADES, BASE, DCA, etc.)
  2. Open trades status (count, exposure, DCA depth)
  3. Recent performance (wins/losses last 7 days)
  4. Budget safety (EUR free vs min reserve)
  5. Process health (bot, AI, dashboard running?)
  6. Error log scan (recent errors in bot_log.txt)
  7. Test suite (optional: --run-tests)
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict | list | None:
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return None


def _file_age_seconds(path: Path) -> float | None:
    try:
        return time.time() - path.stat().st_mtime
    except Exception:
        return None


# ─── 1. Config Check ─────────────────────────────────────────────────────────

def check_config() -> dict:
    """Load merged config and return key trading parameters."""
    result = {"status": "ok", "issues": []}
    try:
        from modules.config import load_config
        cfg = load_config()
    except Exception as e:
        return {"status": "error", "issues": [f"Config load failed: {e}"]}

    result["values"] = {
        "MAX_OPEN_TRADES": cfg.get("MAX_OPEN_TRADES"),
        "BASE_AMOUNT_EUR": cfg.get("BASE_AMOUNT_EUR"),
        "DCA_AMOUNT_EUR": cfg.get("DCA_AMOUNT_EUR"),
        "DCA_DROP_PCT": cfg.get("DCA_DROP_PCT"),
        "DCA_SIZE_MULTIPLIER": cfg.get("DCA_SIZE_MULTIPLIER"),
        "DCA_MAX_BUYS": cfg.get("DCA_MAX_BUYS"),
        "MIN_SCORE_TO_BUY": cfg.get("MIN_SCORE_TO_BUY"),
        "DEFAULT_TRAILING": cfg.get("DEFAULT_TRAILING"),
        "GRID_ENABLED": cfg.get("GRID_TRADING", {}).get("enabled", False),
        "GRID_INVESTMENT": cfg.get("GRID_TRADING", {}).get("max_total_investment", 0),
    }

    # Sanity checks
    mot = cfg.get("MAX_OPEN_TRADES", 0)
    if mot < 3:
        result["issues"].append(f"MAX_OPEN_TRADES={mot} is below minimum 3!")
        result["status"] = "warning"
    if cfg.get("MIN_SCORE_TO_BUY", 0) < 6.0:
        result["issues"].append(f"MIN_SCORE_TO_BUY={cfg.get('MIN_SCORE_TO_BUY')} is dangerously low")
        result["status"] = "warning"

    return result


# ─── 2. Open Trades ──────────────────────────────────────────────────────────

def check_open_trades() -> dict:
    """Analyze current open trades."""
    result = {"status": "ok", "issues": [], "trades": []}
    trade_log = _load_json(PROJECT_ROOT / "data" / "trade_log.json")
    if trade_log is None:
        return {"status": "error", "issues": ["Cannot read trade_log.json"]}

    # trade_log.json has structure: {"open": {market: trade}, "closed": ..., "profits": ...}
    open_section = trade_log.get("open", {}) if isinstance(trade_log, dict) else {}
    # Fallback: if no 'open' key, try flat dict (legacy format)
    if not open_section and isinstance(trade_log, dict):
        open_section = {k: v for k, v in trade_log.items()
                        if isinstance(v, dict) and not v.get("sell_price") and k not in ("closed", "profits", "_save_ts")}

    open_trades = open_section

    total_exposure = 0.0
    for market, t in open_trades.items():
        invested = t.get("invested_eur", 0) or 0
        dca_buys = t.get("dca_buys", 0) or 0
        dca_max = t.get("dca_max") or t.get("DCA_MAX_BUYS", 17)
        total_exposure += invested
        trade_info = {
            "market": market,
            "invested_eur": round(invested, 2),
            "dca_buys": dca_buys,
            "dca_max": dca_max,
        }
        # Check for high DCA depth
        if dca_buys >= 10:
            result["issues"].append(f"{market}: DCA depth {dca_buys}/{dca_max} — deep position")
        result["trades"].append(trade_info)

    result["count"] = len(open_trades)
    result["total_exposure_eur"] = round(total_exposure, 2)
    return result


# ─── 3. Recent Performance ───────────────────────────────────────────────────

def check_performance(days: int = 7) -> dict:
    """Analyze closed trades from the last N days."""
    result = {"status": "ok", "issues": []}
    archive = _load_json(PROJECT_ROOT / "data" / "trade_archive.json")
    if archive is None:
        return {"status": "error", "issues": ["Cannot read trade_archive.json"]}

    cutoff = time.time() - (days * 86400)
    recent = []
    if isinstance(archive, list):
        recent = [t for t in archive if (t.get("closed_ts") or t.get("sell_ts") or 0) > cutoff]
    elif isinstance(archive, dict):
        for t in archive.values():
            if isinstance(t, dict) and (t.get("closed_ts") or t.get("sell_ts") or 0) > cutoff:
                recent.append(t)

    wins = sum(1 for t in recent if (t.get("profit", 0) or 0) > 0)
    losses = sum(1 for t in recent if (t.get("profit", 0) or 0) <= 0)
    total_pnl = sum(t.get("profit", 0) or 0 for t in recent)
    winrate = (wins / len(recent) * 100) if recent else 0

    result["period_days"] = days
    result["total_trades"] = len(recent)
    result["wins"] = wins
    result["losses"] = losses
    result["winrate_pct"] = round(winrate, 1)
    result["total_pnl_eur"] = round(total_pnl, 2)

    if winrate < 50 and len(recent) >= 5:
        result["issues"].append(f"Winrate {winrate:.0f}% is below 50% — consider pausing opschaling")
        result["status"] = "warning"

    return result


# ─── 4. Budget Safety ────────────────────────────────────────────────────────

def check_budget() -> dict:
    """Check EUR buffer and reserve requirements."""
    result = {"status": "ok", "issues": []}

    # Try to get account overview from cached data
    overview = _load_json(PROJECT_ROOT / "data" / "account_overview.json")
    if overview is None:
        result["status"] = "unknown"
        result["issues"].append("No account_overview.json — cannot check budget")
        return result

    eur_available = 0
    portfolio_value = 0
    if isinstance(overview, dict):
        eur_available = float(overview.get("eur_available", 0))
        portfolio_value = float(overview.get("total_account_value_eur", 0) or overview.get("total_eur", 0) or overview.get("portfolio_value", 0))

    result["eur_available"] = round(eur_available, 2)
    result["portfolio_value"] = round(portfolio_value, 2)

    if portfolio_value > 0:
        reserve_pct = eur_available / portfolio_value * 100
        result["reserve_pct"] = round(reserve_pct, 1)
        if reserve_pct < 15:
            result["issues"].append(
                f"EUR reserve {reserve_pct:.0f}% is below 15% minimum ({eur_available:.0f}/{portfolio_value:.0f})"
            )
            result["status"] = "warning"
    return result


# ─── 5. Process Health ────────────────────────────────────────────────────────

def check_processes() -> dict:
    """Check if key processes are running."""
    result = {"status": "ok", "issues": [], "processes": {}}

    # Check heartbeat
    hb = _load_json(PROJECT_ROOT / "data" / "heartbeat.json")
    if hb and isinstance(hb, dict):
        ts = hb.get("timestamp", 0)
        age = time.time() - ts if ts else 999999
        result["processes"]["bot"] = {
            "active": hb.get("bot_active", False),
            "heartbeat_age_s": round(age),
        }
        if age > 120:
            result["issues"].append(f"Bot heartbeat is {age:.0f}s old (>120s = stale)")
            result["status"] = "warning"
    else:
        result["issues"].append("No heartbeat.json found")
        result["status"] = "warning"

    # Check AI heartbeat
    ai_hb = _load_json(PROJECT_ROOT / "data" / "ai_heartbeat.json")
    if ai_hb and isinstance(ai_hb, dict):
        ts = ai_hb.get("timestamp", 0)
        age = time.time() - ts if ts else 999999
        result["processes"]["ai"] = {
            "active": True,
            "heartbeat_age_s": round(age),
        }

    # Check bot log freshness
    log_age = _file_age_seconds(PROJECT_ROOT / "logs" / "bot_log.txt")
    if log_age is not None:
        result["processes"]["log_age_s"] = round(log_age)

    return result


# ─── 6. Error Log Scan ───────────────────────────────────────────────────────

def check_errors(max_lines: int = 500) -> dict:
    """Scan recent bot_log.txt for errors."""
    result = {"status": "ok", "issues": [], "recent_errors": []}
    log_path = PROJECT_ROOT / "logs" / "bot_log.txt"

    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        result["issues"].append("Cannot read bot_log.txt")
        result["status"] = "unknown"
        return result

    # Scan last N lines for errors
    error_keywords = ["ERROR", "CRITICAL", "Traceback", "Exception", "saldo_error"]
    recent_errors = []
    for line in lines[-max_lines:]:
        for kw in error_keywords:
            if kw in line:
                recent_errors.append(line.strip()[:200])
                break

    result["recent_errors"] = recent_errors[-20:]  # Last 20 unique errors
    result["error_count"] = len(recent_errors)
    if len(recent_errors) > 10:
        result["issues"].append(f"{len(recent_errors)} errors in last {max_lines} log lines")
        result["status"] = "warning"

    return result


# ─── 7. Roadmap Alignment ────────────────────────────────────────────────────

def check_roadmap_alignment() -> dict:
    """Check if current config matches the active roadmap phase."""
    result = {"status": "ok", "issues": []}

    try:
        from modules.config import load_config
        cfg = load_config()
    except Exception:
        return {"status": "error", "issues": ["Cannot load config"]}

    # Current expected values from €1.200 phase
    # This gets updated when roadmap phase changes
    expected = {
        "phase": "€1.200",
        "MAX_OPEN_TRADES": 5,
        "BASE_AMOUNT_EUR": 62,
        "DCA_AMOUNT_EUR": 30,
        "DCA_DROP_PCT": 0.025,
        "MIN_SCORE_TO_BUY": 7.0,
        "DEFAULT_TRAILING": 0.024,
    }
    result["expected_phase"] = expected["phase"]

    for key, expected_val in expected.items():
        if key == "phase":
            continue
        actual = cfg.get(key)
        if actual is not None and abs(float(actual) - float(expected_val)) > 0.001:
            result["issues"].append(
                f"{key}: expected {expected_val} (roadmap {expected['phase']}), got {actual}"
            )
            result["status"] = "mismatch"

    return result


# ─── Main ─────────────────────────────────────────────────────────────────────

def run_health_check(run_tests: bool = False) -> dict:
    """Run all health checks and return combined report."""
    report = {
        "timestamp": datetime.now().isoformat(),
        "checks": {}
    }

    checks = [
        ("config", check_config),
        ("open_trades", check_open_trades),
        ("performance_7d", check_performance),
        ("budget", check_budget),
        ("processes", check_processes),
        ("errors", check_errors),
        ("roadmap_alignment", check_roadmap_alignment),
    ]

    overall_status = "ok"
    all_issues = []

    for name, fn in checks:
        try:
            result = fn()
        except Exception as e:
            result = {"status": "error", "issues": [f"Check failed: {e}"]}
        report["checks"][name] = result

        if result.get("status") not in ("ok", "unknown"):
            overall_status = "warning"
        all_issues.extend(result.get("issues", []))

    report["overall_status"] = overall_status
    report["all_issues"] = all_issues

    if run_tests:
        import subprocess
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short", "-q"],
                capture_output=True, text=True, timeout=120,
                cwd=str(PROJECT_ROOT),
            )
            report["checks"]["tests"] = {
                "status": "ok" if proc.returncode == 0 else "fail",
                "returncode": proc.returncode,
                "summary": proc.stdout.split("\n")[-3:] if proc.stdout else [],
                "issues": [f"Tests failed (rc={proc.returncode})"] if proc.returncode != 0 else [],
            }
            if proc.returncode != 0:
                overall_status = "warning"
                all_issues.append("Test suite has failures")
        except Exception as e:
            report["checks"]["tests"] = {"status": "error", "issues": [str(e)]}

    return report


def print_summary(report: dict) -> None:
    """Print human-readable summary."""
    status = report["overall_status"]
    icon = "✅" if status == "ok" else "⚠️"
    print(f"\n{icon}  Bot Health: {status.upper()}")
    print(f"   Timestamp: {report['timestamp']}")
    print()

    for name, check in report["checks"].items():
        s = check.get("status", "?")
        si = "✅" if s == "ok" else "⚠️" if s in ("warning", "mismatch") else "❌" if s in ("error", "fail") else "❓"
        print(f"  {si} {name}")

        # Print key values
        if name == "config" and "values" in check:
            v = check["values"]
            print(f"     MAX_TRADES={v.get('MAX_OPEN_TRADES')} BASE={v.get('BASE_AMOUNT_EUR')} "
                  f"DCA={v.get('DCA_AMOUNT_EUR')} SCORE={v.get('MIN_SCORE_TO_BUY')} "
                  f"TRAIL={v.get('DEFAULT_TRAILING')} GRID={v.get('GRID_ENABLED')}")
        elif name == "open_trades":
            print(f"     {check.get('count', '?')} open, €{check.get('total_exposure_eur', '?')} exposure")
            for t in check.get("trades", []):
                print(f"       {t['market']}: €{t['invested_eur']} (DCA {t['dca_buys']}/{t['dca_max']})")
        elif name == "performance_7d":
            print(f"     {check.get('total_trades', 0)} trades, "
                  f"{check.get('wins', 0)}W/{check.get('losses', 0)}L, "
                  f"winrate {check.get('winrate_pct', 0)}%, "
                  f"PnL €{check.get('total_pnl_eur', 0)}")
        elif name == "budget":
            print(f"     EUR free: €{check.get('eur_available', '?')} "
                  f"({check.get('reserve_pct', '?')}% reserve)")
        elif name == "roadmap_alignment":
            print(f"     Expected phase: {check.get('expected_phase', '?')}")

        # Print issues
        for issue in check.get("issues", []):
            print(f"     ⚠️  {issue}")

    if report["all_issues"]:
        print(f"\n  ── {len(report['all_issues'])} issue(s) found ──")
        for i in report["all_issues"]:
            print(f"    • {i}")
    else:
        print("\n  ── No issues found ──")


if __name__ == "__main__":
    run_tests = "--run-tests" in sys.argv
    report = run_health_check(run_tests=run_tests)
    print_summary(report)

    # Also save JSON report
    out_path = PROJECT_ROOT / "data" / "ai_health_report.json"
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"\n  Report saved to: {out_path}")
    except Exception:
        pass
