"""Smart Limit Execution — optimal order placement for better fills.

Analyses the orderbook to calculate the best limit price that maximizes
the chance of fill while minimizing slippage vs. mid-price.

Usage
-----
    from core.smart_execution import optimal_limit_price
    price, details = optimal_limit_price(book, side='buy', urgency=0.5)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _parse_book_side(levels: List) -> List[Tuple[float, float]]:
    """Parse orderbook levels into [(price, size), ...]."""
    parsed = []
    for level in levels:
        try:
            if isinstance(level, dict):
                p = float(level.get("price", 0))
                s = float(level.get("amount", 0) or level.get("size", 0))
            elif isinstance(level, (list, tuple)) and len(level) >= 2:
                p = float(level[0])
                s = float(level[1])
            else:
                continue
            if p > 0 and s > 0:
                parsed.append((p, s))
        except (ValueError, TypeError):
            continue
    return parsed


def optimal_limit_price(
    book: Dict[str, Any],
    side: str = "buy",
    urgency: float = 0.5,
    order_size_eur: float = 40.0,
) -> Tuple[Optional[float], Dict[str, Any]]:
    """Calculate optimal limit order price.

    Parameters
    ----------
    book : dict
        Orderbook with 'bids' and 'asks' lists.
    side : str
        'buy' or 'sell'
    urgency : float
        0.0 = patient (deeper in book), 1.0 = aggressive (at best bid/ask).
        0.5 = balanced (between bid and mid).
    order_size_eur : float
        Approximate order size in EUR for depth analysis.

    Returns
    -------
    (optimal_price, details) : tuple
    """
    if not book:
        return None, {"reason": "no_book"}

    bids = _parse_book_side(book.get("bids", []))
    asks = _parse_book_side(book.get("asks", []))

    if not bids or not asks:
        return None, {"reason": "empty_book"}

    best_bid = bids[0][0]
    best_ask = asks[0][0]
    mid_price = (best_bid + best_ask) / 2
    spread = best_ask - best_bid
    spread_pct = spread / mid_price * 100 if mid_price > 0 else 0

    if side == "buy":
        # For buying: we want to place between bid and mid
        # urgency=0: at best_bid (cheapest, may not fill)
        # urgency=0.5: between bid and mid (balanced)
        # urgency=1.0: at best_ask (overpays, guaranteed fill = market order)

        # Calculate depth-weighted price (where most liquidity sits)
        total_bid_volume = 0.0
        depth_weighted_price = 0.0
        for price, size in bids[:10]:
            eur_value = price * size
            total_bid_volume += eur_value
            depth_weighted_price += price * eur_value

        if total_bid_volume > 0:
            depth_weighted_price /= total_bid_volume
        else:
            depth_weighted_price = best_bid

        # Optimal price: blend between best_bid and mid based on urgency
        if urgency <= 0.3:
            # Patient: place at or just above best bid
            tick_improvement = spread * 0.05  # improve by 5% of spread
            optimal = best_bid + tick_improvement
        elif urgency <= 0.7:
            # Balanced: place between bid and mid
            blend = (urgency - 0.3) / 0.4  # 0.0 to 1.0 within this range
            optimal = best_bid + spread * (0.1 + blend * 0.35)
        else:
            # Urgent: place near mid or at ask
            blend = (urgency - 0.7) / 0.3
            optimal = mid_price + spread * blend * 0.3

        # Never pay more than best ask
        optimal = min(optimal, best_ask)

        # Check if there's a large wall at best bid (queue priority matters)
        bid_wall = bids[0][1] * bids[0][0] if bids else 0
        if bid_wall > order_size_eur * 10:
            # Large wall at bid — improve by 1 tick to get ahead
            optimal = max(optimal, best_bid + spread * 0.02)

    elif side == "sell":
        # For selling: mirror logic
        if urgency <= 0.3:
            tick_improvement = spread * 0.05
            optimal = best_ask - tick_improvement
        elif urgency <= 0.7:
            blend = (urgency - 0.3) / 0.4
            optimal = best_ask - spread * (0.1 + blend * 0.35)
        else:
            blend = (urgency - 0.7) / 0.3
            optimal = mid_price - spread * blend * 0.3

        optimal = max(optimal, best_bid)
    else:
        return None, {"reason": f"unknown_side:{side}"}

    # Calculate savings vs market order
    market_price = best_ask if side == "buy" else best_bid
    savings_pct = abs(optimal - market_price) / market_price * 100 if market_price > 0 else 0
    savings_eur = order_size_eur * savings_pct / 100

    details = {
        "optimal_price": round(optimal, 10),
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid_price": round(mid_price, 10),
        "spread_pct": round(spread_pct, 4),
        "urgency": urgency,
        "savings_vs_market_pct": round(savings_pct, 4),
        "savings_vs_market_eur": round(savings_eur, 4),
        "side": side,
    }

    logger.debug(
        f"[EXEC] {side}: optimal={optimal:.8f} "
        f"(bid={best_bid:.8f}, ask={best_ask:.8f}, spread={spread_pct:.3f}%, "
        f"save={savings_pct:.3f}%)"
    )

    return optimal, details


def should_use_limit_order(
    spread_pct: float,
    urgency: float = 0.5,
    score: float = 0.0,
    threshold: float = 10.0,
) -> bool:
    """Decide whether to use limit vs market order.

    Use limit when:
    - Spread is wide enough to benefit (>0.05%)
    - Signal is not extremely strong (urgent fills don't wait)
    - Urgency is moderate
    """
    # Very strong signal → use market order for guaranteed fill
    if score > threshold * 1.5 or urgency > 0.9:
        return False

    # Tight spread → limit order saves little, use market
    if spread_pct < 0.03:
        return False

    # Default: use limit if spread > 0.05%
    return spread_pct > 0.05


def calculate_urgency(
    score: float,
    threshold: float,
    btc_burst_active: bool = False,
    regime: str = "ranging",
) -> float:
    """Calculate execution urgency from 0.0 (patient) to 1.0 (fill now).

    High urgency when:
    - Score is very far above threshold (strong signal)
    - BTC is bursting (cascade opportunity is time-sensitive)
    - Market is trending (momentum = need fill NOW)
    """
    urgency = 0.5  # default balanced

    # Score excess → higher urgency
    excess = score - threshold
    if excess > 5:
        urgency += 0.3
    elif excess > 3:
        urgency += 0.2
    elif excess > 1:
        urgency += 0.1

    # BTC burst → higher urgency (time-sensitive cascade)
    if btc_burst_active:
        urgency += 0.2

    # Trending regime → higher urgency (don't miss the move)
    if regime in ("trending_up", "REGIME_TRENDING_UP"):
        urgency += 0.1
    elif regime in ("ranging", "REGIME_RANGING"):
        urgency -= 0.1  # can be more patient in ranging

    return max(0.0, min(1.0, urgency))
