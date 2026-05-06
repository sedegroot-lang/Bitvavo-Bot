"""Weekly performance report module.

Reads ``data/trade_archive.json`` and produces:
1. A JSON snapshot at ``data/weekly_reports/YYYY-Www.json``
2. A formatted Telegram message summarising the past 7 days

Designed to be called by ``scripts/automation/scheduler.py`` once a week
(Sunday 21:00 local). Idempotent: re-running for the same week overwrites
the snapshot but only sends Telegram if not already sent (tracked via
``data/weekly_reports/.last_sent``).

Usage:
    python -m bot.weekly_report           # generate + send (if new week)
    python -m bot.weekly_report --force   # always send
    python -m bot.weekly_report --dry     # generate snapshot only, no telegram
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = PROJECT_ROOT / "data" / "trade_archive.json"
REPORT_DIR = PROJECT_ROOT / "data" / "weekly_reports"
LAST_SENT = REPORT_DIR / ".last_sent"


def _load_trades() -> List[Dict[str, Any]]:
    if not ARCHIVE.exists():
        return []
    try:
        with ARCHIVE.open("r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception:
        return []
    if isinstance(data, dict):
        return list(data.get("trades") or data.get("closed") or [])
    if isinstance(data, list):
        return list(data)
    return []


def _trade_ts(trade: Dict[str, Any]) -> float:
    """Best-effort timestamp for a closed trade (sell time)."""
    for key in ("archived_at", "sell_ts", "closed_ts", "timestamp", "opened_ts"):
        v = trade.get(key)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return 0.0


def _filter_window(trades: Iterable[Dict[str, Any]], start_ts: float, end_ts: float) -> List[Dict[str, Any]]:
    return [t for t in trades if start_ts <= _trade_ts(t) < end_ts]


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        f = float(v)
        if f != f:  # NaN
            return default
        return f
    except (TypeError, ValueError):
        return default


def compute_report(trades: List[Dict[str, Any]], end_ts: float | None = None) -> Dict[str, Any]:
    """Compute the report for the 7 days ending at ``end_ts`` (default: now)."""
    end_ts = float(end_ts) if end_ts is not None else time.time()
    week_start = end_ts - 7 * 86400
    prev_week_start = week_start - 7 * 86400

    week = _filter_window(trades, week_start, end_ts)
    prev = _filter_window(trades, prev_week_start, week_start)

    def _summary(window: List[Dict[str, Any]]) -> Dict[str, Any]:
        n = len(window)
        if n == 0:
            return {
                "trades": 0, "pnl_eur": 0.0, "wins": 0, "losses": 0,
                "win_rate": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
                "best": None, "worst": None, "fees_eur": 0.0,
            }
        pnls = [_safe_float(t.get("profit")) for t in window]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        # Best / worst trade
        with_pnl = list(zip(window, pnls))
        best = max(with_pnl, key=lambda kv: kv[1])
        worst = min(with_pnl, key=lambda kv: kv[1])
        # Fee proxy: profit - profit_calculated (when present)
        fees_eur = 0.0
        for t, p in with_pnl:
            pc = t.get("profit_calculated")
            if isinstance(pc, (int, float)):
                fees_eur += abs(_safe_float(pc) - p)
        return {
            "trades": n,
            "pnl_eur": round(sum(pnls), 2),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / n * 100, 1),
            "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
            "best": {"market": best[0].get("market"), "pnl": round(best[1], 2)},
            "worst": {"market": worst[0].get("market"), "pnl": round(worst[1], 2)},
            "fees_eur": round(fees_eur, 2),
        }

    cur = _summary(week)
    pre = _summary(prev)

    # Per-market aggregation for current week
    per_market: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0})
    for t in week:
        m = str(t.get("market") or "")
        pnl = _safe_float(t.get("profit"))
        per_market[m]["trades"] += 1
        per_market[m]["pnl"] += pnl
        if pnl > 0:
            per_market[m]["wins"] += 1
    market_rows = sorted(
        ({"market": m, **{k: round(v, 2) if isinstance(v, float) else v for k, v in row.items()}}
         for m, row in per_market.items()),
        key=lambda r: r["pnl"], reverse=True,
    )

    # Reason distribution
    reason_counts = dict(Counter(str(t.get("reason") or "unknown") for t in week))

    # Delta vs previous week
    pnl_delta = round(cur["pnl_eur"] - pre["pnl_eur"], 2)
    trades_delta = cur["trades"] - pre["trades"]
    wr_delta = round(cur["win_rate"] - pre["win_rate"], 1)

    iso_year, iso_week, _ = datetime.fromtimestamp(week_start, tz=timezone.utc).isocalendar()
    return {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period": {
            "start": datetime.fromtimestamp(week_start, tz=timezone.utc).isoformat(),
            "end": datetime.fromtimestamp(end_ts, tz=timezone.utc).isoformat(),
            "iso_week": f"{iso_year}-W{iso_week:02d}",
        },
        "current": cur,
        "previous": pre,
        "delta": {"pnl_eur": pnl_delta, "trades": trades_delta, "win_rate": wr_delta},
        "per_market": market_rows[:20],
        "reasons": reason_counts,
    }


def format_telegram(report: Dict[str, Any]) -> str:
    cur = report["current"]
    delta = report["delta"]
    period = report["period"]["iso_week"]
    arrow_pnl = "↑" if delta["pnl_eur"] > 0 else ("↓" if delta["pnl_eur"] < 0 else "·")
    arrow_wr = "↑" if delta["win_rate"] > 0 else ("↓" if delta["win_rate"] < 0 else "·")

    lines: List[str] = []
    lines.append(f"📊 WEEKLY REPORT {period}")
    lines.append(f"PnL:  €{cur['pnl_eur']:+.2f} ({arrow_pnl} €{delta['pnl_eur']:+.2f} vs vorige week)")
    lines.append(f"Trades: {cur['trades']} ({delta['trades']:+d})  WR: {cur['win_rate']:.0f}% ({arrow_wr} {delta['win_rate']:+.1f}pp)")
    lines.append(f"Avg win: €{cur['avg_win']:+.2f}  Avg loss: €{cur['avg_loss']:+.2f}  Fees: €{cur['fees_eur']:.2f}")

    if cur["best"] and cur["best"]["market"]:
        lines.append(f"Beste: {cur['best']['market']} €{cur['best']['pnl']:+.2f}")
    if cur["worst"] and cur["worst"]["market"]:
        lines.append(f"Slechtste: {cur['worst']['market']} €{cur['worst']['pnl']:+.2f}")

    if report["per_market"]:
        lines.append("")
        lines.append("Top markten:")
        for row in report["per_market"][:5]:
            lines.append(f"  {row['market']}: €{row['pnl']:+.2f} ({row['trades']}x)")

    if report["reasons"]:
        lines.append("")
        lines.append("Exit-redenen: " + ", ".join(f"{k}={v}" for k, v in sorted(report["reasons"].items(), key=lambda kv: kv[1], reverse=True)[:5]))

    return "\n".join(lines)


def write_snapshot(report: Dict[str, Any]) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    name = report["period"]["iso_week"] + ".json"
    path = REPORT_DIR / name
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    tmp.replace(path)
    return path


def _already_sent(week_id: str) -> bool:
    if not LAST_SENT.exists():
        return False
    try:
        return LAST_SENT.read_text(encoding="utf-8").strip() == week_id
    except Exception:
        return False


def _mark_sent(week_id: str) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    LAST_SENT.write_text(week_id, encoding="utf-8")


def run(force: bool = False, dry: bool = False) -> Tuple[Dict[str, Any], Path, bool]:
    trades = _load_trades()
    report = compute_report(trades)
    snapshot = write_snapshot(report)
    sent = False
    if dry:
        return report, snapshot, sent
    week_id = report["period"]["iso_week"]
    if not force and _already_sent(week_id):
        return report, snapshot, sent
    msg = format_telegram(report)
    try:
        from notifier import send_telegram  # type: ignore
        send_telegram(msg)
        _mark_sent(week_id)
        sent = True
    except Exception as e:  # noqa: BLE001
        print(f"[weekly_report] telegram failed: {e}", file=sys.stderr)
    return report, snapshot, sent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="always send telegram")
    ap.add_argument("--dry", action="store_true", help="snapshot only, no telegram")
    ap.add_argument("--print", action="store_true", help="print formatted telegram message")
    args = ap.parse_args()

    report, snapshot, sent = run(force=args.force, dry=args.dry)
    print(f"snapshot: {snapshot}")
    print(f"sent: {sent}")
    if args.print or args.dry:
        print()
        print(format_telegram(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
