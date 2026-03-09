"""core.funding_rate_oracle – Binance Perpetual Futures Funding Rate Oracle.

Uses FREE public Binance API to fetch funding rates as a contrarian market signal.
No API key needed. No futures trading. Just reads public data.

Signal logic:
  - Funding STRONGLY positive (>+0.05%) = market overleveraged long → bearish bias
  - Funding STRONGLY negative (<-0.03%) = market overleveraged short → short squeeze risk → bullish bias
  - Funding neutral (-0.03% to +0.05%) = no signal

This is one of the most reliable contrarian indicators in professional crypto quant trading.
Academic source: "Funding Rates and Futures Basis in Cryptocurrency Markets" (2021).
"""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Dict, Optional, Tuple

from modules.logging_utils import log

# ── Constants ──
BINANCE_FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
BINANCE_PREMIUM_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"

# Bitvavo market → Binance perpetual symbol mapping
MARKET_MAP = {
    "BTC-EUR": "BTCUSDT", "ETH-EUR": "ETHUSDT", "SOL-EUR": "SOLUSDT",
    "XRP-EUR": "XRPUSDT", "ADA-EUR": "ADAUSDT", "LINK-EUR": "LINKUSDT",
    "AAVE-EUR": "AAVEUSDT", "UNI-EUR": "UNIUSDT", "LTC-EUR": "LTCUSDT",
    "BCH-EUR": "BCHUSDT", "AVAX-EUR": "AVAXUSDT", "DOT-EUR": "DOTUSDT",
    "RENDER-EUR": "RENDERUSDT", "FET-EUR": "FETUSDT", "INJ-EUR": "INJUSDT",
    "OP-EUR": "OPUSDT", "APT-EUR": "APTUSDT", "HYPE-EUR": "HYPEUSDT",
    "NEAR-EUR": "NEARUSDT", "SUI-EUR": "SUIUSDT", "DOGE-EUR": "DOGEUSDT",
}

# Thresholds (in decimal, so 0.0005 = 0.05%)
FUNDING_BULLISH_THRESHOLD = -0.0003    # Below this → short squeeze risk → bullish
FUNDING_BEARISH_THRESHOLD = 0.0005     # Above this → overleveraged long → bearish
FUNDING_EXTREME_BULLISH = -0.001       # Very negative → strong bullish signal
FUNDING_EXTREME_BEARISH = 0.001        # Very positive → strong bearish signal

# Cache settings
_cache: Dict[str, Tuple[float, float, str]] = {}  # symbol → (rate, timestamp, signal)
_CACHE_TTL = 300  # 5 minutes (funding rate updates every 8h, no need to spam)
_btc_cache: Tuple[Optional[float], float] = (None, 0)  # (rate, timestamp)


def _fetch_json(url: str, timeout: int = 5) -> Optional[list | dict]:
    """Fetch JSON from URL with User-Agent header."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BitvavoBotOracle/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        log(f"[FundingOracle] Fetch failed {url}: {e}", level="debug")
        return None


def get_funding_rate(symbol: str) -> Optional[float]:
    """Get latest funding rate for a Binance perpetual symbol. Returns decimal (0.0001 = 0.01%)."""
    now = time.time()

    # Check cache
    if symbol in _cache:
        rate, cached_ts, _ = _cache[symbol]
        if now - cached_ts < _CACHE_TTL:
            return rate

    data = _fetch_json(f"{BINANCE_FUNDING_URL}?symbol={symbol}&limit=1")
    if not data or not isinstance(data, list) or len(data) == 0:
        return None

    try:
        rate = float(data[0]["fundingRate"])
        signal = _classify_signal(rate)
        _cache[symbol] = (rate, now, signal)
        return rate
    except (KeyError, ValueError, TypeError):
        return None


def get_btc_funding_rate() -> Optional[float]:
    """Get BTC funding rate (master signal for whole market)."""
    global _btc_cache
    now = time.time()
    if _btc_cache[0] is not None and now - _btc_cache[1] < _CACHE_TTL:
        return _btc_cache[0]

    rate = get_funding_rate("BTCUSDT")
    if rate is not None:
        _btc_cache = (rate, now)
    return rate


def _classify_signal(rate: float) -> str:
    """Classify funding rate into a signal category."""
    if rate <= FUNDING_EXTREME_BULLISH:
        return "strong_bullish"
    elif rate <= FUNDING_BULLISH_THRESHOLD:
        return "bullish"
    elif rate >= FUNDING_EXTREME_BEARISH:
        return "strong_bearish"
    elif rate >= FUNDING_BEARISH_THRESHOLD:
        return "bearish"
    return "neutral"


def get_market_signal(market: str) -> Dict[str, object]:
    """Get funding rate signal for a Bitvavo market.

    Returns dict with:
      - rate: float (raw funding rate)
      - signal: str (strong_bullish|bullish|neutral|bearish|strong_bearish)
      - score_modifier: float (bonus/penalty for signal scoring)
      - should_skip: bool (True if extremely bearish → skip this trade)
    """
    symbol = MARKET_MAP.get(market)
    if not symbol:
        return {"rate": None, "signal": "unknown", "score_modifier": 0.0, "should_skip": False}

    # Get coin-specific rate
    coin_rate = get_funding_rate(symbol)
    # Always also check BTC (systemic risk)
    btc_rate = get_btc_funding_rate()

    # Use coin-specific rate if available, otherwise fall back to BTC
    rate = coin_rate if coin_rate is not None else btc_rate
    if rate is None:
        return {"rate": None, "signal": "unavailable", "score_modifier": 0.0, "should_skip": False}

    signal = _classify_signal(rate)

    # Score modifiers — added to signal_strength score
    modifiers = {
        "strong_bullish": 2.0,     # Strong short squeeze → boost score
        "bullish": 1.0,            # Mild bullish bias
        "neutral": 0.0,            # No effect
        "bearish": -1.5,           # Reduce score (less favorable entry)
        "strong_bearish": -3.0,    # Strong penalty (overleveraged market)
    }

    score_mod = modifiers.get(signal, 0.0)
    should_skip = signal == "strong_bearish"

    # If BTC systemic risk is extreme bearish, override individual coin signal
    if btc_rate is not None and btc_rate >= FUNDING_EXTREME_BEARISH:
        if signal not in ("strong_bearish",):
            score_mod = min(score_mod, -2.0)
            should_skip = True
            signal = f"btc_systemic_bearish"

    return {
        "rate": round(rate, 8),
        "btc_rate": round(btc_rate, 8) if btc_rate is not None else None,
        "signal": signal,
        "score_modifier": score_mod,
        "should_skip": should_skip,
        "rate_pct": round(rate * 100, 4),  # Human-readable percentage
    }


def get_market_summary() -> Dict[str, Dict]:
    """Get funding rate summary for all mapped markets. Used by dashboard."""
    summary = {}
    for market in MARKET_MAP:
        try:
            summary[market] = get_market_signal(market)
        except Exception:
            summary[market] = {"signal": "error", "rate": None}
    return summary


def batch_prefetch(markets: list[str]) -> None:
    """Pre-fetch funding rates for a list of markets. Efficient: fetches BTC once + unique symbols."""
    # Always fetch BTC first (used as fallback)
    get_btc_funding_rate()

    # Deduplicate symbols
    symbols_needed = set()
    for m in markets:
        sym = MARKET_MAP.get(m)
        if sym and sym != "BTCUSDT":
            symbols_needed.add(sym)

    for sym in symbols_needed:
        try:
            get_funding_rate(sym)
        except Exception:
            pass
