# ai_sentiment.py
"""
Nieuws en Sentiment Analyse Module voor AI Trading Bot
Haalt crypto nieuws en berekent sentiment scores
"""

import json

# Project imports
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.json_compat import write_json_compat
from modules.logging_utils import log

# Data paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SENTIMENT_CACHE_FILE = PROJECT_ROOT / "data" / "sentiment_cache.json"
SENTIMENT_HISTORY_FILE = PROJECT_ROOT / "data" / "sentiment_history.json"

# Sentiment keywords voor crypto
BULLISH_KEYWORDS = [
    "bullish",
    "surge",
    "rally",
    "breakout",
    "moon",
    "pump",
    "soar",
    "jump",
    "gain",
    "rise",
    "bull run",
    "all-time high",
    "ath",
    "adoption",
    "partnership",
    "institutional",
    "upgrade",
    "launch",
    "mainnet",
    "halving",
    "buy signal",
    "accumulation",
    "whale buying",
    "outperform",
    "breakthrough",
    "milestone",
    "positive",
    "optimistic",
    "growth",
    "recovery",
    "strong",
    "momentum",
]

BEARISH_KEYWORDS = [
    "bearish",
    "crash",
    "dump",
    "plunge",
    "sell-off",
    "selloff",
    "drop",
    "fall",
    "decline",
    "bear market",
    "correction",
    "fud",
    "hack",
    "exploit",
    "rug pull",
    "scam",
    "ban",
    "regulation",
    "lawsuit",
    "sec",
    "investigation",
    "bankrupt",
    "insolvency",
    "liquidation",
    "capitulation",
    "death cross",
    "sell signal",
    "negative",
    "pessimistic",
    "weak",
    "fear",
    "panic",
    "warning",
    "risk",
]

# Coin name mappings
COIN_ALIASES = {
    "BTC": ["bitcoin", "btc"],
    "ETH": ["ethereum", "eth", "ether"],
    "XRP": ["xrp", "ripple"],
    "SOL": ["solana", "sol"],
    "ADA": ["cardano", "ada"],
    "DOGE": ["dogecoin", "doge"],
    "AVAX": ["avalanche", "avax"],
    "DOT": ["polkadot", "dot"],
    "LINK": ["chainlink", "link"],
    "MATIC": ["polygon", "matic"],
    "UNI": ["uniswap", "uni"],
    "ATOM": ["cosmos", "atom"],
    "LTC": ["litecoin", "ltc"],
    "NEAR": ["near protocol", "near"],
    "ALGO": ["algorand", "algo"],
}


def _load_cache() -> dict:
    """Load sentiment cache from disk."""
    try:
        if SENTIMENT_CACHE_FILE.exists():
            with open(SENTIMENT_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"entries": [], "last_update": 0}


def _save_cache(cache: dict):
    """Save sentiment cache to disk."""
    try:
        SENTIMENT_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        write_json_compat(str(SENTIMENT_CACHE_FILE), cache)
    except Exception as e:
        log(f"[SENTIMENT] Cache save error: {e}", level="warning")


def analyze_text_sentiment(text: str, coin: Optional[str] = None) -> dict:
    """
    Analyze sentiment of a text.
    Returns dict with score (-1 to 1), label, and keyword matches.
    """
    text_lower = text.lower()

    # Count keyword matches
    bullish_matches = [kw for kw in BULLISH_KEYWORDS if kw in text_lower]
    bearish_matches = [kw for kw in BEARISH_KEYWORDS if kw in text_lower]

    bullish_count = len(bullish_matches)
    bearish_count = len(bearish_matches)
    total = bullish_count + bearish_count

    if total == 0:
        score = 0.0
        label = "NEUTRAL"
    else:
        # Score between -1 (bearish) and 1 (bullish)
        score = (bullish_count - bearish_count) / total

        if score > 0.3:
            label = "BULLISH"
        elif score < -0.3:
            label = "BEARISH"
        else:
            label = "NEUTRAL"

    # Check if coin is mentioned
    coin_mentioned = False
    if coin:
        coin_base = coin.replace("-EUR", "").upper()
        aliases = COIN_ALIASES.get(coin_base, [coin_base.lower()])
        coin_mentioned = any(alias in text_lower for alias in aliases)

    return {
        "score": round(score, 3),
        "label": label,
        "bullish_keywords": bullish_matches,
        "bearish_keywords": bearish_matches,
        "coin_mentioned": coin_mentioned,
        "confidence": min(1.0, total / 5),  # More keywords = higher confidence
    }


