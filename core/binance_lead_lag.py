"""core.binance_lead_lag – Binance price leads Bitvavo by 15-90 seconds.

Uses FREE public Binance API to detect price moves before they hit Bitvavo.
Academic evidence: "Price Discovery in Cryptocurrency Markets" (Makarov & Schoar, 2020).

Use cases:
  1. Grid bot: Don't place sell orders if Binance shows uptrend (price hasn't caught up yet)
  2. Trailing bot: Extend trailing activation window during Binance uptrend
  3. Stop-loss: Delay execution if Binance already reversed upward

All endpoints are public, no API key needed.
"""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Dict, Optional, Tuple

from modules.logging_utils import log

BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/price"

# Bitvavo market → Binance spot symbol
SYMBOL_MAP = {
    "BTC-EUR": "BTCUSDT", "ETH-EUR": "ETHUSDT", "SOL-EUR": "SOLUSDT",
    "XRP-EUR": "XRPUSDT", "ADA-EUR": "ADAUSDT", "LINK-EUR": "LINKUSDT",
    "AAVE-EUR": "AAVEUSDT", "UNI-EUR": "UNIUSDT", "LTC-EUR": "LTCUSDT",
    "BCH-EUR": "BCHUSDT", "AVAX-EUR": "AVAXUSDT", "RENDER-EUR": "RENDERUSDT",
    "FET-EUR": "FETUSDT", "INJ-EUR": "INJUSDT", "APT-EUR": "APTUSDT",
    "OP-EUR": "OPUSDT", "NEAR-EUR": "NEARUSDT", "DOT-EUR": "DOTUSDT",
}

# EUR/USD approximate rate (updated periodically)
_eurusd_rate: float = 1.05  # Conservative estimate, updated below
_eurusd_ts: float = 0

# Price history for trend detection
_price_history: Dict[str, list] = {}  # symbol → [(ts, price), ...]
_HISTORY_WINDOW = 120  # Keep last 2 minutes of prices
_MAX_HISTORY = 30  # Max data points per symbol

# Cache single fetch
_price_cache: Dict[str, Tuple[float, float]] = {}  # symbol → (price_usd, ts)
_CACHE_TTL = 10  # 10 seconds between fetches


def _fetch_json(url: str, timeout: int = 3) -> Optional[dict | list]:
    """Fetch JSON from URL."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BitvavoBotLeadLag/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        log(f"[LeadLag] Fetch failed: {e}", level="debug")
        return None


def _update_eurusd() -> float:
    """Update EUR/USD rate from Binance (EURUSDT pair)."""
    global _eurusd_rate, _eurusd_ts
    now = time.time()
    if now - _eurusd_ts < 3600:  # Update hourly
        return _eurusd_rate
    try:
        data = _fetch_json(f"{BINANCE_TICKER_URL}?symbol=EURUSDT")
        if data and "price" in data:
            _eurusd_rate = float(data["price"])
            _eurusd_ts = now
    except Exception:
        pass
    return _eurusd_rate


def get_binance_price_eur(market: str) -> Optional[float]:
    """Get Binance price converted to EUR for a Bitvavo market."""
    symbol = SYMBOL_MAP.get(market)
    if not symbol:
        return None

    now = time.time()
    if symbol in _price_cache:
        cached_price, cached_ts = _price_cache[symbol]
        if now - cached_ts < _CACHE_TTL:
            return cached_price / _update_eurusd()

    data = _fetch_json(f"{BINANCE_TICKER_URL}?symbol={symbol}")
    if not data or "price" not in data:
        return None

    try:
        price_usd = float(data["price"])
        _price_cache[symbol] = (price_usd, now)

        # Add to history
        if symbol not in _price_history:
            _price_history[symbol] = []
        _price_history[symbol].append((now, price_usd))
        # Trim old entries
        cutoff = now - _HISTORY_WINDOW
        _price_history[symbol] = [
            (ts, p) for ts, p in _price_history[symbol] if ts > cutoff
        ][-_MAX_HISTORY:]

        return price_usd / _update_eurusd()
    except (ValueError, TypeError):
        return None


def detect_lead_signal(market: str, bitvavo_price: float) -> Dict[str, object]:
    """Detect if Binance is leading Bitvavo in a direction.

    Uses RELATIVE price changes (not absolute) to avoid EUR/USDT conversion issues.

    Returns:
      - direction: 'up' | 'down' | 'neutral'
      - binance_trend_pct: float (Binance % change over last 60s)
      - should_delay_sell: bool (True if Binance trending up → don't sell yet)
      - should_delay_buy: bool (True if Binance trending down → wait)
    """
    symbol = SYMBOL_MAP.get(market)
    if not symbol:
        return {"direction": "unknown", "binance_trend_pct": 0.0, "should_delay_sell": False, "should_delay_buy": False}

    # Fetch current Binance price (in USD, doesn't matter — we use % change)
    now = time.time()
    if symbol in _price_cache:
        cached_price, cached_ts = _price_cache[symbol]
        if now - cached_ts < _CACHE_TTL:
            binance_usd = cached_price
        else:
            data = _fetch_json(f"{BINANCE_TICKER_URL}?symbol={symbol}")
            if not data or "price" not in data:
                return {"direction": "unknown", "binance_trend_pct": 0.0, "should_delay_sell": False, "should_delay_buy": False}
            binance_usd = float(data["price"])
            _price_cache[symbol] = (binance_usd, now)
    else:
        data = _fetch_json(f"{BINANCE_TICKER_URL}?symbol={symbol}")
        if not data or "price" not in data:
            return {"direction": "unknown", "binance_trend_pct": 0.0, "should_delay_sell": False, "should_delay_buy": False}
        binance_usd = float(data["price"])
        _price_cache[symbol] = (binance_usd, now)

    # Add to history
    if symbol not in _price_history:
        _price_history[symbol] = []
    _price_history[symbol].append((now, binance_usd))
    cutoff = now - _HISTORY_WINDOW
    _price_history[symbol] = [
        (ts, p) for ts, p in _price_history[symbol] if ts > cutoff
    ][-_MAX_HISTORY:]

    # Calculate Binance short-term trend (last 60 seconds)
    binance_trend = 0.0
    history = _price_history.get(symbol, [])
    if len(history) >= 3:
        # Compare oldest point (within last 60s) to most recent
        window_60s = [(ts, p) for ts, p in history if now - ts <= 60]
        if len(window_60s) >= 2:
            binance_trend = ((window_60s[-1][1] - window_60s[0][1]) / window_60s[0][1]) * 100

    # Decision logic based on Binance trend (not cross-exchange spread)
    direction = "neutral"
    should_delay_sell = False
    should_delay_buy = False

    if binance_trend > 0.12:
        # Binance has gone up >0.12% in last 60s → Bitvavo likely to follow
        direction = "up"
        should_delay_sell = True  # Don't sell, price is going up
    elif binance_trend < -0.12:
        # Binance trending down → Bitvavo will follow down
        direction = "down"
        should_delay_buy = True  # Don't buy, price is going down

    return {
        "direction": direction,
        "binance_trend_pct": round(binance_trend, 4),
        "should_delay_sell": should_delay_sell,
        "should_delay_buy": should_delay_buy,
    }
