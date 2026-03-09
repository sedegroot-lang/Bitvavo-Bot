"""ai.market_analysis – Market regime detection, coin statistics, risk metrics, and market scanning.

Pure analysis functions with no side-effects. Takes data in, returns results.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List

from modules.logging_utils import log
from ai.ai_constants import SECTOR_DEFINITIONS


def _dbg(msg: str) -> None:
    """Debug-level log helper."""
    log(msg, level='debug')


# ---------------------------------------------------------------------------
# Sector helpers
# ---------------------------------------------------------------------------

def get_market_sector(market: str) -> str:
    """Returns the sector category for a given market."""
    for sector, markets in SECTOR_DEFINITIONS.items():
        if market in markets:
            return sector
    return "Other"


def calculate_portfolio_sectors(open_trades: dict) -> Dict[str, int]:
    """Returns a dict with count per sector in current portfolio."""
    sectors: Dict[str, int] = {}
    for market in open_trades:
        sector = get_market_sector(market)
        sectors[sector] = sectors.get(sector, 0) + 1
    return sectors


# ---------------------------------------------------------------------------
# Market regime detection
# ---------------------------------------------------------------------------

def _fetch_btc_candles_for_regime(interval: str = '1h', limit: int = 48) -> list:
    """Fetch BTC-EUR candles from Bitvavo for forward-looking regime detection."""
    try:
        from utils import get_bitvavo_client
        client = get_bitvavo_client()
        if client:
            candles = client.candles('BTC-EUR', interval, {'limit': limit})
            if isinstance(candles, list) and len(candles) >= 10:
                return candles
    except Exception as e:
        _dbg(f"BTC candle fetch for regime failed: {e}")
    return []


def detect_market_regime(closed_trades: list, cfg: dict) -> Dict[str, Any]:
    """Detect current market regime: BULL, BEAR, or SIDEWAYS.

    Uses a HYBRID approach:
    1. Forward-looking: BTC-EUR candle data (SMA, momentum, volatility)
    2. Backward-looking: recent trade performance (win rate, PnL trend)

    Forward data is weighted 60%, backward data 40%.
    Falls back to pure backward if candles unavailable.
    """
    # === FORWARD-LOOKING: BTC candle analysis ===
    btc_candles = _fetch_btc_candles_for_regime('1h', 48)
    forward_scores = {'BULL': 0.0, 'BEAR': 0.0, 'SIDEWAYS': 0.0}
    forward_indicators = {}
    has_forward = False

    if btc_candles and len(btc_candles) >= 15:
        has_forward = True
        closes = []
        for c in btc_candles:
            try:
                closes.append(float(c[4]) if len(c) > 4 else float(c[3]))
            except (IndexError, TypeError, ValueError):
                continue

        if len(closes) >= 15:
            # SMA crossover (short vs long)
            sma_short = sum(closes[-8:]) / 8
            sma_long = sum(closes[-24:]) / min(24, len(closes))
            sma_ratio = (sma_short - sma_long) / sma_long if sma_long > 0 else 0

            # Momentum (last 12h change)
            lookback = min(12, len(closes) - 1)
            momentum = (closes[-1] - closes[-lookback - 1]) / closes[-lookback - 1] if closes[-lookback - 1] > 0 else 0

            # Higher highs / lower lows
            hh_count = sum(1 for i in range(1, min(10, len(closes))) if closes[-i] > closes[-i - 1])
            ll_count = sum(1 for i in range(1, min(10, len(closes))) if closes[-i] < closes[-i - 1])

            # Volatility
            returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes)) if closes[i - 1] > 0]
            avg_ret = sum(returns) / len(returns) if returns else 0
            std_ret = (sum((r - avg_ret) ** 2 for r in returns) / len(returns)) ** 0.5 if returns else 0

            forward_indicators = {
                'sma_ratio': round(sma_ratio, 4),
                'momentum': round(momentum, 4),
                'higher_highs': hh_count,
                'lower_lows': ll_count,
                'volatility': round(std_ret * 100, 2),
                'btc_price': closes[-1],
            }

            # BULL signals
            if sma_ratio > 0.005:
                forward_scores['BULL'] += 0.3
            if momentum > 0.02:
                forward_scores['BULL'] += 0.3
            if hh_count >= 6:
                forward_scores['BULL'] += 0.2
            if avg_ret > 0.001:
                forward_scores['BULL'] += 0.2

            # BEAR signals
            if sma_ratio < -0.005:
                forward_scores['BEAR'] += 0.3
            if momentum < -0.02:
                forward_scores['BEAR'] += 0.3
            if ll_count >= 6:
                forward_scores['BEAR'] += 0.2
            if avg_ret < -0.001:
                forward_scores['BEAR'] += 0.2

            # SIDEWAYS signals
            if abs(sma_ratio) <= 0.005:
                forward_scores['SIDEWAYS'] += 0.3
            if abs(momentum) <= 0.01:
                forward_scores['SIDEWAYS'] += 0.2
            if std_ret > 0.015:
                forward_scores['SIDEWAYS'] += 0.3
            if 3 <= hh_count <= 6:
                forward_scores['SIDEWAYS'] += 0.2

    # === BACKWARD-LOOKING: trade history ===
    backward_scores = {'BULL': 0.0, 'BEAR': 0.0, 'SIDEWAYS': 0.0}
    backward_indicators = {}

    if len(closed_trades) >= 20:
        recent = closed_trades[-30:] if len(closed_trades) >= 30 else closed_trades

        if len(recent) >= 20:
            recent_10 = recent[-10:]
            prev_10 = recent[-20:-10]
            recent_wr = sum(1 for t in recent_10 if t.get("pnl", 0) > 0) / len(recent_10)
            prev_wr = sum(1 for t in prev_10 if t.get("pnl", 0) > 0) / len(prev_10)
            wr_trend = recent_wr - prev_wr
        else:
            recent_wr = sum(1 for t in recent if t.get("pnl", 0) > 0) / len(recent)
            wr_trend = 0

        wins = [t.get("pnl", 0) for t in recent if t.get("pnl", 0) > 0]
        losses = [abs(t.get("pnl", 0)) for t in recent if t.get("pnl", 0) < 0]
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        pnls = [t.get("pnl", 0) for t in recent]
        avg_pnl = sum(pnls) / len(pnls) if pnls else 0

        backward_indicators = {
            'win_rate': round(recent_wr, 3),
            'wr_trend': round(wr_trend, 3),
            'avg_pnl': round(avg_pnl, 2),
        }

        if recent_wr > 0.55:
            backward_scores['BULL'] += 0.3
        if wr_trend > 0.05:
            backward_scores['BULL'] += 0.2
        if avg_pnl > 1:
            backward_scores['BULL'] += 0.3

        if recent_wr < 0.45:
            backward_scores['BEAR'] += 0.3
        if wr_trend < -0.05:
            backward_scores['BEAR'] += 0.2
        if avg_pnl < -1:
            backward_scores['BEAR'] += 0.3

        if 0.45 <= recent_wr <= 0.55:
            backward_scores['SIDEWAYS'] += 0.3
        if abs(wr_trend) < 0.05:
            backward_scores['SIDEWAYS'] += 0.2
        if abs(avg_pnl) < 1:
            backward_scores['SIDEWAYS'] += 0.2
    elif len(closed_trades) < 20 and not has_forward:
        return {"regime": "SIDEWAYS", "confidence": 0.5, "indicators": {}, "source": "insufficient_data"}

    # === COMBINE: forward 60%, backward 40% (or 100% backward if no candles) ===
    if has_forward:
        fw = 0.60
        bw = 0.40
    else:
        fw = 0.0
        bw = 1.0

    combined = {}
    for regime in ('BULL', 'BEAR', 'SIDEWAYS'):
        combined[regime] = forward_scores.get(regime, 0) * fw + backward_scores.get(regime, 0) * bw

    regime = max(combined, key=combined.get)  # type: ignore[arg-type]
    confidence = combined[regime]

    indicators = {}
    indicators.update(backward_indicators)
    if forward_indicators:
        indicators['forward'] = forward_indicators

    return {
        "regime": regime,
        "confidence": round(min(1.0, confidence), 3),
        "indicators": indicators,
        "source": "hybrid" if has_forward else "trade_history",
        "forward_weight": fw,
    }


# ---------------------------------------------------------------------------
# Coin statistics
# ---------------------------------------------------------------------------

def get_coin_statistics(closed_trades: list) -> Dict[str, Any]:
    """Per-coin performance statistics."""
    coin_stats: Dict[str, Any] = {}
    for trade in closed_trades:
        market = trade.get("market", "UNKNOWN")
        pnl = trade.get("pnl", 0)
        if market not in coin_stats:
            coin_stats[market] = {"trades": 0, "wins": 0, "total_pnl": 0, "pnls": []}
        coin_stats[market]["trades"] += 1
        coin_stats[market]["total_pnl"] += pnl
        coin_stats[market]["pnls"].append(pnl)
        if pnl > 0:
            coin_stats[market]["wins"] += 1

    for stats in coin_stats.values():
        stats["win_rate"] = stats["wins"] / stats["trades"] if stats["trades"] > 0 else 0
        stats["avg_pnl"] = stats["total_pnl"] / stats["trades"] if stats["trades"] > 0 else 0

    return coin_stats


# ---------------------------------------------------------------------------
# Risk metrics
# ---------------------------------------------------------------------------

def calculate_risk_metrics(closed_trades: list, cfg: dict) -> Dict[str, Any]:
    """Advanced risk metrics: drawdown, consecutive losses, volatility."""
    if len(closed_trades) < 10:
        return {"risk_level": "LOW", "daily_drawdown": 0, "consecutive_losses": 0}

    recent = closed_trades[-20:]

    # Daily drawdown
    daily_trades = recent[-10:] if len(recent) >= 10 else recent
    daily_pnl = sum(t.get("pnl", 0) for t in daily_trades)

    # Consecutive losses
    consecutive = 0
    for trade in reversed(recent):
        if trade.get("pnl", 0) < 0:
            consecutive += 1
        else:
            break

    # Volatility
    pnls = [t.get("pnl", 0) for t in recent]
    avg_pnl = sum(pnls) / len(pnls)
    std_pnl = (sum((p - avg_pnl) ** 2 for p in pnls) / len(pnls)) ** 0.5
    volatility = std_pnl / abs(avg_pnl) if avg_pnl != 0 else 1.0

    risk_score = 0
    if daily_pnl < -10:
        risk_score += 2
    elif daily_pnl < -5:
        risk_score += 1
    if consecutive >= 3:
        risk_score += 2
    elif consecutive >= 2:
        risk_score += 1
    if volatility > 2.0:
        risk_score += 1

    if risk_score >= 3:
        risk_level = "HIGH"
    elif risk_score >= 1:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    return {
        "daily_drawdown": daily_pnl,
        "consecutive_losses": consecutive,
        "current_volatility": volatility,
        "risk_level": risk_level,
        "risk_score": risk_score,
    }


# ---------------------------------------------------------------------------
# Full market scanner
# ---------------------------------------------------------------------------

def scan_all_markets_for_opportunities(cfg: dict, closed_trades: list) -> Dict[str, Any]:
    """Scan ALL available Bitvavo EUR markets for trading opportunities."""
    all_markets: List[str] = []

    # Method 1: Try Bitvavo API
    try:
        from utils import get_bitvavo_client
        client = get_bitvavo_client()
        if client:
            markets_data = client.markets({})
            all_markets = [m["market"] for m in markets_data if m["market"].endswith("-EUR")]
            log(f"[MARKET-SCAN] Fetched {len(all_markets)} EUR markets from Bitvavo API", level="info")
    except Exception as e:
        _dbg(f"get_bitvavo_client failed: {e}")

    # Method 2: Fallback to top50 file
    if not all_markets:
        top50_file = os.path.join(os.path.dirname(__file__), "top50_eur_markets.json")
        try:
            with open(top50_file, "r") as f:
                all_markets = json.load(f)
            log(f"[MARKET-SCAN] Using top50 file: {len(all_markets)} markets", level="info")
        except Exception as e:
            _dbg(f"load failed: {e}")

    # Method 3: Ultimate fallback
    if not all_markets:
        all_markets = [
            "BTC-EUR", "ETH-EUR", "SOL-EUR", "BNB-EUR", "AVAX-EUR", "LINK-EUR",
            "MATIC-EUR", "ATOM-EUR", "DOT-EUR", "UNI-EUR", "AAVE-EUR", "ARB-EUR",
            "OP-EUR", "INJ-EUR", "SNX-EUR", "XRP-EUR", "LTC-EUR", "ALGO-EUR",
            "NEAR-EUR", "FTM-EUR", "GRT-EUR", "LDO-EUR", "GMX-EUR", "CRV-EUR", "MKR-EUR",
        ]
        log(f"[MARKET-SCAN] Using fallback list: {len(all_markets)} markets", level="warning")

    current_whitelist = cfg.get("WHITELIST_MARKETS", [])
    coin_stats = get_coin_statistics(closed_trades)

    # Poor performers to remove
    recommended_remove: List[Dict[str, Any]] = []
    for market in current_whitelist:
        if market in coin_stats:
            stats = coin_stats[market]
            if stats["trades"] >= 8 and stats["win_rate"] < 0.35 and stats["avg_pnl"] < -2:
                recommended_remove.append({
                    "market": market,
                    "reason": f"Poor performer: WR={stats['win_rate']:.0%}, avg PnL=€{stats['avg_pnl']:.1f}",
                    "win_rate": stats["win_rate"],
                    "avg_pnl": stats["avg_pnl"],
                    "trades": stats["trades"],
                })

    # Markets to potentially add
    available_markets = [m for m in all_markets if m not in current_whitelist]

    layer1_markets = [
        "XRP-EUR", "ADA-EUR", "LTC-EUR", "ALGO-EUR", "NEAR-EUR", "FTM-EUR",
        "EGLD-EUR", "FLOW-EUR", "TRX-EUR", "XTZ-EUR", "EOS-EUR",
    ]
    defi_markets = [
        "LDO-EUR", "GMX-EUR", "CRV-EUR", "MKR-EUR", "1INCH-EUR", "COMP-EUR",
        "YFI-EUR", "BAL-EUR", "SUSHI-EUR", "CAKE-EUR",
    ]
    layer2_markets = ["IMX-EUR", "LRC-EUR", "METIS-EUR"]

    priority_markets: Dict[str, Dict[str, str]] = {}
    for market in layer1_markets:
        if market in available_markets:
            priority_markets[market] = {
                "reason": f"{market.split('-')[0]} - Established Layer 1 blockchain",
                "priority": "HIGH",
                "category": "Layer1",
            }
    for market in defi_markets:
        if market in available_markets:
            priority_markets[market] = {
                "reason": f"{market.split('-')[0]} - DeFi protocol",
                "priority": "HIGH" if market in ["LDO-EUR", "GMX-EUR", "CRV-EUR", "MKR-EUR"] else "MEDIUM",
                "category": "DeFi",
            }
    for market in layer2_markets:
        if market in available_markets:
            priority_markets[market] = {
                "reason": f"{market.split('-')[0]} - Layer 2 scaling solution",
                "priority": "MEDIUM",
                "category": "Layer2",
            }

    unexplored = [m for m in available_markets if m not in coin_stats]
    for market in unexplored[:10]:
        if market not in priority_markets and market in all_markets:
            priority_markets[market] = {
                "reason": f"{market.split('-')[0]} - Unexplored market, worth testing",
                "priority": "LOW",
                "category": "Unexplored",
            }

    recommended_add: List[Dict[str, Any]] = []
    for market, info in priority_markets.items():
        recommended_add.append({
            "market": market,
            "reason": info["reason"],
            "priority": info["priority"],
            "category": info["category"],
        })

    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    recommended_add.sort(key=lambda x: priority_order.get(x["priority"], 3))

    # Annotate guardrail data
    try:
        from modules.ai_markets import evaluate_market_guardrails
        for rec in recommended_add:
            eval_result = evaluate_market_guardrails(rec["market"], cfg)
            rec["risk_score"] = eval_result.get("risk_score")
            rec["guardrail_ok"] = eval_result.get("ok")
    except Exception as e:
        _dbg(f"evaluate_market_guardrails failed: {e}")

    log(
        f"[MARKET-SCAN] Total markets scanned: {len(all_markets)}, "
        f"Available to add: {len(available_markets)}, "
        f"Recommended add: {len(recommended_add)}, "
        f"Recommended remove: {len(recommended_remove)}",
        level="info",
    )

    return {
        "total_markets_scanned": len(all_markets),
        "available_markets": len(available_markets),
        "recommended_add": recommended_add,
        "recommended_remove": recommended_remove,
        "scan_time": time.time(),
    }