def _fetch_btc_candles(interval: str = "1h", limit: int = 48) -> list:
    """Fetch real BTC-EUR candles from Bitvavo for sentiment calculation."""
    try:
        from utils import get_bitvavo_client

        client = get_bitvavo_client()
        if client:
            candles = client.candles("BTC-EUR", interval, {"limit": limit})
            if isinstance(candles, list) and len(candles) >= 10:
                return candles
    except Exception as e:
        log(f"[SENTIMENT] BTC candle fetch failed: {e}", level="debug")
    return []


def _calculate_btc_trend(candles: list) -> dict:
    """Derive trend metrics from BTC candles (real market data)."""
    if not candles or len(candles) < 10:
        return {"trend_score": 0.0, "volatility": 1.0, "momentum": 0.0, "sma_position": 0.0}

    closes = []
    for c in candles:
        try:
            closes.append(float(c[4]) if len(c) > 4 else float(c[3]))
        except (IndexError, TypeError, ValueError):
            continue

    if len(closes) < 10:
        return {"trend_score": 0.0, "volatility": 1.0, "momentum": 0.0, "sma_position": 0.0}

    # Current price vs SMA-20 (or however many candles we have)
    sma_period = min(20, len(closes))
    sma_val = sum(closes[-sma_period:]) / sma_period
    current = closes[-1]
    sma_position = (current - sma_val) / sma_val if sma_val > 0 else 0.0

    # Momentum: price change over last 12 candles
    lookback = min(12, len(closes) - 1)
    momentum = (closes[-1] - closes[-(lookback + 1)]) / closes[-(lookback + 1)] if closes[-(lookback + 1)] > 0 else 0.0

    # Volatility: std/mean of returns
    returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes)) if closes[i - 1] > 0]
    if returns:
        avg_ret = sum(returns) / len(returns)
        std_ret = (sum((r - avg_ret) ** 2 for r in returns) / len(returns)) ** 0.5
        volatility = std_ret * (len(returns) ** 0.5) if std_ret > 0 else 0.5
    else:
        volatility = 1.0

    # Higher highs / lower lows count
    higher_high = sum(1 for i in range(1, min(10, len(closes))) if closes[-i] > closes[-i - 1])
    trend_score = (higher_high / min(9, len(closes) - 1)) * 2 - 1  # -1 to +1

    # Composite trend: weight SMA position, momentum, trend direction
    composite = sma_position * 50 + momentum * 30 + trend_score * 0.2

    return {
        "trend_score": round(composite, 4),
        "sma_position": round(sma_position, 4),
        "momentum": round(momentum, 4),
        "volatility": round(min(3.0, max(0.1, volatility)), 3),
        "higher_highs": higher_high,
        "current_price": current,
        "sma_value": round(sma_val, 2),
    }


