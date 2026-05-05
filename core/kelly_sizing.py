"""core.kelly_sizing – Kelly Criterion + Volatility Parity Position Sizing.

Combines two proven portfolio-theory concepts:

1. Kelly Criterion: Mathematically optimal position size per coin
   f* = (p·b - q) / b  where p=win_rate, b=avg_win/avg_loss, q=1-p
   Uses half-Kelly for safety, per-coin statistics for precision.

2. Volatility Parity: Allocate capital inversely proportional to volatility
   so each position contributes EQUAL risk to the portfolio.
   (Same principle as Ray Dalio's All Weather Portfolio)

Result: FET-EUR (high vol) gets smaller positions, LTC-EUR (lower vol) gets larger.
But both carry the same dollar-risk per trade.

Academic basis:
  - Kelly (1956) "A New Interpretation of Information Rate"
  - Qian (2005) "Risk Parity Portfolios" (PanAgora Asset Management)
"""

from __future__ import annotations

import json
import math
import time
from typing import Any, Dict, List, Optional

from modules.logging_utils import log

# ── Defaults ──
DEFAULT_KELLY_FRACTION = 0.5  # Half-Kelly (standard risk-adjusted approach)
MIN_POSITION_EUR = 10.0  # Never go below €10
MAX_POSITION_MULT = 2.5  # Never exceed 2.5x base amount
MIN_TRADES_KELLY = 15  # Need 15+ trades per coin for reliable Kelly
MIN_TRADES_GLOBAL = 30  # Global Kelly needs 30+ trades
VOL_PARITY_LOOKBACK = 50  # Number of 1m candles for vol calculation

# Cache
_stats_cache: Dict[str, Any] = {}
_STATS_CACHE_TTL = 600  # 10 minutes


