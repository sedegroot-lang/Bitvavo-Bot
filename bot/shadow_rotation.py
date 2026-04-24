"""
Shadow Capital Rotation — observation only, no trades executed.

Hypothesis: when MAX_OPEN_TRADES is reached and a high-quality candidate
appears, closing a "stale but positive" existing trade and opening the
candidate would generate higher net PnL than holding both.

This module logs what *would* have happened. Run evaluate() every bot
cycle (or call from a periodic scheduler). After ~2 weeks, run analyse()
to see the distribution of would-be rotations and outcomes.

Decision rule (conservative — same as docs/strategy advice):
  Rotate ONLY if all conditions hold:
    1. open_trades_count >= MAX_OPEN_TRADES
    2. candidate.score >= ROTATE_MIN_CANDIDATE_SCORE  (default 8.5)
    3. existing trade.age_hours >= ROTATE_MIN_AGE_HOURS  (default 48)
    4. existing trade.pnl_pct > 0  (only close winners — never lock in losses)
    5. existing trade.pnl_pct < ROTATE_MAX_STALE_PNL_PCT  (default 1.5%)
    6. existing trade has been "still" (|move_6h_pct| < 0.3) for 6h+
    7. candidate.expected_pct >= 2 * existing.pnl_pct + fees_pct (Kelly edge)

If a rotation is suggested, it gets logged to data/shadow_rotation.jsonl
with full context. NEVER mutates state, NEVER places orders.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = PROJECT_ROOT / "data" / "shadow_rotation.jsonl"

# Defaults — overridable via CONFIG
DEFAULTS = {
    "ROTATE_MIN_CANDIDATE_SCORE": 8.5,
    "ROTATE_MIN_AGE_HOURS": 48.0,
    "ROTATE_MAX_STALE_PNL_PCT": 1.5,
    "ROTATE_STILL_MOVE_PCT": 0.3,
    "ROTATE_FEES_PCT_ROUNDTRIP": 0.5,  # taker round-trip ~0.5% on Bitvavo
    "ROTATE_KELLY_EDGE_MULT": 2.0,
}


def _cfg(config: Optional[Dict[str, Any]], key: str) -> float:
    if config and key in config:
        try:
            return float(config[key])
        except (TypeError, ValueError):
            return float(DEFAULTS[key])
    return float(DEFAULTS[key])


def _now() -> float:
    return time.time()


def _safe_get(d: Dict[str, Any], *keys, default: Any = 0.0) -> Any:
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return default


def _trade_age_hours(trade: Dict[str, Any]) -> float:
    ts = _safe_get(trade, "opened_ts", "timestamp", default=0)
    try:
        ts = float(ts)
    except (TypeError, ValueError):
        return 0.0
    if ts <= 0:
        return 0.0
    return max(0.0, (_now() - ts) / 3600.0)


def _trade_pnl_pct(trade: Dict[str, Any], current_price: float) -> float:
    """Return unrealised PnL % vs cost basis."""
    try:
        buy = float(_safe_get(trade, "buy_price", default=0))
        if buy <= 0 or current_price <= 0:
            return 0.0
        return (current_price - buy) / buy * 100.0
    except (TypeError, ValueError):
        return 0.0


def _move_pct(prices: Sequence[float]) -> float:
    """% move from first to last in the price window."""
    if len(prices) < 2:
        return 0.0
    first, last = float(prices[0]), float(prices[-1])
    if first <= 0:
        return 0.0
    return abs(last - first) / first * 100.0


def evaluate(
    open_trades: Dict[str, Dict[str, Any]],
    candidates: Sequence[Dict[str, Any]],
    *,
    max_open_trades: int,
    current_prices: Optional[Dict[str, float]] = None,
    price_history_6h: Optional[Dict[str, Sequence[float]]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Evaluate whether to suggest any rotations. Returns list of suggestions
    (also appended to LOG_PATH). Never mutates input. Never places orders.

    candidates: list of dicts with at minimum {market, score, expected_pct?}
    """
    if not isinstance(open_trades, dict) or not candidates:
        return []
    if len(open_trades) < int(max_open_trades):
        return []  # No rotation needed — slot available

    min_score = _cfg(config, "ROTATE_MIN_CANDIDATE_SCORE")
    min_age = _cfg(config, "ROTATE_MIN_AGE_HOURS")
    max_stale = _cfg(config, "ROTATE_MAX_STALE_PNL_PCT")
    still_thr = _cfg(config, "ROTATE_STILL_MOVE_PCT")
    fees = _cfg(config, "ROTATE_FEES_PCT_ROUNDTRIP")
    edge_mult = _cfg(config, "ROTATE_KELLY_EDGE_MULT")
    current_prices = current_prices or {}
    price_history_6h = price_history_6h or {}

    # Top candidate by score
    cand = max(
        (c for c in candidates if isinstance(c, dict) and c.get("score") is not None),
        key=lambda c: float(c.get("score", 0) or 0),
        default=None,
    )
    if cand is None:
        return []
    cand_score = float(cand.get("score", 0) or 0)
    if cand_score < min_score:
        return []
    cand_expected = float(cand.get("expected_pct", 0) or 0)  # may be 0 if unknown

    suggestions: List[Dict[str, Any]] = []
    now = _now()

    for market, trade in open_trades.items():
        if not isinstance(trade, dict):
            continue
        age_h = _trade_age_hours(trade)
        if age_h < min_age:
            continue
        cur_p = float(current_prices.get(market, 0) or 0)
        if cur_p <= 0:
            continue
        pnl_pct = _trade_pnl_pct(trade, cur_p)
        if pnl_pct <= 0 or pnl_pct >= max_stale:
            continue
        # Stillness check — last 6h
        history = price_history_6h.get(market) or []
        if len(history) >= 2:
            mv = _move_pct(history)
            if mv >= still_thr:
                continue
            still_pct = mv
        else:
            still_pct = -1.0  # unknown — don't block, but log
        # Kelly edge: candidate must beat (current pnl + fees) by edge_mult
        if cand_expected > 0:
            min_edge = max(0.0, pnl_pct) * edge_mult + fees
            if cand_expected < min_edge:
                continue
        suggestions.append({
            "ts": now,
            "candidate_market": cand.get("market", "?"),
            "candidate_score": cand_score,
            "candidate_expected_pct": cand_expected,
            "close_market": market,
            "close_pnl_pct": round(pnl_pct, 3),
            "close_age_hours": round(age_h, 2),
            "close_still_move_pct_6h": round(still_pct, 3) if still_pct >= 0 else None,
            "fees_pct": fees,
            "edge_mult": edge_mult,
            "rule_version": 1,
        })

    if suggestions:
        try:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with LOG_PATH.open("a", encoding="utf-8") as f:
                for s in suggestions:
                    f.write(json.dumps(s, ensure_ascii=True) + "\n")
        except Exception:
            pass  # observation must never crash trading
    return suggestions