def get_market_sentiment(coin: Optional[str] = None) -> dict:
    """
    Get market sentiment based on REAL BTC candle data from Bitvavo.

    Uses BTC-EUR candles to derive: trend, momentum, volatility.
    Falls back to time-based heuristics only if API unavailable.

    Returns:
        dict with overall sentiment score and breakdown
    """
    cache = _load_cache()
    now = time.time()

    # Return cached if fresh (< 15 minutes for real data, 5 min for simulated)
    cache_ttl = 900
    if now - cache.get("last_update", 0) < cache_ttl:
        cached_sentiment = cache.get("market_sentiment", {})
        if cached_sentiment:
            return cached_sentiment

    hour = datetime.now(timezone.utc).hour
    day = datetime.now(timezone.utc).weekday()

    # === PRIMARY: Real BTC candle data ===
    btc_candles = _fetch_btc_candles("1h", 48)
    btc_trend = _calculate_btc_trend(btc_candles)
    source = "btc_candles" if btc_candles else "time_heuristic"

    if btc_candles:
        # Real data-driven score
        base_score = max(-1.0, min(1.0, btc_trend["trend_score"]))
        volatility_factor = btc_trend["volatility"]

        # Fear & Greed derived from trend + volatility
        # Strong uptrend + low vol = greed; downtrend + high vol = fear
        raw_fg = 50 + base_score * 35 - (volatility_factor - 1.0) * 15
        fear_greed = max(0, min(100, round(raw_fg)))
    else:
        # Fallback: time-based heuristics (clearly labeled)
        base_score = 0.0
        if day >= 5:
            base_score -= 0.05
        volatility_factor = 1.3 if 14 <= hour <= 21 else 1.0
        fear_greed = 50

    # Weekend liquidity penalty (applies to both real and simulated)
    if day >= 5:
        base_score -= 0.03
        volatility_factor = max(volatility_factor, 1.1)

    if fear_greed > 75:
        fear_greed_label = "EXTREME_GREED"
    elif fear_greed > 55:
        fear_greed_label = "GREED"
    elif fear_greed > 45:
        fear_greed_label = "NEUTRAL"
    elif fear_greed > 25:
        fear_greed_label = "FEAR"
    else:
        fear_greed_label = "EXTREME_FEAR"

    sentiment = {
        "overall_score": round(max(-1.0, min(1.0, base_score)), 3),
        "overall_label": "BULLISH" if base_score > 0.15 else ("BEARISH" if base_score < -0.15 else "NEUTRAL"),
        "fear_greed_index": fear_greed,
        "fear_greed_label": fear_greed_label,
        "volatility_factor": round(volatility_factor, 3),
        "market_hours": "US_OPEN" if 14 <= hour <= 21 else ("ASIA_OPEN" if 0 <= hour <= 8 else "EU_OPEN"),
        "weekend": day >= 5,
        "timestamp": now,
        "source": source,
        "btc_trend": btc_trend,
    }

    # Coin-specific sentiment modifier
    if coin:
        coin_base = coin.replace("-EUR", "").upper()
        if coin_base in ["BTC", "ETH"]:
            sentiment["coin_sentiment"] = round(base_score * 0.9, 3)
            sentiment["coin_stability"] = "HIGH"
        elif coin_base in ["SOL", "XRP", "ADA", "DOT"]:
            sentiment["coin_sentiment"] = round(base_score * 1.1, 3)
            sentiment["coin_stability"] = "MEDIUM"
        else:
            sentiment["coin_sentiment"] = round(base_score * 1.3, 3)
            sentiment["coin_stability"] = "LOW"

    # Cache result
    cache["market_sentiment"] = sentiment
    cache["last_update"] = now
    _save_cache(cache)

    return sentiment


def get_trading_recommendation(coin: str, current_price: float = 0) -> dict:
    """
    Get AI trading recommendation based on sentiment.

    Returns:
        dict with recommendation, confidence, and reasoning
    """
    sentiment = get_market_sentiment(coin)

    score = sentiment.get("overall_score", 0)
    fear_greed = sentiment.get("fear_greed_index", 50)
    coin_sentiment = sentiment.get("coin_sentiment", score)

    # Calculate recommendation
    reasons = []

    # Fear & Greed based
    if fear_greed < 25:
        reasons.append(f"Extreme fear ({fear_greed}) - potential buying opportunity")
        recommendation = "BUY"
        confidence = 0.7
    elif fear_greed > 75:
        reasons.append(f"Extreme greed ({fear_greed}) - consider taking profits")
        recommendation = "SELL"
        confidence = 0.6
    else:
        recommendation = "HOLD"
        confidence = 0.5

    # Adjust for coin-specific sentiment
    if coin_sentiment > 0.3:
        reasons.append(f"Positive coin sentiment ({coin_sentiment:.2f})")
        if recommendation == "HOLD":
            recommendation = "BUY"
            confidence = 0.55
    elif coin_sentiment < -0.3:
        reasons.append(f"Negative coin sentiment ({coin_sentiment:.2f})")
        if recommendation == "HOLD":
            recommendation = "SELL"
            confidence = 0.55

    # Weekend caution
    if sentiment.get("weekend"):
        reasons.append("Weekend - lower liquidity")
        confidence *= 0.9

    return {
        "coin": coin,
        "recommendation": recommendation,
        "confidence": round(confidence, 3),
        "reasons": reasons,
        "sentiment": sentiment,
        "timestamp": time.time(),
    }


def record_sentiment_for_trade(market: str, action: str, sentiment_at_trade: dict):
    """
    Record sentiment at time of trade for later analysis.
    """
    try:
        history = []
        if SENTIMENT_HISTORY_FILE.exists():
            with open(SENTIMENT_HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)

        history.append(
            {
                "market": market,
                "action": action,  # 'BUY' or 'SELL'
                "sentiment": sentiment_at_trade,
                "timestamp": time.time(),
            }
        )

        # Keep last 500 entries
        history = history[-500:]

        write_json_compat(str(SENTIMENT_HISTORY_FILE), history)

    except Exception as e:
        log(f"[SENTIMENT] History record error: {e}", level="warning")


