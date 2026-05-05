"""Trade Audit Trail — immutable event log for every trade state change.

Every buy, sell, DCA, SL, TP, sync, and config change is recorded as an
append-only JSON Lines (.jsonl) file. This ensures full traceability even
if trade_log.json is modified.

Usage:
    from modules.trade_audit import audit_log
    audit_log("BUY", "LINK-EUR", {"price": 7.50, "amount": 2.0, "invested": 15.0})
    audit_log("SELL", "LINK-EUR", {"price": 8.10, "profit": 0.85, "reason": "trailing"})
    audit_log("DCA", "LINK-EUR", {"level": 1, "price": 7.00, "amount": 5.0})
    audit_log("STALE_FIX", "LINK-EUR", {"old_bp": 0.50, "new_bp": 7.73})
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

# Audit log location
_ROOT = Path(__file__).resolve().parent.parent
_AUDIT_DIR = _ROOT / "data" / "audit"
_AUDIT_DIR.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()

# Valid event types
VALID_EVENTS = {
    "BUY",
    "SELL",
    "DCA",
    "PYRAMID",
    "SL_HARD",
    "SL_TRAILING",
    "SL_DRAWDOWN",
    "SL_MAX_AGE",
    "TP_PARTIAL",
    "TP_FULL",
    "SYNC_REMOVED",
    "SYNC_ADDED",
    "STALE_FIX",
    "CONFIG_CHANGE",
    "CIRCUIT_BREAKER",
    "RESTART",
    "ERROR",
    "DUST_SWEEP",
    "MANUAL_SELL",
    "GRID_BUY",
    "GRID_SELL",
}


def audit_log(
    event: str,
    market: str = "",
    details: Optional[Dict[str, Any]] = None,
    *,
    level: str = "info",
) -> None:
    """Append an audit event to today's audit log file.

    Parameters
    ----------
    event : str
        Event type (e.g., BUY, SELL, DCA, SL_HARD, STALE_FIX).
    market : str
        Market symbol (e.g., LINK-EUR).
    details : dict, optional
        Additional event details.
    level : str
        Log level (info, warning, error).
    """
    ts = time.time()
    date_str = time.strftime("%Y-%m-%d", time.localtime(ts))
    filename = f"audit_{date_str}.jsonl"
    filepath = _AUDIT_DIR / filename

    record = {
        "ts": ts,
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts)),
        "event": event,
        "market": market,
        "level": level,
    }
    if details:
        record["details"] = details

    line = json.dumps(record, ensure_ascii=False, default=str) + "\n"

    with _lock:
        try:
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass  # Audit should never crash the bot


def get_audit_events(
    date: Optional[str] = None,
    event_filter: Optional[str] = None,
    market_filter: Optional[str] = None,
    limit: int = 100,
) -> list:
    """Read audit events from a date's log file.

    Parameters
    ----------
    date : str, optional
        Date string YYYY-MM-DD. Defaults to today.
    event_filter : str, optional
        Filter by event type.
    market_filter : str, optional
        Filter by market.
    limit : int
        Max events to return (newest first).
    """
    if date is None:
        date = time.strftime("%Y-%m-%d")
    filepath = _AUDIT_DIR / f"audit_{date}.jsonl"
    if not filepath.exists():
        return []

    events = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event_filter and record.get("event") != event_filter:
                    continue
                if market_filter and record.get("market") != market_filter:
                    continue
                events.append(record)
    except Exception:
        return []

    # Return newest first, limited
    return events[-limit:][::-1]


def audit_summary(date: Optional[str] = None) -> Dict[str, Any]:
    """Generate a summary of today's audit events."""
    events = get_audit_events(date=date, limit=10000)
    if not events:
        return {"date": date or time.strftime("%Y-%m-%d"), "total": 0}

    by_type: Dict[str, int] = {}
    by_market: Dict[str, int] = {}
    errors = 0
    for e in events:
        evt = e.get("event", "UNKNOWN")
        mkt = e.get("market", "")
        by_type[evt] = by_type.get(evt, 0) + 1
        if mkt:
            by_market[mkt] = by_market.get(mkt, 0) + 1
        if e.get("level") == "error":
            errors += 1

    return {
        "date": date or time.strftime("%Y-%m-%d"),
        "total": len(events),
        "by_type": by_type,
        "by_market": by_market,
        "errors": errors,
    }


def cleanup_old_audits(max_days: int = 90) -> int:
    """Remove audit files older than max_days."""
    cutoff = time.time() - (max_days * 86400)
    removed = 0
    for f in _AUDIT_DIR.glob("audit_*.jsonl"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except Exception:
            pass
    return removed
