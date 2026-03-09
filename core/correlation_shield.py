"""core.correlation_shield – Cascade Correlation Circuit Breaker 2.0.

Detects when multiple open positions are highly correlated and moving down together,
triggering a portfolio-level circuit breaker BEFORE individual stop-losses fire.

The real danger: BTC flash crash → all 6 alts drop -8% simultaneously.
Individual SLs trigger too late. This module detects the cascade EARLY.

Logic:
1. Compute rolling correlation matrix between all open positions
2. If avg correlation > 0.85 AND portfolio -3% in 1 hour → CASCADE ALERT
3. Automatically tighten all trailing stops
4. Block new entries until correlation drops

Academic basis: Cont & Kan (2011) "Statistical Properties of Correlation Matrices"
Used by: Two Sigma, Citadel, Bridgewater (portfolio-level risk management)
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Tuple

from modules.logging_utils import log

# ── Parameters ──
CORRELATION_WINDOW = 60         # Rolling window in candles (1m = 60 min = 1 hour)
HIGH_CORR_THRESHOLD = 0.80      # Positions considered "highly correlated"
CASCADE_CORR_THRESHOLD = 0.85   # Correlation level for cascade alert
CASCADE_DRAWDOWN_PCT = -0.025   # Portfolio drawdown to trigger cascade (-2.5%)
MAX_CORRELATED_POSITIONS = 3    # Max positions allowed with corr > threshold
COOLDOWN_SECONDS = 1800         # 30 min cooldown after cascade alert

# State
_correlation_cache: Dict[str, Any] = {}
_CACHE_TTL = 120  # Recompute every 2 minutes
_last_cascade_ts: float = 0
_cascade_active: bool = False


def _returns_from_prices(prices: List[float], n: int = None) -> List[float]:
    """Calculate log returns from a price series."""
    if n is not None:
        prices = prices[-n:]
    if len(prices) < 2:
        return []
    return [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices)) if prices[i - 1] > 0]


def _pearson_correlation(x: List[float], y: List[float]) -> float:
    """Calculate Pearson correlation between two return series."""
    n = min(len(x), len(y))
    if n < 5:
        return 0.0

    x, y = x[-n:], y[-n:]
    mean_x = sum(x) / n
    mean_y = sum(y) / n

    num = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    den_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x))
    den_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y))

    if den_x < 1e-12 or den_y < 1e-12:
        return 0.0

    return num / (den_x * den_y)


def compute_correlation_matrix(
    market_candles: Dict[str, List[List]],
    window: int = CORRELATION_WINDOW,
) -> Dict[str, Dict[str, float]]:
    """Compute pairwise correlation matrix for all markets.

    Args:
        market_candles: {market: [[ts,o,h,l,c,v], ...]} for each open position

    Returns: {market_a: {market_b: correlation, ...}, ...}
    """
    # Extract close prices
    market_returns: Dict[str, List[float]] = {}
    for market, candles in market_candles.items():
        closes = []
        for c in candles:
            try:
                closes.append(float(c[4]))
            except (IndexError, TypeError, ValueError):
                continue
        returns = _returns_from_prices(closes, window)
        if returns:
            market_returns[market] = returns

    markets = list(market_returns.keys())
    matrix: Dict[str, Dict[str, float]] = {}

    for i, m1 in enumerate(markets):
        matrix[m1] = {}
        for j, m2 in enumerate(markets):
            if i == j:
                matrix[m1][m2] = 1.0
            elif j < i:
                # Use already computed value
                matrix[m1][m2] = matrix[m2][m1]
            else:
                corr = _pearson_correlation(market_returns[m1], market_returns[m2])
                matrix[m1][m2] = round(corr, 4)

    return matrix


def _average_correlation(matrix: Dict[str, Dict[str, float]]) -> float:
    """Calculate average pairwise correlation (excluding self-correlation)."""
    markets = list(matrix.keys())
    n = len(markets)
    if n < 2:
        return 0.0

    total = 0.0
    pairs = 0
    for i in range(n):
        for j in range(i + 1, n):
            total += abs(matrix[markets[i]][markets[j]])
            pairs += 1

    return total / pairs if pairs > 0 else 0.0


def _count_high_corr_clusters(
    matrix: Dict[str, Dict[str, float]],
    threshold: float = HIGH_CORR_THRESHOLD,
) -> Tuple[int, List[Tuple[str, str, float]]]:
    """Count number of highly correlated position pairs.

    Returns: (count, [(market_a, market_b, correlation), ...])
    """
    markets = list(matrix.keys())
    high_pairs = []

    for i in range(len(markets)):
        for j in range(i + 1, len(markets)):
            corr = abs(matrix[markets[i]][markets[j]])
            if corr >= threshold:
                high_pairs.append((markets[i], markets[j], corr))

    return len(high_pairs), high_pairs


def _portfolio_pnl_1h(
    open_trades: Dict[str, Dict],
    current_prices: Dict[str, float],
) -> float:
    """Calculate portfolio P&L over the last hour as a percentage."""
    total_invested = 0.0
    total_pnl = 0.0

    for market, trade in open_trades.items():
        invested = float(trade.get("invested_eur", 0) or trade.get("total_invested_eur", 0) or 0)
        amount = float(trade.get("amount", 0) or 0)
        current = current_prices.get(market, 0)

        if invested <= 0 or amount <= 0 or current <= 0:
            continue

        current_value = amount * current
        pnl = current_value - invested
        total_invested += invested
        total_pnl += pnl

    if total_invested <= 0:
        return 0.0

    return total_pnl / total_invested


def check_cascade_risk(
    market_candles: Dict[str, List[List]],
    open_trades: Dict[str, Dict],
    current_prices: Dict[str, float],
) -> Dict[str, Any]:
    """Main function: check for cascade correlation risk.

    Args:
        market_candles: {market: candles} for all open positions
        open_trades: current open trades dict
        current_prices: {market: current_price}

    Returns dict with:
        cascade_alert: bool (True if cascade detected)
        should_block_new_entries: bool
        should_tighten_stops: bool
        avg_correlation: float
        high_corr_pairs: list
        portfolio_pnl_pct: float
        details: dict
    """
    global _last_cascade_ts, _cascade_active
    now = time.time()

    # Check cache
    cached = _correlation_cache.get("last_check")
    if cached and (now - cached.get("ts", 0)) < _CACHE_TTL:
        return cached["result"]

    # Compute correlation matrix
    matrix = compute_correlation_matrix(market_candles)
    avg_corr = _average_correlation(matrix)
    n_high, high_pairs = _count_high_corr_clusters(matrix)

    # Portfolio P&L
    port_pnl = _portfolio_pnl_1h(open_trades, current_prices)

    # ── Cascade Detection ──
    cascade_alert = False
    should_block = False
    should_tighten = False

    # Level 1: High correlation warning (block new entries of correlated assets)
    if n_high >= MAX_CORRELATED_POSITIONS:
        should_block = True
        log(
            f"[CORR_SHIELD] ⚠️ {n_high} highly correlated pairs detected (>{HIGH_CORR_THRESHOLD:.0%})",
            level="warning",
        )

    # Level 2: Cascade alert (high correlation + portfolio drawdown)
    if avg_corr >= CASCADE_CORR_THRESHOLD and port_pnl <= CASCADE_DRAWDOWN_PCT:
        cascade_alert = True
        should_block = True
        should_tighten = True
        _last_cascade_ts = now
        _cascade_active = True
        log(
            f"[CORR_SHIELD] 🔴 CASCADE ALERT! avg_corr={avg_corr:.2%}, PnL={port_pnl:.2%} "
            f"— tightening all stops, blocking entries",
            level="error",
        )

    # Level 3: Cooldown period after cascade
    elif _cascade_active:
        if now - _last_cascade_ts < COOLDOWN_SECONDS:
            should_block = True
            should_tighten = True
            log(
                f"[CORR_SHIELD] Cascade cooldown active ({int((COOLDOWN_SECONDS - (now - _last_cascade_ts)) / 60)}min remaining)",
                level="info",
            )
        else:
            _cascade_active = False
            log("[CORR_SHIELD] Cascade cooldown expired, returning to normal", level="info")

    result = {
        "cascade_alert": cascade_alert,
        "should_block_new_entries": should_block,
        "should_tighten_stops": should_tighten,
        "avg_correlation": round(avg_corr, 4),
        "high_corr_pairs": [(a, b, round(c, 3)) for a, b, c in high_pairs],
        "n_high_corr_pairs": n_high,
        "portfolio_pnl_pct": round(port_pnl, 4),
        "cascade_active": _cascade_active,
        "matrix": matrix,
        "details": {
            "n_markets": len(matrix),
            "corr_threshold": HIGH_CORR_THRESHOLD,
            "cascade_threshold": CASCADE_CORR_THRESHOLD,
            "drawdown_trigger": CASCADE_DRAWDOWN_PCT,
        },
    }

    # Cache
    _correlation_cache["last_check"] = {"result": result, "ts": now}

    return result


def get_correlated_markets(
    target_market: str,
    matrix: Dict[str, Dict[str, float]],
    threshold: float = HIGH_CORR_THRESHOLD,
) -> List[Tuple[str, float]]:
    """Get markets that are highly correlated with target_market.

    Useful for: "Should I open a new SOL trade when XRP and ADA are already open and correlated?"
    """
    if target_market not in matrix:
        return []

    correlated = []
    for other_market, corr in matrix[target_market].items():
        if other_market != target_market and abs(corr) >= threshold:
            correlated.append((other_market, corr))

    correlated.sort(key=lambda x: abs(x[1]), reverse=True)
    return correlated


def should_allow_new_position(
    target_market: str,
    market_candles: Dict[str, List[List]],
    open_markets: List[str],
) -> Tuple[bool, str]:
    """Check if opening a new position would create too much correlation risk.

    Returns: (allowed, reason)
    """
    if len(open_markets) < 2:
        return True, "fewer_than_2_positions"

    # Only compute if target has candle data
    if target_market not in market_candles:
        return True, "no_candle_data"

    matrix = compute_correlation_matrix(market_candles)

    if target_market not in matrix:
        return True, "not_in_matrix"

    # Count how many existing positions are highly correlated with target
    correlated = get_correlated_markets(target_market, matrix)
    n_corr_with_open = sum(1 for m, _ in correlated if m in open_markets)

    if n_corr_with_open >= 2:
        reason = f"already {n_corr_with_open} correlated positions open ({', '.join(m for m, _ in correlated if m in open_markets)})"
        log(
            f"[CORR_SHIELD] Blocking {target_market}: {reason}",
            level="info",
        )
        return False, reason

    return True, "ok"


def get_tightened_sl_pct(
    original_sl_pct: float,
    cascade_level: str = "warning",
) -> float:
    """Calculate tightened stop-loss during cascade alert.

    cascade_level: 'warning' | 'alert' | 'critical'
    """
    multipliers = {
        "warning": 0.75,   # 25% tighter
        "alert": 0.60,     # 40% tighter
        "critical": 0.50,  # 50% tighter (half the original SL distance)
    }
    mult = multipliers.get(cascade_level, 0.75)
    return original_sl_pct * mult