def analyze_sentiment_accuracy() -> dict:
    """
    Analyze how accurate sentiment was at predicting trade outcomes.
    Requires trade_log.json to compare.
    """
    try:
        if not SENTIMENT_HISTORY_FILE.exists():
            return {"error": "No sentiment history available"}

        with open(SENTIMENT_HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)

        if len(history) < 10:
            return {"error": "Not enough data (need 10+ trades)"}

        # This would correlate with actual trade outcomes
        # For now return basic stats
        bullish_at_buy = sum(
            1 for h in history if h.get("action") == "BUY" and h.get("sentiment", {}).get("overall_score", 0) > 0
        )

        total_buys = sum(1 for h in history if h.get("action") == "BUY")

        return {
            "total_records": len(history),
            "buys_with_positive_sentiment": bullish_at_buy,
            "total_buys": total_buys,
            "sentiment_buy_alignment": round(bullish_at_buy / total_buys, 3) if total_buys > 0 else 0,
        }

    except Exception as e:
        return {"error": str(e)}


# Integration function for AI supervisor
def get_sentiment_adjustment(coin: str) -> dict:
    """
    Get sentiment-based parameter adjustments for AI supervisor.
    Uses real BTC trend data to drive adjustments.

    Returns:
        dict with suggested parameter adjustments
    """
    sentiment = get_market_sentiment(coin)
    adjustments = {}

    fear_greed = sentiment.get("fear_greed_index", 50)
    overall = sentiment.get("overall_score", 0)
    btc_trend = sentiment.get("btc_trend", {})
    momentum = btc_trend.get("momentum", 0.0)
    vol = btc_trend.get("volatility", 1.0)
    is_real = sentiment.get("source") == "btc_candles"

    # Only generate strong adjustments when backed by real data
    confidence_mult = 1.0 if is_real else 0.3

    # Extreme fear (real or simulated)
    if fear_greed < 25:
        adjustments["MIN_SCORE_TO_BUY"] = {
            "direction": "decrease",
            "magnitude": 0.5 * confidence_mult,
            "reason": f"Fear/Greed {fear_greed} (extreme fear) - buying opportunity",
        }
        if is_real and momentum < -0.03:
            adjustments["HARD_SL_ALT_PCT"] = {
                "direction": "decrease",
                "magnitude": 0.005,
                "reason": f"BTC momentum {momentum:.1%} negative in fear - tighter stops",
            }

    # Extreme greed
    elif fear_greed > 75:
        adjustments["MIN_SCORE_TO_BUY"] = {
            "direction": "increase",
            "magnitude": 0.5 * confidence_mult,
            "reason": f"Fear/Greed {fear_greed} (extreme greed) - be selective",
        }
        adjustments["DEFAULT_TRAILING"] = {
            "direction": "decrease",
            "magnitude": 0.005 * confidence_mult,
            "reason": "Extreme greed - take profits faster",
        }

    # High BTC volatility — reduce position sizes (real data only)
    if is_real and vol > 2.0:
        adjustments["BASE_AMOUNT_EUR"] = {
            "direction": "decrease",
            "magnitude": 0.85,
            "reason": f"BTC volatility {vol:.1f}x elevated - reduce sizing",
        }
    elif is_real and vol < 0.6 and momentum > 0.01:
        adjustments["BASE_AMOUNT_EUR"] = {
            "direction": "increase",
            "magnitude": 1.1,
            "reason": "Low volatility + positive momentum - favorable conditions",
        }

    # Weekend adjustments
    if sentiment.get("weekend"):
        adjustments.setdefault(
            "BASE_AMOUNT_EUR", {"direction": "decrease", "magnitude": 0.85, "reason": "weekend - lower liquidity"}
        )

    return {
        "adjustments": adjustments,
        "sentiment_summary": sentiment,
        "data_quality": "real" if is_real else "simulated",
        "timestamp": time.time(),
    }


if __name__ == "__main__":
    # Test
    print("=== Sentiment Test ===")

    sentiment = get_market_sentiment("BTC-EUR")
    print(f"\nMarket Sentiment: {json.dumps(sentiment, indent=2)}")

    rec = get_trading_recommendation("BTC-EUR")
    print(f"\nTrading Recommendation: {json.dumps(rec, indent=2)}")

    adj = get_sentiment_adjustment("BTC-EUR")
    print(f"\nAI Adjustments: {json.dumps(adj, indent=2)}")
