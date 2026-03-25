"""bot.trailing – Trailing stop, stop-loss, partial TP, and exit strategies.

All functions that manage trailing stops, hard stop-losses, partial take-profit,
advanced exit strategies, and profit calculation live here.

Usage:
    import bot.trailing as _trail
    _trail.init(config, open_trades_ref)
    # Later, after risk is ready:
    # _trail._risk_mgr = risk_manager  (if needed)
"""

from __future__ import annotations

import copy
import json
import math
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

import bot.api as _api
from core.indicators import close_prices, highs, lows, atr, ema
from modules.logging_utils import log, locked_write_json

# ---------------------------------------------------------------------------
# Module state – set by init()
# ---------------------------------------------------------------------------
_cfg: dict = {}
_open_trades: dict = {}  # reference to the global open_trades dict

# ---------------------------------------------------------------------------
# HTF candle cache — avoids 3 redundant API calls per trade per loop tick
# ---------------------------------------------------------------------------
_HTF_CACHE: Dict[str, dict] = {}
_HTF_CACHE_LOCK = threading.Lock()
_HTF_CACHE_TTL: Dict[str, float] = {"5m": 120.0, "15m": 300.0, "1h": 600.0}


def _get_htf_candles(market: str, interval: str, limit: int = 20) -> Optional[List]:
    """Return HTF candles from cache or fetch fresh; TTL varies by interval."""
    cache_key = f"{market}:{interval}:{limit}"
    ttl = _HTF_CACHE_TTL.get(interval, 120.0)
    now = time.time()
    with _HTF_CACHE_LOCK:
        entry = _HTF_CACHE.get(cache_key)
        if entry and (now - entry["ts"]) < ttl:
            return entry["data"]
    data = _api.get_candles(market, interval, limit)
    if data is not None:
        with _HTF_CACHE_LOCK:
            _HTF_CACHE[cache_key] = {"data": data, "ts": now}
    return data

# ---------------------------------------------------------------------------
# Partial TP state (module-owned)
# ---------------------------------------------------------------------------
PARTIAL_TP_HISTORY_FILE: Path = Path("data/partial_tp_events.jsonl")
PARTIAL_TP_STATS_FILE: Path = Path("data/partial_tp_stats.json")
_PARTIAL_TP_STATS_LOCK = threading.Lock()
_PARTIAL_TP_STATS: Dict[str, Any] = {
    "total_events": 0,
    "per_level": {},
    "last_event": None,
}


def _load_partial_tp_stats_cache() -> None:
    """Load persisted partial-TP stats from disk into module state."""
    try:
        if not PARTIAL_TP_STATS_FILE.exists():
            return
        with PARTIAL_TP_STATS_FILE.open("r", encoding="utf-8") as fh:
            data = json.load(fh) or {}
        if isinstance(data, dict):
            with _PARTIAL_TP_STATS_LOCK:
                _PARTIAL_TP_STATS.update(data)
    except Exception as e:
        log(f"exists failed: {e}", level="warning")


# ---------------------------------------------------------------------------
# init()
# ---------------------------------------------------------------------------

def init(config: dict, *, open_trades_ref: dict | None = None) -> None:
    """Inject runtime dependencies.

    Parameters
    ----------
    config : dict
        Reference to the global CONFIG dict.
    open_trades_ref : dict, optional
        Reference to the global open_trades dict.
    """
    global _cfg, _open_trades
    global PARTIAL_TP_HISTORY_FILE, PARTIAL_TP_STATS_FILE
    _cfg = config
    if open_trades_ref is not None:
        _open_trades = open_trades_ref

    PARTIAL_TP_HISTORY_FILE = Path(config.get("PARTIAL_TP_HISTORY_FILE", "data/partial_tp_events.jsonl"))
    PARTIAL_TP_STATS_FILE = Path(config.get("PARTIAL_TP_STATS_FILE", "data/partial_tp_stats.json"))

    _load_partial_tp_stats_cache()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_parent_dir(path: str) -> None:
    try:
        parent = Path(path).parent
        if parent:
            parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log(f"[ERROR] Failed to create parent directory for {path}: {e}", level="error")


