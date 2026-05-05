"""core.orderbook_imbalance – Order Book Microstructure Signal.

Analyzes the Bitvavo order book to generate short-term directional signals
based on bid/ask volume imbalance.

Formula:
  OBI = V_bid / (V_bid + V_ask)

  OBI > 0.65 → More buying pressure → price likely to rise in 5-15 min
  OBI < 0.35 → More selling pressure → price likely to drop
  OBI 0.35-0.65 → Balanced → no signal

Academic basis:
  Cao, Chen, & Griffin (2005) "Informational Content of Order Book"
  Cont, Kukanov, Stoikov (2014) "The Price Impact of Order Book Events"

Uses Bitvavo's public book API at depth 25 (available without auth).
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

from modules.logging_utils import log

# ── Parameters ──
BOOK_DEPTH = 25  # Levels deep into the order book
OBI_BULLISH_THRESHOLD = 0.65  # Bid-heavy → price likely rising
OBI_BEARISH_THRESHOLD = 0.35  # Ask-heavy → price likely falling
OBI_STRONG_BULLISH = 0.75  # Very strong bid pressure
OBI_STRONG_BEARISH = 0.25  # Very strong ask pressure

# Large wall detection
WALL_SIZE_MULT = 5.0  # Must be 5x the average level size
WALL_PROXIMITY_PCT = 0.02  # Within 2% of current price

# Cache
_obi_cache: Dict[str, Tuple[float, float, Dict]] = {}  # market → (obi, ts, details)
_CACHE_TTL = 15  # 15 seconds (orderbook is dynamic)


def calculate_obi(
    bids: List[Tuple[float, float]],
    asks: List[Tuple[float, float]],
    levels: int = BOOK_DEPTH,
) -> float:
    """Calculate Order Book Imbalance from bid/ask arrays.

    Args:
        bids: [(price, size), ...] sorted best-to-worst
        asks: [(price, size), ...] sorted best-to-worst

    Returns: OBI value (0-1, higher = more buying pressure)
    """
    bid_vol = sum(size for _, size in bids[:levels])
    ask_vol = sum(size for _, size in asks[:levels])

    total = bid_vol + ask_vol
    if total <= 0:
        return 0.5  # Neutral

    return bid_vol / total


def calculate_weighted_obi(
    bids: List[Tuple[float, float]],
    asks: List[Tuple[float, float]],
    mid_price: float,
    levels: int = BOOK_DEPTH,
) -> float:
    """Calculate price-weighted OBI — levels closer to mid weigh more.

    Orders close to the spread carry more information than deep orders.
    Weight = 1 / (1 + distance_from_mid)
    """
    if mid_price <= 0:
        return calculate_obi(bids, asks, levels)

    def weighted_vol(orders: List[Tuple[float, float]]) -> float:
        total = 0.0
        for price, size in orders[:levels]:
            distance_pct = abs(price - mid_price) / mid_price
            weight = 1.0 / (1.0 + distance_pct * 50)  # Closer = higher weight
            total += size * weight * price  # EUR-denominated
        return total

    bid_vol = weighted_vol(bids)
    ask_vol = weighted_vol(asks)
    total = bid_vol + ask_vol

    if total <= 0:
        return 0.5

    return bid_vol / total


def detect_walls(
    bids: List[Tuple[float, float]],
    asks: List[Tuple[float, float]],
    current_price: float,
    levels: int = BOOK_DEPTH,
) -> Dict[str, Any]:
    """Detect large support/resistance walls in the order book.

    A "wall" is an order significantly larger than the average level.
    """
    walls = {"support": [], "resistance": []}

    # Average bid/ask size
    avg_bid_size = sum(s for _, s in bids[:levels]) / max(len(bids[:levels]), 1)
    avg_ask_size = sum(s for _, s in asks[:levels]) / max(len(asks[:levels]), 1)

    # Detect bid walls (support)
    for price, size in bids[:levels]:
        if size >= avg_bid_size * WALL_SIZE_MULT:
            distance_pct = (current_price - price) / current_price if current_price > 0 else 0
            if distance_pct <= WALL_PROXIMITY_PCT:
                walls["support"].append(
                    {
                        "price": price,
                        "size_eur": round(price * size, 2),
                        "distance_pct": round(distance_pct * 100, 3),
                        "mult": round(size / avg_bid_size, 1),
                    }
                )

    # Detect ask walls (resistance)
    for price, size in asks[:levels]:
        if size >= avg_ask_size * WALL_SIZE_MULT:
            distance_pct = (price - current_price) / current_price if current_price > 0 else 0
            if distance_pct <= WALL_PROXIMITY_PCT:
                walls["resistance"].append(
                    {
                        "price": price,
                        "size_eur": round(price * size, 2),
                        "distance_pct": round(distance_pct * 100, 3),
                        "mult": round(size / avg_ask_size, 1),
                    }
                )

    return walls


def analyze_orderbook(
    book: Dict[str, List],
    current_price: float,
    market: str = "",
) -> Dict[str, Any]:
    """Full order book analysis for a market.

    Args:
        book: {'bids': [[price, size], ...], 'asks': [[price, size], ...]}
        current_price: current market price
        market: market identifier

    Returns dict with:
        obi: float (0-1)
        weighted_obi: float (0-1, price-distance weighted)
        signal: str (strong_bullish|bullish|neutral|bearish|strong_bearish)
        score_modifier: float (bonus for signal scoring)
        should_delay_sell: bool (OBI bullish → don't sell yet)
        should_delay_buy: bool (OBI bearish → don't buy yet)
        walls: dict (support/resistance walls)
        spread_pct: float (current bid-ask spread)
        details: dict
    """
    now = time.time()

    # Check cache
    if market in _obi_cache:
        cached_obi, cached_ts, cached_result = _obi_cache[market]
        if now - cached_ts < _CACHE_TTL:
            return cached_result

    # Parse book
    raw_bids = book.get("bids", [])
    raw_asks = book.get("asks", [])

    bids = []
    for entry in raw_bids:
        try:
            bids.append((float(entry[0]), float(entry[1])))
        except (IndexError, TypeError, ValueError):
            continue

    asks = []
    for entry in raw_asks:
        try:
            asks.append((float(entry[0]), float(entry[1])))
        except (IndexError, TypeError, ValueError):
            continue

    if not bids or not asks:
        return {
            "obi": 0.5,
            "weighted_obi": 0.5,
            "signal": "no_data",
            "score_modifier": 0.0,
            "should_delay_sell": False,
            "should_delay_buy": False,
            "walls": {"support": [], "resistance": []},
            "spread_pct": 0.0,
            "details": {},
        }

    # Calculate mid price and spread
    best_bid = bids[0][0]
    best_ask = asks[0][0]
    mid_price = (best_bid + best_ask) / 2
    spread_pct = (best_ask - best_bid) / mid_price if mid_price > 0 else 0

    # OBI calculations
    obi = calculate_obi(bids, asks)
    w_obi = calculate_weighted_obi(bids, asks, mid_price)

    # Wall detection
    walls = detect_walls(bids, asks, current_price)

    # Signal classification (use weighted OBI as primary)
    if w_obi >= OBI_STRONG_BULLISH:
        signal = "strong_bullish"
        score_mod = 1.5
    elif w_obi >= OBI_BULLISH_THRESHOLD:
        signal = "bullish"
        score_mod = 0.5
    elif w_obi <= OBI_STRONG_BEARISH:
        signal = "strong_bearish"
        score_mod = -1.5
    elif w_obi <= OBI_BEARISH_THRESHOLD:
        signal = "bearish"
        score_mod = -0.5
    else:
        signal = "neutral"
        score_mod = 0.0

    # Wall-based adjustments
    has_support = len(walls["support"]) > 0
    has_resistance = len(walls["resistance"]) > 0
    if has_support and not has_resistance:
        score_mod += 0.3  # Support wall = safer entry
    elif has_resistance and not has_support:
        score_mod -= 0.3  # Resistance wall = harder to break up

    should_delay_sell = signal in ("strong_bullish", "bullish") and has_support
    should_delay_buy = signal in ("strong_bearish", "bearish") and has_resistance

    result = {
        "obi": round(obi, 4),
        "weighted_obi": round(w_obi, 4),
        "signal": signal,
        "score_modifier": round(score_mod, 2),
        "should_delay_sell": should_delay_sell,
        "should_delay_buy": should_delay_buy,
        "walls": walls,
        "spread_pct": round(spread_pct * 100, 4),
        "details": {
            "bid_volume_eur": round(sum(p * s for p, s in bids[:BOOK_DEPTH]), 2),
            "ask_volume_eur": round(sum(p * s for p, s in asks[:BOOK_DEPTH]), 2),
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid_price": round(mid_price, 8),
            "n_support_walls": len(walls["support"]),
            "n_resistance_walls": len(walls["resistance"]),
        },
    }

    # Cache
    _obi_cache[market] = (w_obi, now, result)

    if signal != "neutral" or walls["support"] or walls["resistance"]:
        log(
            f"[OBI] {market}: {signal} (OBI={w_obi:.3f}, spread={spread_pct * 100:.3f}%, "
            f"walls: {len(walls['support'])} support / {len(walls['resistance'])} resistance)",
            level="debug",
        )

    return result


def get_orderbook_signal(
    market: str,
    book: Dict[str, List],
    current_price: float,
) -> Dict[str, Any]:
    """Simplified interface for bot integration. Returns score modifier and delay flags."""
    result = analyze_orderbook(book, current_price, market)
    return {
        "score_modifier": result["score_modifier"],
        "should_delay_buy": result["should_delay_buy"],
        "should_delay_sell": result["should_delay_sell"],
        "signal": result["signal"],
        "obi": result["weighted_obi"],
    }