def _load_trade_history(trade_log_path: str = "data/trade_log.json") -> List[Dict]:
    """Load closed trade history."""
    try:
        with open(trade_log_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        closed = data.get("closed", []) if isinstance(data, dict) else []
        return [t for t in closed if isinstance(t, dict)]
    except Exception:
        return []


def _per_coin_stats(closed_trades: List[Dict]) -> Dict[str, Dict[str, float]]:
    """Calculate win rate and avg win/loss ratio per coin.

    Returns: {market: {win_rate, avg_win_pct, avg_loss_pct, win_loss_ratio, n_trades}}
    """
    by_market: Dict[str, List[Dict]] = {}
    for t in closed_trades:
        m = t.get("market", "")
        if not m:
            continue
        by_market.setdefault(m, []).append(t)

    result = {}
    for market, trades in by_market.items():
        wins = []
        losses = []
        for t in trades:
            profit = float(t.get("profit", 0) or 0)
            invested = float(t.get("invested_eur", 0) or t.get("total_invested_eur", 0) or 0)
            if invested <= 0:
                continue
            pct = profit / invested
            if profit > 0:
                wins.append(pct)
            elif profit < 0:
                losses.append(abs(pct))

        n_total = len(wins) + len(losses)
        if n_total < 3:
            continue

        win_rate = len(wins) / n_total if n_total > 0 else 0.5
        avg_win = sum(wins) / len(wins) if wins else 0.02
        avg_loss = sum(losses) / len(losses) if losses else 0.02

        result[market] = {
            "win_rate": win_rate,
            "avg_win_pct": avg_win,
            "avg_loss_pct": avg_loss,
            "win_loss_ratio": avg_win / avg_loss if avg_loss > 0 else 2.0,
            "n_trades": n_total,
        }

    return result


def kelly_fraction_for_market(
    win_rate: float,
    win_loss_ratio: float,
    kelly_multiplier: float = DEFAULT_KELLY_FRACTION,
) -> float:
    """Calculate Kelly fraction for a market.

    f* = W - (1-W)/R  (full Kelly)
    Applied fraction = f* × kelly_multiplier (half-Kelly by default)

    Returns: fraction of capital to bet (0.0 to 1.0)
    """
    if win_loss_ratio <= 0:
        return 0.0

    full_kelly = win_rate - (1.0 - win_rate) / win_loss_ratio

    if full_kelly <= 0:
        return 0.0  # Negative Kelly = losing strategy

    return full_kelly * kelly_multiplier


def _volatility_from_candles(candles: List[List], window: int = 20) -> float:
    """Calculate annualized volatility from candle data."""
    closes = []
    for c in candles:
        try:
            closes.append(float(c[4]))
        except (IndexError, TypeError, ValueError):
            continue

    if len(closes) < window + 1:
        return 0.0

    recent = closes[-(window + 1) :]
    log_returns = [math.log(recent[i] / recent[i - 1]) for i in range(1, len(recent)) if recent[i - 1] > 0]

    if not log_returns:
        return 0.0

    mu = sum(log_returns) / len(log_returns)
    variance = sum((r - mu) ** 2 for r in log_returns) / max(len(log_returns) - 1, 1)
    return math.sqrt(variance)


def volatility_parity_weights(
    market_volatilities: Dict[str, float],
) -> Dict[str, float]:
    """Calculate volatility parity weights.

    Each market gets weight inversely proportional to its volatility,
    so all positions contribute equal risk.

    Returns: {market: weight} where sum(weights) = 1.0
    """
    if not market_volatilities:
        return {}

    # Filter out zero/missing volatilities
    valid = {m: v for m, v in market_volatilities.items() if v > 0}
    if not valid:
        # Equal weight fallback
        n = len(market_volatilities)
        return {m: 1.0 / n for m in market_volatilities}

    # Inverse volatility weights
    inv_vols = {m: 1.0 / v for m, v in valid.items()}
    total_inv = sum(inv_vols.values())

    weights = {m: iv / total_inv for m, iv in inv_vols.items()}

    return weights


def calculate_position_size(
    market: str,
    base_amount_eur: float,
    candles: Optional[List[List]] = None,
    trade_log_path: str = "data/trade_log.json",
    all_market_candles: Optional[Dict[str, List[List]]] = None,
    kelly_fraction_mult: float = DEFAULT_KELLY_FRACTION,
    budget_eur: float = 300.0,
) -> Dict[str, Any]:
    """Calculate optimal position size combining Kelly + Volatility Parity.

    Strategy:
    1. If enough per-coin trades → use per-coin Kelly
    2. If not → use global Kelly
    3. Apply volatility parity weight to scale position
    4. Blend Kelly and vol-parity amounts

    Returns dict with:
        amount_eur: float (final position size)
        kelly_fraction: float
        vol_parity_weight: float
        details: dict (diagnostic)
    """
    now = time.time()

    # Check cache for stats
    if not _stats_cache or (now - _stats_cache.get("ts", 0)) > _STATS_CACHE_TTL:
        closed = _load_trade_history(trade_log_path)
        _stats_cache["per_coin"] = _per_coin_stats(closed)
        _stats_cache["closed"] = closed
        _stats_cache["ts"] = now

    per_coin = _stats_cache.get("per_coin", {})
    coin_stats = per_coin.get(market)

    details = {"market": market, "base_amount_eur": base_amount_eur}

    # ── Step 1: Kelly Criterion ──
    kelly_f = 0.0
    if coin_stats and coin_stats["n_trades"] >= MIN_TRADES_KELLY:
        # Per-coin Kelly (most precise)
        kelly_f = kelly_fraction_for_market(
            coin_stats["win_rate"],
            coin_stats["win_loss_ratio"],
            kelly_fraction_mult,
        )
        details["kelly_source"] = "per_coin"
        details["kelly_stats"] = coin_stats
    else:
        # Global Kelly (fallback)
        all_closed = _stats_cache.get("closed", [])
        if len(all_closed) >= MIN_TRADES_GLOBAL:
            global_stats = _per_coin_stats(all_closed).get("_global_", None)
            # Calculate global stats manually
            wins, losses = [], []
            for t in all_closed:
                p = float(t.get("profit", 0) or 0)
                inv = float(t.get("invested_eur", 0) or 0)
                if inv <= 0:
                    continue
                pct = p / inv
                if p > 0:
                    wins.append(pct)
                elif p < 0:
                    losses.append(abs(pct))
            if wins and losses:
                wr = len(wins) / (len(wins) + len(losses))
                wlr = (sum(wins) / len(wins)) / (sum(losses) / len(losses))
                kelly_f = kelly_fraction_for_market(wr, wlr, kelly_fraction_mult)
                details["kelly_source"] = "global"
                details["global_win_rate"] = wr
                details["global_wl_ratio"] = wlr
            else:
                details["kelly_source"] = "none"
        else:
            details["kelly_source"] = "insufficient_data"

    kelly_amount = budget_eur * kelly_f if kelly_f > 0 else base_amount_eur
    details["kelly_fraction"] = round(kelly_f, 4)
    details["kelly_amount"] = round(kelly_amount, 2)

    # ── Step 2: Volatility Parity ──
    vol_weight = 1.0
    if all_market_candles:
        vols = {}
        for m, c in all_market_candles.items():
            v = _volatility_from_candles(c, window=VOL_PARITY_LOOKBACK)
            if v > 0:
                vols[m] = v

        if vols and market in vols:
            weights = volatility_parity_weights(vols)
            vol_weight = weights.get(market, 1.0 / len(vols))
            details["vol_weight"] = round(vol_weight, 4)
            details["market_vol"] = round(vols.get(market, 0), 6)
            # How many markets contribute
            n_markets = len(vols)
            # Scale: if weight > 1/n_markets, this coin gets MORE allocation
            vol_amount = base_amount_eur * (vol_weight * n_markets)
            details["vol_adjusted_amount"] = round(vol_amount, 2)
        else:
            vol_amount = base_amount_eur
            details["vol_weight"] = 1.0
    else:
        vol_amount = base_amount_eur

    # ── Step 3: Blend Kelly + Volatility Parity ──
    # 60% Kelly, 40% Vol Parity (Kelly is mathematically optimal, vol parity for risk management)
    if kelly_f > 0:
        blended = 0.6 * kelly_amount + 0.4 * vol_amount
    else:
        blended = vol_amount  # No Kelly data → pure vol parity

    # ── Step 4: Clamp to reasonable range ──
    final = max(MIN_POSITION_EUR, min(base_amount_eur * MAX_POSITION_MULT, blended))
    final = round(final, 2)

    details["vol_parity_amount"] = round(vol_amount, 2)
    details["blended_raw"] = round(blended, 2)
    details["final_amount"] = final

    log(
        f"[KELLY+VP] {market}: €{final:.2f} "
        f"(kelly_f={kelly_f:.3f}→€{kelly_amount:.0f}, vol_w={vol_weight:.3f}→€{vol_amount:.0f})",
        level="debug",
    )

    return {
        "amount_eur": final,
        "kelly_fraction": kelly_f,
        "vol_parity_weight": vol_weight,
        "details": details,
    }


def get_sizing_summary(
    markets: List[str],
    base_amount_eur: float = 40.0,
    trade_log_path: str = "data/trade_log.json",
) -> Dict[str, Dict[str, float]]:
    """Get position sizing summary for all active markets (for dashboard/Telegram)."""
    closed = _load_trade_history(trade_log_path)
    per_coin = _per_coin_stats(closed)

    summary = {}
    for m in markets:
        stats = per_coin.get(m, {})
        kelly_f = 0.0
        if stats and stats.get("n_trades", 0) >= MIN_TRADES_KELLY:
            kelly_f = kelly_fraction_for_market(stats["win_rate"], stats["win_loss_ratio"])

        summary[m] = {
            "win_rate": stats.get("win_rate", 0.0),
            "n_trades": stats.get("n_trades", 0),
            "kelly_fraction": round(kelly_f, 4),
            "suggested_amount": round(base_amount_eur * max(0.3, min(2.5, kelly_f * 5 + 0.5)), 2)
            if kelly_f > 0
            else base_amount_eur,
        }

    return summary