def _partial_tp_levels() -> List[Tuple[float, float]]:
    """Build PARTIAL_TP_LEVELS from config (cached-ish via config reference)."""
    tp_targets = _cfg.get("TAKE_PROFIT_TARGETS") or []
    tp_pcts = _cfg.get("TAKE_PROFIT_PERCENTAGES") or []
    levels: List[Tuple[float, float]] = []
    for target, pct in zip(tp_targets, tp_pcts):
        try:
            t = float(target)
            s = float(pct)
        except Exception:
            continue
        if t <= 0 or s <= 0:
            continue
        levels.append((t, min(1.0, s)))
    if not levels:
        atr_mult = _cfg.get("ATR_MULTIPLIER", 2.0)
        levels = [
            (max(0.015, 1.0 * (atr_mult / 10)), 0.30),
            (max(0.025, 1.8 * (atr_mult / 10)), 0.30),
            (max(0.035, 2.5 * (atr_mult / 10)), 0.40),
        ]
    return levels


# ---------------------------------------------------------------------------
# Partial TP functions
# ---------------------------------------------------------------------------

def _ensure_tp_flags(trade: Dict[str, Any]) -> List[bool]:
    """Ensure partial-TP flags are initialised on *trade*.

    NOTE: Caller MUST hold ``state.trades_lock`` — this function mutates *trade*.
    """
    levels = _partial_tp_levels()
    required = len(levels)
    if required <= 0:
        trade["tp_levels_done"] = []
        trade.setdefault("partial_tp_events", [])
        return []
    flags = trade.get("tp_levels_done")
    if not isinstance(flags, list):
        flags = [False] * required
    elif len(flags) < required:
        flags.extend([False] * (required - len(flags)))
    trade["tp_levels_done"] = flags
    trade.setdefault("partial_tp_events", [])
    return flags


def _record_partial_tp_event(
    market: str,
    trade: Dict[str, Any],
    level_idx: int,
    target_pct: float,
    sell_pct: float,
    configured_pct: Optional[float],
    sell_amount: float,
    sell_price: float,
    profit_eur: float,
    remaining_amount: float,
) -> None:
    ts = time.time()
    event = {
        "ts": ts,
        "market": market,
        "level_index": level_idx,
        "reason": f"partial_tp_{level_idx + 1}",
        "target_pct": float(target_pct),
        "sell_pct": float(sell_pct),
        "configured_sell_pct": float(configured_pct) if configured_pct is not None else None,
        "sell_amount": float(sell_amount),
        "sell_price": float(sell_price),
        "profit_eur": float(profit_eur),
        "remaining_amount": max(0.0, float(remaining_amount)),
    }
    try:
        trade.setdefault("partial_tp_events", []).append(event)
        trade["tp_last_time"] = ts
    except Exception as e:
        log(f"[ERROR] Failed to record partial TP event in trade dict for {market}: {e}", level="error")
    try:
        _ensure_parent_dir(str(PARTIAL_TP_HISTORY_FILE))
        with PARTIAL_TP_HISTORY_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:
        log(f"[ERROR] Failed to write partial TP event to file for {market}: {e}", level="error")
    summary: Dict[str, Any]
    with _PARTIAL_TP_STATS_LOCK:
        stats = _PARTIAL_TP_STATS
        stats["total_events"] = int(stats.get("total_events", 0) or 0) + 1
        key = f"L{level_idx + 1}"
        per_level = stats.setdefault("per_level", {})
        entry = per_level.setdefault(
            key,
            {
                "count": 0,
                "realized_profit_eur": 0.0,
                "target_pct": float(target_pct),
                "sell_pct": float(sell_pct),
                "configured_sell_pct": float(configured_pct) if configured_pct is not None else None,
            },
        )
        entry["count"] = int(entry.get("count", 0) or 0) + 1
        entry["realized_profit_eur"] = float(entry.get("realized_profit_eur", 0.0) or 0.0) + float(profit_eur)
        entry["target_pct"] = float(target_pct)
        entry["sell_pct"] = float(sell_pct)
        if configured_pct is not None:
            entry["configured_sell_pct"] = float(configured_pct)
        entry["last_hit_ts"] = ts
        stats["last_event"] = {
            "ts": ts,
            "market": market,
            "level": key,
            "profit_eur": float(profit_eur),
            "price": float(sell_price),
        }
        summary = {
            "ts": ts,
            "total_events": stats["total_events"],
            "per_level": per_level,
            "last_event": stats["last_event"],
        }
    try:
        locked_write_json(str(PARTIAL_TP_STATS_FILE), summary)
    except Exception as e:
        log(f"[ERROR] Failed to write partial TP stats to file: {e}", level="error")


