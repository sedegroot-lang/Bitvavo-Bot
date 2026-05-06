"""Performance regression alerter.

Monitors the rolling window of recently closed trades and emits a Telegram
alert when performance deteriorates beyond configurable thresholds.

Triggers (any one is enough):
- Rolling win rate over last N trades drops below ``WR_FLOOR``.
- Cumulative PnL over last N trades is negative *and* below ``PNL_FLOOR``.
- Loss streak (consecutive losing trades) exceeds ``MAX_LOSS_STREAK``.

State and throttling:
- Uses ``data/regression_alert_state.json`` to throttle alerts (default
  one alert per 6 h).
- Idempotent and safe to call from a scheduled job.

Usage:
    python -m bot.regression_alerter           # check + alert (throttled)
    python -m bot.regression_alerter --force   # bypass throttle
    python -m bot.regression_alerter --dry     # check only, no telegram
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = PROJECT_ROOT / "data" / "trade_archive.json"
STATE_FILE = PROJECT_ROOT / "data" / "regression_alert_state.json"

# Defaults — overridable via CONFIG (REGRESSION_ALERT_*) at call time
DEFAULTS: Dict[str, Any] = {
    "WINDOW": 20,
    "WR_FLOOR": 0.50,           # 50%
    "PNL_FLOOR": -10.0,         # cumulative EUR
    "MAX_LOSS_STREAK": 4,
    "THROTTLE_HOURS": 6.0,
    "MIN_TRADES": 8,            # skip if fewer than this in window
}


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        f = float(v)
        if f != f:
            return default
        return f
    except (TypeError, ValueError):
        return default


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


def _trade_ts(t: Dict[str, Any]) -> float:
    for key in ("archived_at", "sell_ts", "closed_ts", "timestamp", "opened_ts"):
        v = t.get(key)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return 0.0


def _recent_trades(window: int) -> List[Dict[str, Any]]:
    trades = _load_trades()
    trades.sort(key=_trade_ts)
    return trades[-window:]


def _load_state() -> Dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: Dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def _config_overrides() -> Dict[str, Any]:
    """Pull optional REGRESSION_ALERT_* overrides from config without crashing."""
    try:
        from modules.config import CONFIG  # type: ignore
    except Exception:
        return {}
    out: Dict[str, Any] = {}
    for key, default in DEFAULTS.items():
        cfg_key = f"REGRESSION_ALERT_{key}"
        if cfg_key in CONFIG:
            try:
                out[key] = type(default)(CONFIG[cfg_key])
            except (TypeError, ValueError):
                pass
    return out


def evaluate(window: int | None = None) -> Dict[str, Any]:
    """Compute current metrics and which thresholds are breached."""
    cfg = {**DEFAULTS, **_config_overrides()}
    if window is not None:
        cfg["WINDOW"] = int(window)
    trades = _recent_trades(int(cfg["WINDOW"]))
    n = len(trades)
    if n < int(cfg["MIN_TRADES"]):
        return {"ok": True, "skipped": True, "reason": f"only {n} trades", "n": n, "config": cfg}

    pnls = [_safe_float(t.get("profit")) for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    win_rate = wins / n
    cum_pnl = sum(pnls)

    # Loss streak from the tail
    streak = 0
    for p in reversed(pnls):
        if p <= 0:
            streak += 1
        else:
            break

    breaches: List[str] = []
    if win_rate < float(cfg["WR_FLOOR"]):
        breaches.append(f"win_rate {win_rate*100:.0f}% < {float(cfg['WR_FLOOR'])*100:.0f}%")
    if cum_pnl < float(cfg["PNL_FLOOR"]):
        breaches.append(f"cum_pnl €{cum_pnl:+.2f} < €{float(cfg['PNL_FLOOR']):+.2f}")
    if streak >= int(cfg["MAX_LOSS_STREAK"]):
        breaches.append(f"loss_streak {streak} ≥ {int(cfg['MAX_LOSS_STREAK'])}")

    return {
        "ok": len(breaches) == 0,
        "skipped": False,
        "n": n,
        "win_rate": round(win_rate, 4),
        "cum_pnl": round(cum_pnl, 2),
        "loss_streak": streak,
        "breaches": breaches,
        "config": cfg,
        "worst_market": _worst_market(trades),
    }


def _worst_market(trades: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    agg: Dict[str, float] = {}
    for t in trades:
        m = str(t.get("market") or "")
        agg[m] = agg.get(m, 0.0) + _safe_float(t.get("profit"))
    if not agg:
        return None
    m, p = min(agg.items(), key=lambda kv: kv[1])
    return {"market": m, "pnl": round(p, 2)}


def format_telegram(result: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("⚠️ PERFORMANCE REGRESSIE")
    lines.append(f"Laatste {result['n']} trades:")
    lines.append(f"  WR: {result['win_rate']*100:.0f}%   Cum PnL: €{result['cum_pnl']:+.2f}   Loss-streak: {result['loss_streak']}")
    if result.get("worst_market"):
        wm = result["worst_market"]
        lines.append(f"  Slechtste markt: {wm['market']} €{wm['pnl']:+.2f}")
    lines.append("")
    lines.append("Trigger(s):")
    for b in result["breaches"]:
        lines.append(f"  • {b}")
    lines.append("")
    lines.append("Aanbevolen: check dashboard, overweeg MAX_OPEN_TRADES verlagen of slechtste markt blacklisten.")
    return "\n".join(lines)


def run(force: bool = False, dry: bool = False) -> Tuple[Dict[str, Any], bool]:
    result = evaluate()
    sent = False
    if dry or result.get("skipped") or result["ok"]:
        return result, sent

    state = _load_state()
    last_ts = float(state.get("last_alert_ts") or 0)
    throttle_s = float(result["config"]["THROTTLE_HOURS"]) * 3600
    if not force and (time.time() - last_ts) < throttle_s:
        result["throttled"] = True
        return result, sent

    msg = format_telegram(result)
    try:
        from notifier import send_telegram  # type: ignore
        send_telegram(msg)
        sent = True
        state["last_alert_ts"] = time.time()
        state["last_breaches"] = result["breaches"]
        state["last_metrics"] = {
            "win_rate": result["win_rate"],
            "cum_pnl": result["cum_pnl"],
            "loss_streak": result["loss_streak"],
        }
        _save_state(state)
    except Exception as e:  # noqa: BLE001
        print(f"[regression_alerter] telegram failed: {e}", file=sys.stderr)
    return result, sent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="bypass throttle")
    ap.add_argument("--dry", action="store_true", help="evaluate only, no telegram")
    ap.add_argument("--print", action="store_true", help="always print formatted alert")
    args = ap.parse_args()

    result, sent = run(force=args.force, dry=args.dry)
    print(json.dumps(result, indent=2))
    print(f"sent: {sent}")
    if args.print and result.get("breaches"):
        print()
        print(format_telegram(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
