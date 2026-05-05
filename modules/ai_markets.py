"""Helpers for AI market guardrails and auto-apply logic.

Provides checks to decide whether a market may be added automatically by the AI
under the configured guardrails, and helpers to persist such additions into
`config/bot_config.json` safely.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from modules.bitvavo_client import get_bitvavo
from modules.logging_utils import log

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "bot_config.json"
_ANALYTICS_CACHE: Dict[str, Any] = {"ts": 0.0, "window": 0, "stats": {}}


def _safe_load_config() -> Dict:
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _safe_write_config(cfg: Dict) -> bool:
    try:
        # write atomically
        tmp = CONFIG_PATH.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
        tmp.replace(CONFIG_PATH)
        return True
    except Exception as exc:
        log(f"ai_markets: failed to write config: {exc}", level="error")
        return False


def get_24h_volume_eur(market: str) -> Optional[float]:
    try:
        bv = get_bitvavo()
        if not bv:
            return None
        t = bv.ticker24h({"market": market})
        if isinstance(t, list):
            t = t[0] if t else None
        if not isinstance(t, dict):
            return None
        volq = t.get("volumeQuote")
        if volq is not None:
            return float(volq)
        vol = t.get("volume")
        last = t.get("last") or t.get("price") or t.get("open")
        if vol is None or last is None:
            return None
        return float(vol) * float(last)
    except Exception as exc:
        log(f"ai_markets: get_24h_volume_eur failed for {market}: {exc}", level="warning")
        return None


def get_bid_ask(market: str) -> Optional[Dict[str, float]]:
    try:
        bv = get_bitvavo()
        if not bv:
            return None
        b = bv.book(market, {"depth": 1})
        if not b:
            return None
        # Check for API error response
        if isinstance(b, dict) and "errorCode" in b:
            log(f"ai_markets: get_bid_ask API error for {market}: {b.get('error', 'unknown')}", level="warning")
            return None
        ask = float(b["asks"][0][0])
        bid = float(b["bids"][0][0])
        return {"ask": ask, "bid": bid}
    except Exception as exc:
        log(f"ai_markets: get_bid_ask failed for {market}: {exc}", level="warning")
        return None


def spread_pct(market: str) -> Optional[float]:
    ba = get_bid_ask(market)
    if not ba:
        return None
    ask, bid = ba["ask"], ba["bid"]
    try:
        return (ask - bid) / ((ask + bid) / 2.0)
    except Exception:
        return None


def current_portfolio_exposure_eur() -> float:
    """Estimate current invested EUR from `data/trade_log.json` open entries."""
    try:
        tfile = PROJECT_ROOT / "data" / "trade_log.json"
        with tfile.open("r", encoding="utf-8") as fh:
            doc = json.load(fh)
        open_list = doc.get("open") or []
        total = 0.0
        for it in open_list:
            if isinstance(it, dict):
                invested = float(it.get("invested_eur") or it.get("invested") or 0.0)
                total += invested
        return float(total)
    except Exception:
        return 0.0


def _get_market_stats(window_days: int) -> Dict[str, Any]:
    now = time.time()
    cached_window = int(_ANALYTICS_CACHE.get("window", 0))
    cached_ts = float(_ANALYTICS_CACHE.get("ts", 0.0))
    if cached_window == window_days and (now - cached_ts) < 900:
        stats = _ANALYTICS_CACHE.get("stats")
        if isinstance(stats, dict):
            return stats
    try:
        from modules.performance_analytics import PerformanceAnalytics

        analytics = PerformanceAnalytics()
        stats = analytics.market_statistics(days=window_days)
        _ANALYTICS_CACHE["stats"] = stats
        _ANALYTICS_CACHE["ts"] = now
        _ANALYTICS_CACHE["window"] = window_days
        return stats
    except Exception:
        return {}


def evaluate_market_guardrails(
    market: str,
    cfg: Optional[Dict[str, Any]] = None,
    *,
    analytics_stats: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    cfg = cfg or _safe_load_config()
    guard = cfg.get("AI_GUARDRAILS", {}) or {}
    min_vol = float(guard.get("min_volume_24h_eur", cfg.get("MIN_VOLUME_24H_EUR", 10000)))
    max_spread = float(guard.get("max_spread_pct", cfg.get("MAX_SPREAD_PCT", 0.01)))
    max_risk = float(guard.get("max_risk_score", 70.0))
    window_days = int(guard.get("risk_window_days", 14))

    stats = analytics_stats if isinstance(analytics_stats, dict) else _get_market_stats(window_days)

    vol = get_24h_volume_eur(market) or 0.0
    sp = spread_pct(market)

    risk_score = 50.0
    if vol > 0:
        if vol < min_vol:
            deficit = (min_vol - vol) / max(min_vol, 1.0)
            risk_score += min(30.0, deficit * 40.0)
        else:
            risk_score -= min(10.0, (vol / min_vol) if min_vol else 5.0)
    else:
        risk_score += 15.0

    if sp is not None:
        if sp > max_spread:
            excess = (sp / max_spread) - 1.0 if max_spread else sp
            risk_score += min(25.0, excess * 30.0)
        else:
            risk_score -= 5.0
    else:
        risk_score += 10.0

    perf = stats.get(market) if stats else None
    if perf:
        trades = float(perf.get("trades", 0) or 0)
        win_rate = float(perf.get("win_rate", 0.0) or 0.0)
        avg_pnl = float(perf.get("avg_pnl", 0.0) or 0.0)
        if trades < 3:
            risk_score += 5.0
        elif win_rate < 40.0:
            risk_score += 15.0
        elif win_rate > 55.0:
            risk_score -= 10.0
        if avg_pnl < 0:
            risk_score += min(15.0, abs(avg_pnl) * 5.0)
        elif avg_pnl > 0.5:
            risk_score -= 5.0

    risk_score = max(0.0, min(100.0, risk_score))

    ok = True
    reasons = []
    if vol < min_vol:
        ok = False
        reasons.append(f"volume {vol:.0f} < {min_vol:.0f}")
    if sp is None:
        ok = False
        reasons.append("spread unavailable")
    elif sp > max_spread:
        ok = False
        reasons.append(f"spread {sp:.4f} > {max_spread:.4f}")
    if risk_score > max_risk:
        ok = False
        reasons.append(f"risk {risk_score:.1f} > {max_risk:.1f}")

    return {
        "ok": ok,
        "volume_eur": vol,
        "min_volume": min_vol,
        "spread_pct": sp,
        "max_spread": max_spread,
        "risk_score": risk_score,
        "max_risk_score": max_risk,
        "reasons": reasons,
    }


def market_allowed_to_auto_apply(
    market: str,
    cfg: Optional[Dict] = None,
    *,
    analytics_stats: Optional[Dict[str, Any]] = None,
) -> bool:
    """Return True if market passes guardrails in config and may be auto-applied.

    Guardrails checked:
    - AI_EMERGENCY_STOP (global stop)
    - min 24h volume in EUR
    - max spread pct
    - max position pct of portfolio exposure
    """
    cfg = cfg or _safe_load_config()
    scope = cfg.get("AI_MARKET_SCOPE", "suggest-only")
    if cfg.get("AI_EMERGENCY_STOP"):
        log("ai_markets: AI_EMERGENCY_STOP enabled, refusing to auto-apply", level="warning")
        return False
    if scope not in ("guarded-auto", "full-access"):
        return False

    guard = cfg.get("AI_GUARDRAILS", {}) or {}
    max_pos_pct = float(guard.get("max_position_pct_portfolio", 0.05))

    eval_result = evaluate_market_guardrails(market, cfg, analytics_stats=analytics_stats)
    if not eval_result.get("ok", False):
        reason = ", ".join(eval_result.get("reasons", [])) or "guardrail violation"
        log(f"ai_markets: market {market} blocked ({reason})", level="info")
        return False

    # position sizing: estimate new exposure as base amount (or DCA amount) and compare
    base_amount = float(cfg.get("BASE_AMOUNT_EUR", cfg.get("DCA_AMOUNT_EUR", 10.0)))
    current = current_portfolio_exposure_eur()
    portfolio_total = max(current + base_amount, cfg.get("MAX_TOTAL_EXPOSURE_EUR", 100.0))
    projected_pct = (current + base_amount) / portfolio_total if portfolio_total else 1.0
    if projected_pct > max_pos_pct:
        log(
            f"ai_markets: market {market} would exceed position pct ({projected_pct:.3f} > {max_pos_pct})", level="info"
        )
        return False

    return True


def add_market_to_whitelist(market: str) -> bool:
    cfg = _safe_load_config()
    wl = cfg.get("WHITELIST_MARKETS") or []
    if market in wl:
        return True
    wl.append(market)
    cfg["WHITELIST_MARKETS"] = wl
    ok = _safe_write_config(cfg)
    if ok:
        log(f"ai_markets: added {market} to WHITELIST_MARKETS", level="info")
        # small delay to ensure file system timestamps settle
        time.sleep(0.2)
    return ok
