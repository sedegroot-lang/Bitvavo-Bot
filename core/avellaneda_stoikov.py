"""core.avellaneda_stoikov – Dynamic Grid Spacing using the Avellaneda-Stoikov Model.

Implements the optimal market-making grid spacing formula from:
  Avellaneda & Stoikov (2008) "High-frequency trading in a limit order book"

Instead of fixed arithmetic/geometric grids, spacing adapts to:
  - Realized volatility (σ): higher vol → wider grids
  - Inventory risk (γ): more inventory → skew grids toward selling
  - Order fill intensity (κ): how quickly orders fill → adjust distance

Formula:
  δ* = γσ²T + (2/γ) * ln(1 + γ/κ)

Where:
  σ = realized volatility (annualized, from ATR or returns)
  γ = risk-aversion parameter (configurable)
  T = time horizon in fractions of day
  κ = order fill intensity (estimated from recent fills)

Used by: Wintermute, GSR, Jump Crypto, and other professional market makers.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Tuple

from modules.logging_utils import log

# ── Default Parameters ──
DEFAULT_GAMMA = 0.1          # Risk aversion (0.01=aggressive, 1.0=conservative)
DEFAULT_KAPPA = 1.5          # Order fill intensity (higher = more aggressive)
DEFAULT_TIME_HORIZON_H = 4   # Time horizon in hours
MIN_SPREAD_PCT = 0.003       # Minimum 0.3% spread per side
MAX_SPREAD_PCT = 0.05        # Maximum 5% spread per side
INVENTORY_SKEW_MAX = 0.5     # Max inventory skew (50% of spread)

# Cache
_vol_cache: Dict[str, Tuple[float, float]] = {}  # market → (vol, timestamp)
_VOL_CACHE_TTL = 300  # 5 minutes


def _realized_volatility(candles: List[List], window: int = 20) -> float:
    """Calculate realized volatility from candle data (annualized).

    Uses close-to-close log returns, annualized by √(periods_per_year).
    For 1m candles: periods_per_year ≈ 525,600
    For 5m candles: periods_per_year ≈ 105,120
    For 1h candles: periods_per_year ≈ 8,760
    """
    closes = []
    for c in candles:
        try:
            closes.append(float(c[4]))
        except (IndexError, TypeError, ValueError):
            continue

    if len(closes) < window + 1:
        return 0.0

    # Use most recent 'window' candles
    recent = closes[-(window + 1):]
    log_returns = [math.log(recent[i] / recent[i - 1]) for i in range(1, len(recent)) if recent[i - 1] > 0]

    if not log_returns:
        return 0.0

    # Sample standard deviation
    mu = sum(log_returns) / len(log_returns)
    variance = sum((r - mu) ** 2 for r in log_returns) / max(len(log_returns) - 1, 1)
    sigma = math.sqrt(variance)

    return sigma


def _estimate_fill_intensity(
    recent_fills: int = 10,
    time_window_hours: float = 24.0,
) -> float:
    """Estimate order fill intensity (κ).

    In production this would use actual fill counts from grid history.
    For now, use a reasonable default based on typical Bitvavo fill rates.
    """
    if time_window_hours <= 0:
        return DEFAULT_KAPPA
    fills_per_hour = recent_fills / time_window_hours
    # Map to κ: more fills = higher intensity = tighter spreads
    kappa = max(0.5, min(5.0, fills_per_hour / 2.0))
    return kappa


def calculate_optimal_spread(
    sigma: float,
    gamma: float = DEFAULT_GAMMA,
    kappa: float = DEFAULT_KAPPA,
    time_horizon_hours: float = DEFAULT_TIME_HORIZON_H,
) -> float:
    """Calculate optimal bid-ask spread using Avellaneda-Stoikov formula.

    δ* = γσ²T + (2/γ) * ln(1 + γ/κ)

    Returns: optimal spread as a decimal fraction (e.g., 0.01 = 1%)
    """
    if sigma <= 0 or gamma <= 0 or kappa <= 0:
        return MIN_SPREAD_PCT

    T = time_horizon_hours / 24.0  # Convert to fraction of day

    # A-S formula
    term1 = gamma * (sigma ** 2) * T
    term2 = (2.0 / gamma) * math.log(1.0 + gamma / kappa)
    delta = term1 + term2

    # Clamp to reasonable range
    delta = max(MIN_SPREAD_PCT, min(MAX_SPREAD_PCT, delta))

    return delta


def calculate_inventory_skew(
    inventory_ratio: float,
    gamma: float = DEFAULT_GAMMA,
    sigma: float = 0.01,
) -> float:
    """Calculate inventory-based price skew.

    When we hold too much inventory, skew the mid-price DOWN to encourage selling.
    When we hold too little, skew UP to encourage buying.

    inventory_ratio: current_inventory_value / target_inventory_value
                     1.0 = balanced, >1 = overweight, <1 = underweight

    Returns: skew as fraction of spread (positive = raise mid, negative = lower mid)
    """
    if inventory_ratio <= 0:
        return 0.0

    # Deviation from target
    deviation = inventory_ratio - 1.0

    # Skew proportional to deviation and risk aversion
    skew = -gamma * sigma * deviation

    # Clamp
    return max(-INVENTORY_SKEW_MAX, min(INVENTORY_SKEW_MAX, skew))


def calculate_dynamic_grid_levels(
    current_price: float,
    candles: List[List],
    num_levels: int = 10,
    total_investment_eur: float = 65.0,
    gamma: float = DEFAULT_GAMMA,
    time_horizon_hours: float = DEFAULT_TIME_HORIZON_H,
    inventory_ratio: float = 1.0,
    recent_fills: int = 10,
    fill_window_hours: float = 24.0,
    market: str = "BTC-EUR",
    buy_only: bool = False,
    base_eur_value: float = 0.0,
) -> Dict[str, Any]:
    """Calculate dynamic grid levels using Avellaneda-Stoikov model.

    Returns:
        levels: list of (price, side, amount_eur) tuples
        spread: optimal spread value
        details: diagnostic info
    """
    # 1. Calculate realized volatility
    sigma = _realized_volatility(candles, window=min(30, max(10, len(candles) // 3)))
    if sigma <= 0:
        sigma = 0.005  # Fallback: 0.5% per candle

    # 2. Estimate fill intensity
    kappa = _estimate_fill_intensity(recent_fills, fill_window_hours)

    # 3. Calculate optimal spread
    optimal_spread = calculate_optimal_spread(sigma, gamma, kappa, time_horizon_hours)

    # 4. Calculate inventory skew
    skew = calculate_inventory_skew(inventory_ratio, gamma, sigma)

    # 5. Calculate mid-price with skew
    skewed_mid = current_price * (1.0 + skew)

    # 6. Generate grid levels
    # Half above skewed mid (sell), half below (buy)
    levels_per_side = num_levels // 2
    # Number of sell levels to actually generate (may be reduced below)
    sell_count = 0 if buy_only else levels_per_side

    if buy_only:
        # Not enough base asset for even one sell: full budget to buy-side
        amount_per_buy = total_investment_eur / levels_per_side
        amount_per_sell = 0.0
    elif base_eur_value > 0 and levels_per_side > 0:
        # Proportional: sell budget capped by available base asset value
        naive_per_level = total_investment_eur / num_levels
        sell_budget_needed = naive_per_level * levels_per_side
        sell_budget_actual = min(sell_budget_needed, base_eur_value)
        # Determine how many sell levels can meet minimum order (€5)
        min_order = 5.0
        affordable_sells = min(int(sell_budget_actual / min_order), levels_per_side) if sell_budget_actual >= min_order else 0
        sell_count = affordable_sells
        if affordable_sells == 0:
            # Can't afford even one sell above minimum → full budget to buys
            buy_budget = total_investment_eur
            amount_per_buy = buy_budget / levels_per_side
            amount_per_sell = 0.0
        else:
            buy_budget = total_investment_eur - sell_budget_actual
            amount_per_buy = buy_budget / levels_per_side
            amount_per_sell = sell_budget_actual / affordable_sells
    else:
        amount_per_buy = total_investment_eur / num_levels
        amount_per_sell = total_investment_eur / num_levels

    levels = []

    # Spacing increases further from mid (non-linear for volatility adaptation)
    sells_placed = 0
    for i in range(1, levels_per_side + 1):
        # Spacing increases quadratically further from mid
        spacing_mult = 1.0 + 0.3 * (i - 1)  # Level 1: 1.0x, Level 5: 2.2x
        level_spread = optimal_spread * spacing_mult

        # Buy levels (below mid)
        buy_price = skewed_mid * (1.0 - level_spread * i / levels_per_side)
        # Sell levels (above mid)
        sell_price = skewed_mid * (1.0 + level_spread * i / levels_per_side)

        levels.append({
            "price": round(buy_price, 8),
            "side": "buy",
            "amount_eur": round(amount_per_buy, 2),
            "level_id": i - 1,
            "spread_pct": round(level_spread * 100, 3),
        })
        if sells_placed < sell_count:
            levels.append({
                "price": round(sell_price, 8),
                "side": "sell",
                "amount_eur": round(amount_per_sell, 2),
                "level_id": levels_per_side + i - 1,
                "spread_pct": round(level_spread * 100, 3),
            })
            sells_placed += 1

    # Sort by price
    levels.sort(key=lambda x: x["price"])

    details = {
        "sigma": round(sigma, 6),
        "sigma_annualized_pct": round(sigma * math.sqrt(365 * 24 * 60) * 100, 2),
        "optimal_spread_pct": round(optimal_spread * 100, 4),
        "gamma": gamma,
        "kappa": round(kappa, 3),
        "inventory_skew_pct": round(skew * 100, 4),
        "skewed_mid": round(skewed_mid, 2),
        "time_horizon_h": time_horizon_hours,
        "levels_count": len(levels),
    }

    log(
        f"[A-S GRID] {market}: spread={optimal_spread * 100:.3f}%, "
        f"σ={sigma:.5f}, skew={skew * 100:.3f}%, γ={gamma}, κ={kappa:.2f}",
        level="debug",
    )

    return {
        "levels": levels,
        "spread": optimal_spread,
        "skewed_mid": skewed_mid,
        "details": details,
    }


def should_widen_grid(current_spread_pct: float, candles: List[List]) -> Tuple[bool, float]:
    """Check if current grid spacing is too narrow for current volatility.

    Returns (should_widen, suggested_spread_pct)
    """
    sigma = _realized_volatility(candles)
    if sigma <= 0:
        return False, current_spread_pct

    optimal = calculate_optimal_spread(sigma)
    suggested = optimal * 100  # Convert to percentage

    if suggested > current_spread_pct * 1.5:
        return True, suggested

    return False, current_spread_pct


def get_volatility_adjusted_num_grids(
    base_num_grids: int,
    candles: List[List],
    min_grids: int = 5,
    max_grids: int = 20,
) -> int:
    """Adjust number of grid levels based on volatility.

    Higher volatility → fewer but wider grids
    Lower volatility → more but tighter grids
    """
    sigma = _realized_volatility(candles)
    if sigma <= 0:
        return base_num_grids

    # Baseline: sigma ≈ 0.005 → base_num_grids
    # Higher vol → fewer grids
    # Lower vol → more grids
    vol_ratio = sigma / 0.005 if sigma > 0 else 1.0
    adjusted = int(base_num_grids / vol_ratio)

    return max(min_grids, min(max_grids, adjusted))
