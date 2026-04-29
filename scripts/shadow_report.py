"""Shadow-trading aggregation reporter.

Reads `data/shadow_trades.json(l)` (output of the existing shadow tracker) and
produces an aggregated report: hypothetical PnL, win rate, and slippage of
signals that were generated but not executed (e.g. blocked by entry-confidence
or budget). Useful for tuning thresholds.

Usage:
    python -m scripts.shadow_report --since-days 7
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_records(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    # Try JSONL first, then fall back to JSON
    try:
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
        if records:
            return records
    except Exception:
        pass
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("trades"), list):
            return data["trades"]
    except Exception:
        pass
    return []


def aggregate(records: List[Dict[str, Any]], since_ts: Optional[float]) -> Dict[str, Any]:
    if since_ts is not None:
        records = [r for r in records if float(r.get("ts", 0) or 0) >= since_ts]
    if not records:
        return {"n": 0, "note": "no shadow records in window"}
    pnls = []
    for r in records:
        for k in ("hypothetical_pnl_eur", "pnl_eur", "expected_pnl_eur"):
            v = r.get(k)
            if v is not None:
                try:
                    pnls.append(float(v))
                    break
                except Exception:
                    pass
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)
    total = sum(pnls)
    avg = statistics.fmean(pnls) if pnls else 0.0
    by_reason: Dict[str, int] = {}
    for r in records:
        reason = str(r.get("blocked_reason") or r.get("reason") or "unknown")
        by_reason[reason] = by_reason.get(reason, 0) + 1
    return {
        "n": len(records),
        "n_with_pnl": len(pnls),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / len(pnls), 4) if pnls else 0.0,
        "pnl_total_eur": round(total, 2),
        "pnl_mean_eur": round(avg, 4),
        "blocked_by_reason": dict(sorted(by_reason.items(), key=lambda x: -x[1])),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default="")
    ap.add_argument("--since-days", type=float, default=7.0)
    args = ap.parse_args()

    candidates = [
        Path(args.path) if args.path else None,
        PROJECT_ROOT / "data" / "shadow_trades.jsonl",
        PROJECT_ROOT / "data" / "shadow_trades.json",
        PROJECT_ROOT / "logs" / "shadow_trades.jsonl",
    ]
    path = next((p for p in candidates if p and p.exists()), None)
    if path is None:
        print(json.dumps({"n": 0, "note": "no shadow log file found"}))
        return 0
    since_ts = time.time() - args.since_days * 86400.0 if args.since_days > 0 else None
    records = _load_records(path)
    summary = aggregate(records, since_ts)
    summary["source"] = str(path)
    summary["since_days"] = args.since_days
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