def analyse(window_days: int = 14) -> Dict[str, Any]:
    """Summarise the shadow log over the last N days."""
    if not LOG_PATH.exists():
        return {"total": 0, "markets": {}, "note": "no shadow data yet"}
    cutoff = _now() - window_days * 86400
    rows: List[Dict[str, Any]] = []
    try:
        with LOG_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if float(e.get("ts", 0)) >= cutoff:
                    rows.append(e)
    except Exception as e:
        return {"total": 0, "error": str(e)}

    by_market: Dict[str, int] = {}
    by_candidate: Dict[str, int] = {}
    age_buckets = {"48-72h": 0, "72-120h": 0, "120h+": 0}
    pnl_buckets = {"0-0.5%": 0, "0.5-1%": 0, "1-1.5%": 0}
    for r in rows:
        cm = r.get("close_market", "?")
        ca = r.get("candidate_market", "?")
        by_market[cm] = by_market.get(cm, 0) + 1
        by_candidate[ca] = by_candidate.get(ca, 0) + 1
        ah = float(r.get("close_age_hours", 0) or 0)
        if ah < 72:
            age_buckets["48-72h"] += 1
        elif ah < 120:
            age_buckets["72-120h"] += 1
        else:
            age_buckets["120h+"] += 1
        pp = float(r.get("close_pnl_pct", 0) or 0)
        if pp < 0.5:
            pnl_buckets["0-0.5%"] += 1
        elif pp < 1.0:
            pnl_buckets["0.5-1%"] += 1
        else:
            pnl_buckets["1-1.5%"] += 1

    return {
        "total": len(rows),
        "window_days": window_days,
        "by_close_market": dict(sorted(by_market.items(), key=lambda x: -x[1])[:10]),
        "by_candidate_market": dict(sorted(by_candidate.items(), key=lambda x: -x[1])[:10]),
        "age_buckets": age_buckets,
        "pnl_buckets": pnl_buckets,
    }