def get_partial_tp_stats() -> Dict[str, Any]:
    with _PARTIAL_TP_STATS_LOCK:
        return copy.deepcopy(_PARTIAL_TP_STATS)


# ---------------------------------------------------------------------------
# Adaptive TP
# ---------------------------------------------------------------------------

def calculate_adaptive_tp(market, entry_price, volatility=None, trend_strength=None):
    """Calculate adaptive take profit levels based on market conditions."""
    try:
        if volatility is None:
            candles = _api.get_candles(market, "1m", 60)
            if candles:
                prices = close_prices(candles)
                if len(prices) >= 20:
                    returns = np.diff(prices[-50:]) / prices[-50:-1]
                    volatility = float(np.std(returns))
                else:
                    volatility = 0.03
            else:
                volatility = 0.03

        if volatility < 0.02:
            base_tp_pct = 0.015
        elif volatility < 0.05:
            base_tp_pct = 0.03
        else:
            base_tp_pct = 0.06

        if trend_strength and trend_strength > 0.7:
            base_tp_pct *= 1.5

        tp_levels = [
            {"pct": base_tp_pct * 0.5, "amount": 0.33, "filled": False},
            {"pct": base_tp_pct, "amount": 0.33, "filled": False},
            {"pct": base_tp_pct * 2, "amount": 0.34, "filled": False},
        ]
        return tp_levels
    except Exception as e:
        log(f"[ADAPTIVE_TP] Error calculating for {market}: {e}", level="debug")
        return [{"pct": 0.03, "amount": 1.0, "filled": False}]


# ---------------------------------------------------------------------------
# Stop-loss
# ---------------------------------------------------------------------------

def check_stop_loss(market, trade, current_price, enabled=False):
    """Hard stop-loss override — DISABLED.

    FIX #003: All stop-loss and time-stop-loss logic disabled.
    A trade may NEVER be closed at a loss.
    """
    return False, "Stop loss permanently disabled (FIX #003)"


# ---------------------------------------------------------------------------
# Advanced exit strategies
# ---------------------------------------------------------------------------

def check_advanced_exit_strategies(trade, current_price):
    """Advanced exit: partial TP, time-based exits, volatility spike exits.

    Returns (should_exit, exit_portion, reason).
    """
    if not isinstance(trade, dict):
        return (False, 0.0, None)

    buy_price = trade.get("buy_price", 0.0)
    if buy_price <= 0 or current_price <= 0:
        return (False, 0.0, None)

    try:
        cost_buf = float(trade.get("cost_buffer_pct", 0.0) or 0.0)
    except Exception:
        cost_buf = 0.0
    sell_buffer = 0.0
    try:
        market = trade.get("market") if isinstance(trade, dict) else None
        amt = float(trade.get("amount", 0.0) or 0.0) if isinstance(trade, dict) else 0.0
        if market and amt > 0:
            sell_slip = _api.get_expected_slippage_sell(market, amt, current_price)
            if sell_slip is not None and sell_slip > 0:
                sell_buffer = sell_slip
    except Exception:
        sell_buffer = 0.0

    effective_exit_price = current_price * (1 - sell_buffer)
    profit_pct = (effective_exit_price - buy_price * (1 + cost_buf)) / buy_price

    take_profit_enabled = bool(_cfg.get("TAKE_PROFIT_ENABLED", True))
    # ── Adaptive Exit: use per-trade TP levels if available ──
    adaptive_levels = trade.get("adaptive_tp_levels") if isinstance(trade, dict) else None
    if adaptive_levels and isinstance(adaptive_levels, list) and len(adaptive_levels) > 0:
        # Normalize: adaptive levels may be dicts {"pct":..,"amount"|"sell_fraction":..} or tuples (pct, sell_pct)
        _norm: List[Tuple[float, float]] = []
        for _lv in adaptive_levels:
            if isinstance(_lv, dict):
                _sell = float(_lv.get("amount", _lv.get("sell_fraction", 1.0)))
                _norm.append((float(_lv.get("pct", 0)), _sell))
            elif isinstance(_lv, (list, tuple)) and len(_lv) >= 2:
                _norm.append((float(_lv[0]), float(_lv[1])))
        levels = _norm if _norm else _partial_tp_levels()
    else:
        levels = _partial_tp_levels()
    if take_profit_enabled and levels:
        tp_flags = _ensure_tp_flags(trade)
        for idx, (target_pct, sell_pct) in enumerate(levels):
            if idx < len(tp_flags) and tp_flags[idx]:
                continue
            if profit_pct >= target_pct:
                return (True, min(1.0, sell_pct), f"partial_tp_{idx + 1}")

    # FIX #003: Time-based exits disabled — no 48h exit, no 24h tighten.
    # A trade may NEVER be closed based on time alone.

    highest_price = trade.get("highest_price", buy_price)
    drop_from_peak = (highest_price - current_price) / highest_price if highest_price > 0 else 0
    if drop_from_peak > 0.05 and profit_pct > 0.05:
        return (True, 1.0, "volatility_spike_exit")

    return (False, 0.0, None)


# ---------------------------------------------------------------------------
# calculate_stop_levels (the big one)
# ---------------------------------------------------------------------------

def calculate_stop_levels(m, buy, high):  # noqa: C901
    """Calculate trailing stop, hard stop, and trend strength for a market.

    NOTE: Caller MUST hold ``state.trades_lock`` before calling this function,
    because it reads and mutates ``_open_trades[m]`` (e.g. trailing_activated,
    original_hard_stop, highest_since_activation).
    """
    try:
        try:
            trade = _open_trades.get(m)
        except Exception:
            trade = None

        SMA_SHORT = _cfg.get("SMA_SHORT", 20)
        SMA_LONG = _cfg.get("SMA_LONG", 50)
        ATR_WINDOW_1M = _cfg.get("ATR_WINDOW_1M", 14)
        ATR_MULTIPLIER = _cfg.get("ATR_MULTIPLIER", 2.0)
        HARD_SL_BTCETH_PCT = _cfg.get("HARD_SL_BTCETH_PCT", 0.10)
        HARD_SL_ALT_PCT = _cfg.get("HARD_SL_ALT_PCT", 0.10)
        DEFAULT_TRAILING = _cfg.get("DEFAULT_TRAILING", 0.10)
        TRAILING_ACTIVATION_PCT = _cfg.get("TRAILING_ACTIVATION_PCT", 0.02)

        try:
            c1 = _api.get_candles(m, "1m", 120)
            p1 = close_prices(c1) if c1 else []
            atr_val = atr(highs(c1), lows(c1), p1, ATR_WINDOW_1M) if c1 and p1 else None

            trend_strength = 0.0
            if p1 and len(p1) > SMA_LONG:
                ema_short = ema(p1, SMA_SHORT)
                ema_long = ema(p1, SMA_LONG)
                trend_strength = (ema_short - ema_long) / ema_long if ema_long else 0.0

            hard_pct = HARD_SL_BTCETH_PCT if m.startswith(("BTC", "ETH")) else HARD_SL_ALT_PCT

            # ── Regime Engine: apply sl_mult to hard stop ──
            try:
                _regime_adj = _cfg.get("_REGIME_ADJ") or {}
                _sl_mult = float(_regime_adj.get("sl_mult", 1.0)) if isinstance(_regime_adj, dict) else 1.0
                if _sl_mult != 1.0 and _sl_mult > 0:
                    hard_pct = hard_pct * _sl_mult
            except Exception:
                pass

            hard = buy * (1 - hard_pct) if buy is not None else 0.0

            # Preserve original hard stop from first buy (DCA protection)
            if isinstance(trade, dict):
                if "original_hard_stop" not in trade or trade.get("original_hard_stop") is None:
                    trade["original_hard_stop"] = hard
                    trade["original_buy_price"] = buy
                else:
                    hard = min(float(trade["original_hard_stop"]), hard)

            activation_pct = TRAILING_ACTIVATION_PCT
            try:
                if isinstance(trade, dict) and trade.get("trailing_activation_pct") is not None:
                    activation_pct = float(trade.get("trailing_activation_pct"))
            except Exception:
                activation_pct = TRAILING_ACTIVATION_PCT
            activation_ok = high is not None and buy is not None and high >= buy * (1 + activation_pct)

            hw = high
            try:
                if isinstance(trade, dict) and trade.get("trailing_activated"):
                    stored_hw = trade.get("highest_since_activation")
                    if stored_hw is None:
                        stored_hw = high
                    hw = max(float(stored_hw or 0.0), float(high or 0.0))
                else:
                    hw = high
            except Exception:
                hw = high

            try:
                if isinstance(trade, dict) and activation_ok and not trade.get("trailing_activated"):
                    trade["trailing_activated"] = True
                    trade["activation_price"] = float(buy)
                    trade["highest_since_activation"] = float(high or buy)
                if isinstance(trade, dict) and trade.get("trailing_activated"):
                    trade["highest_since_activation"] = max(
                        float(trade.get("highest_since_activation") or 0.0), float(high or 0.0)
                    )
            except Exception as e:
                log(f"[ERROR] Trailing activation flag update failed for {m if 'm' in dir() else '?'}: {e}", level="error")

            if activation_ok or (isinstance(trade, dict) and trade.get("trailing_activated")):
                used_high = hw
                base_percent = DEFAULT_TRAILING
                try:
                    if isinstance(trade, dict) and trade.get("base_trailing_pct") is not None:
                        base_percent = float(trade.get("base_trailing_pct"))
                except Exception:
                    base_percent = DEFAULT_TRAILING

                # ── Regime Engine: apply trailing_pct_override ──
                try:
                    _regime_adj = _cfg.get("_REGIME_ADJ") or {}
                    _trailing_override = _regime_adj.get("trailing_pct_override") if isinstance(_regime_adj, dict) else None
                    if _trailing_override is not None and float(_trailing_override) > 0:
                        base_percent = float(_trailing_override)
                except Exception:
                    pass

                # Stepped trailing
                try:
                    stepped_levels = _cfg.get("STEPPED_TRAILING_LEVELS", [
                        {"profit_pct": 0.02, "trailing_pct": 0.012},
                        {"profit_pct": 0.04, "trailing_pct": 0.010},
                        {"profit_pct": 0.06, "trailing_pct": 0.008},
                        {"profit_pct": 0.08, "trailing_pct": 0.007},
                        {"profit_pct": 0.12, "trailing_pct": 0.006},
                        {"profit_pct": 0.18, "trailing_pct": 0.005},
                        {"profit_pct": 0.25, "trailing_pct": 0.004},
                        {"profit_pct": 0.35, "trailing_pct": 0.003},
                    ])
                    if buy is not None and buy > 0 and used_high > buy:
                        profit_pct = (used_high - buy) / buy
                        for level in reversed(stepped_levels):
                            if profit_pct >= level["profit_pct"]:
                                base_percent = min(base_percent, level["trailing_pct"])
                                break
                except Exception as e:
                    log(f"get failed: {e}", level="error")

                # Per-market ATR multipliers
                atr_mult = ATR_MULTIPLIER
                try:
                    atr_by_market = _cfg.get("ATR_MULTIPLIER_BY_MARKET", {})
                    if m in atr_by_market:
                        atr_mult = atr_by_market[m]
                    elif "_default" in atr_by_market:
                        atr_mult = atr_by_market["_default"]
                except Exception as e:
                    log(f"get failed: {e}", level="warning")

                # 5-level trend adjustment
                trend_mult = 1.0
                try:
                    trend_levels = _cfg.get("TREND_LEVELS", [
                        {"threshold": 0.06, "multiplier": 0.6, "name": "strong_bull"},
                        {"threshold": 0.03, "multiplier": 0.75, "name": "bull"},
                        {"threshold": -0.03, "multiplier": 1.0, "name": "neutral"},
                        {"threshold": -0.06, "multiplier": 1.25, "name": "bear"},
                        {"threshold": -999, "multiplier": 1.4, "name": "strong_bear"},
                    ])
                    for level in trend_levels:
                        if trend_strength >= level["threshold"]:
                            trend_mult = level["multiplier"]
                            break
                except Exception:
                    if trend_strength > 0.03:
                        trend_mult = 0.7
                    elif trend_strength < -0.03:
                        trend_mult = 1.3

                if atr_val is not None:
                    base_trailing = max(atr_mult * atr_val, used_high * base_percent * 0.5)
                    base_trailing *= trend_mult
                    trailing = used_high - base_trailing
                else:
                    base_percent *= trend_mult
                    trailing = used_high * (1 - base_percent)

                # Cost buffer floor
                try:
                    cost_buf = float(trade.get("cost_buffer_pct", 0.0)) if isinstance(trade, dict) else 0.0
                except Exception:
                    cost_buf = 0.0

                sell_buffer = 0.0
                try:
                    if isinstance(trade, dict):
                        amt = float(trade.get("amount", 0.0) or 0.0)
                        if amt > 0 and used_high:
                            sell_slip = _api.get_expected_slippage_sell(m, amt, used_high)
                            if sell_slip is not None and sell_slip > 0:
                                sell_buffer = sell_slip * 0.5
                except Exception:
                    sell_buffer = 0.0

                min_safe = buy * (1 + cost_buf + 0.001) if buy is not None else trailing
                if sell_buffer and buy is not None:
                    min_safe = max(min_safe, buy * (1 + cost_buf + sell_buffer))

                # Profit velocity awareness
                try:
                    if _cfg.get("PROFIT_VELOCITY_ENABLED", True) and isinstance(trade, dict) and buy is not None and buy > 0:
                        buy_time = trade.get("buy_time") or trade.get("timestamp")
                        if buy_time:
                            buy_dt = datetime.fromisoformat(buy_time) if isinstance(buy_time, str) else datetime.fromtimestamp(buy_time)
                            hours_held = (datetime.utcnow() - buy_dt).total_seconds() / 3600
                            if hours_held > 0.1:
                                profit_pct = (used_high - buy) / buy
                                velocity = profit_pct / hours_held
                                fast_threshold = _cfg.get("PROFIT_VELOCITY_FAST_THRESHOLD", 0.02)
                                slow_threshold = _cfg.get("PROFIT_VELOCITY_SLOW_THRESHOLD", 0.003)
                                if velocity > fast_threshold:
                                    velocity_mult = _cfg.get("PROFIT_VELOCITY_FAST_MULT", 1.3)
                                    trailing_dist = used_high - trailing
                                    trailing = used_high - (trailing_dist * velocity_mult)
                                elif velocity < slow_threshold:
                                    velocity_mult = _cfg.get("PROFIT_VELOCITY_SLOW_MULT", 0.8)
                                    trailing_dist = used_high - trailing
                                    trailing = used_high - (trailing_dist * velocity_mult)
                except Exception as e:
                    log(f"[ERROR] Profit velocity adjustment failed: {e}", level="error")

                # Time decay tightening
                try:
                    if _cfg.get("TIME_DECAY_ENABLED", True) and isinstance(trade, dict):
                        buy_time = trade.get("buy_time") or trade.get("timestamp")
                        if buy_time:
                            buy_dt = datetime.fromisoformat(buy_time) if isinstance(buy_time, str) else datetime.fromtimestamp(buy_time)
                            hours_held = (datetime.utcnow() - buy_dt).total_seconds() / 3600
                            time_decay_levels = _cfg.get("TIME_DECAY_LEVELS", [
                                {"hours": 24, "reduction_pct": 0.10},
                                {"hours": 48, "reduction_pct": 0.15},
                                {"hours": 72, "reduction_pct": 0.20},
                            ])
                            reduction = 0.0
                            for level in reversed(time_decay_levels):
                                if hours_held >= level["hours"]:
                                    reduction = level["reduction_pct"]
                                    break
                            if reduction > 0:
                                trailing_dist = used_high - trailing
                                trailing = used_high - (trailing_dist * (1 - reduction))
                except Exception as e:
                    log(f"get failed: {e}", level="error")

                # Legacy time tighten — DISABLED (FIX #003)
                # trade["time_tighten"] is no longer set; skip tightening.

                # Volume weighting
                try:
                    if _cfg.get("VOLUME_WEIGHTING_ENABLED", True):
                        candles = _api.get_candles(m, "1m", 60)
                        if candles and len(candles) >= 30:
                            volumes = [float(c[5]) for c in candles if len(c) > 5]
                            if volumes:
                                current_vol = volumes[-1]
                                avg_vol = sum(volumes) / len(volumes)
                                if avg_vol > 0:
                                    vol_ratio = current_vol / avg_vol
                                    high_mult = _cfg.get("VOLUME_HIGH_MULT", 2.0)
                                    low_mult = _cfg.get("VOLUME_LOW_MULT", 0.5)
                                    if vol_ratio > high_mult:
                                        vol_tighten = _cfg.get("VOLUME_HIGH_TIGHTEN", 0.85)
                                        trailing_dist = used_high - trailing
                                        trailing = used_high - (trailing_dist * vol_tighten)
                                    elif vol_ratio < low_mult:
                                        vol_loosen = _cfg.get("VOLUME_LOW_LOOSEN", 1.2)
                                        trailing_dist = used_high - trailing
                                        trailing = used_high - (trailing_dist * vol_loosen)
                except Exception as e:
                    log(f"get failed: {e}", level="error")

                # Multi-timeframe consensus
                try:
                    if _cfg.get("MULTI_TIMEFRAME_ENABLED", True):
                        bullish_count = 0
                        bearish_count = 0

                        c5m = _get_htf_candles(m, "5m", 20)
                        if c5m and len(c5m) >= 10:
                            closes_5m = [float(c[4]) for c in c5m]
                            sma_5m = sum(closes_5m[-10:]) / 10
                            if closes_5m[-1] > sma_5m:
                                bullish_count += 1
                            else:
                                bearish_count += 1

                        c15m = _get_htf_candles(m, "15m", 20)
                        if c15m and len(c15m) >= 10:
                            closes_15m = [float(c[4]) for c in c15m]
                            sma_15m = sum(closes_15m[-10:]) / 10
                            if closes_15m[-1] > sma_15m:
                                bullish_count += 1
                            else:
                                bearish_count += 1

                        c1h = _get_htf_candles(m, "1h", 20)
                        if c1h and len(c1h) >= 10:
                            closes_1h = [float(c[4]) for c in c1h]
                            sma_1h = sum(closes_1h[-10:]) / 10
                            if closes_1h[-1] > sma_1h:
                                bullish_count += 1
                            else:
                                bearish_count += 1

                        if bullish_count == 3:
                            trailing_dist = used_high - trailing
                            trailing = used_high - (trailing_dist * 0.7)
                        elif bearish_count == 3:
                            trailing_dist = used_high - trailing
                            trailing = used_high - (trailing_dist * 1.3)
                except Exception as e:
                    log(f"[ERROR] Multi-timeframe consensus failed: {e}", level="error")

                if sell_buffer and buy is not None:
                    trailing = max(trailing, buy * (1 + cost_buf + sell_buffer))
                trailing = max(trailing, hard, buy, min_safe)
            else:
                trailing = max(hard, buy)

            stop = hard
            result = (stop, trailing, hard, trend_strength)
            if not isinstance(result, tuple) or len(result) != 4:
                log(f"[ERROR] calculate_stop_levels fallback: {result}", level="error")
                return 0, 0, 0, 0
            return result
        except Exception as e:
            log(f"[ERROR] calculate_stop_levels exception: {e}", level="error")
            return 0, 0, 0, 0
    except Exception as e:
        log(f"[ERROR] calculate_stop_levels exception: {e}", level="error")
        return 0, 0, 0, 0


# ---------------------------------------------------------------------------
# Realized profit
# ---------------------------------------------------------------------------

def realized_profit(buy_price, sell_price, amount, buy_fee_pct=None, sell_fee_pct=None):
    """Calculate realized profit including trading fees."""
    fee_taker = float(_cfg.get("FEE_TAKER", 0.0025))
    if buy_fee_pct is None:
        buy_fee_pct = fee_taker
    if sell_fee_pct is None:
        sell_fee_pct = fee_taker

    gross_buy = buy_price * amount
    gross_sell = sell_price * amount
    buy_fee = gross_buy * buy_fee_pct
    sell_fee = gross_sell * sell_fee_pct
    net_profit = gross_sell - gross_buy - buy_fee - sell_fee
    return net_profit
