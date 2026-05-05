# ai_indicator_correlation.py
"""
Technische Indicator Correlatie Analyse Module
Analyseert welke indicator combinaties het beste werken voor elke coin
"""

import json

# Project imports
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.json_compat import write_json_compat
from modules.logging_utils import log

# Data paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CORRELATION_FILE = PROJECT_ROOT / "data" / "indicator_correlations.json"
TRADE_LOG_FILE = PROJECT_ROOT / "data" / "trade_log.json"


def _load_correlations() -> dict:
    """Load correlation data from disk."""
    try:
        if CORRELATION_FILE.exists():
            with open(CORRELATION_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"coin_correlations": {}, "global_correlations": {}, "last_analysis": 0, "version": 1}


def _save_correlations(data: dict):
    """Save correlation data to disk."""
    try:
        CORRELATION_FILE.parent.mkdir(parents=True, exist_ok=True)
        write_json_compat(str(CORRELATION_FILE), data)
    except Exception as e:
        log(f"[INDICATOR] Correlation save error: {e}", level="warning")


def _load_trades() -> List[dict]:
    """Load closed trades from trade log."""
    try:
        if TRADE_LOG_FILE.exists():
            with open(TRADE_LOG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data.get("closed", [])
                return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def analyze_indicator_performance(trades: List[dict] = None) -> dict:
    """
    Analyze which indicators correlate with winning trades.

    Returns:
        dict with indicator performance statistics
    """
    if trades is None:
        trades = _load_trades()

    if len(trades) < 20:
        return {"error": "Need at least 20 trades for analysis"}

    # Indicator buckets
    indicators = {
        "rsi": {"ranges": [(0, 30), (30, 40), (40, 50), (50, 60), (60, 70), (70, 100)]},
        "score": {"ranges": [(0, 7), (7, 8), (8, 9), (9, 10), (10, 11), (11, 15)]},
        "volume": {"ranges": ["low", "medium", "high"]},
        "trend": {"values": ["bullish", "bearish", "neutral"]},
    }

    # Collect stats per indicator range
    stats = defaultdict(lambda: {"wins": 0, "losses": 0, "total_pnl": 0, "trades": []})

    for trade in trades:
        is_win = trade.get("profit", trade.get("pnl", 0)) > 0
        pnl = trade.get("profit", trade.get("pnl", 0))
        market = trade.get("market", "UNKNOWN")

        # RSI at entry
        rsi = trade.get("rsi_at_entry", trade.get("rsi", 50))
        if rsi is not None:
            for low, high in indicators["rsi"]["ranges"]:
                if low <= rsi < high:
                    key = f"rsi_{low}_{high}"
                    stats[key]["wins" if is_win else "losses"] += 1
                    stats[key]["total_pnl"] += pnl
                    stats[key]["trades"].append({"market": market, "pnl": pnl, "rsi": rsi})
                    break

        # Score at entry
        score = trade.get("score", trade.get("entry_score", 8))
        if score is not None:
            for low, high in indicators["score"]["ranges"]:
                if low <= score < high:
                    key = f"score_{low}_{high}"
                    stats[key]["wins" if is_win else "losses"] += 1
                    stats[key]["total_pnl"] += pnl
                    stats[key]["trades"].append({"market": market, "pnl": pnl, "score": score})
                    break

        # DCA count correlation
        dca_count = trade.get("dca_buys", trade.get("dca_count", 0))
        key = f"dca_{min(dca_count, 3)}"  # Group 3+ together
        stats[key]["wins" if is_win else "losses"] += 1
        stats[key]["total_pnl"] += pnl

        # Hold time correlation
        hold_time = trade.get("hold_time_hours", 0)
        if hold_time > 0:
            if hold_time < 1:
                time_bucket = "hold_under_1h"
            elif hold_time < 4:
                time_bucket = "hold_1_4h"
            elif hold_time < 24:
                time_bucket = "hold_4_24h"
            else:
                time_bucket = "hold_over_24h"

            stats[time_bucket]["wins" if is_win else "losses"] += 1
            stats[time_bucket]["total_pnl"] += pnl

    # Calculate win rates and rankings
    results = {}
    for key, data in stats.items():
        total = data["wins"] + data["losses"]
        if total >= 3:  # Minimum sample size
            results[key] = {
                "win_rate": round(data["wins"] / total, 3),
                "total_trades": total,
                "total_pnl": round(data["total_pnl"], 2),
                "avg_pnl": round(data["total_pnl"] / total, 2),
                "wins": data["wins"],
                "losses": data["losses"],
            }

    # Sort by win rate
    sorted_results = dict(sorted(results.items(), key=lambda x: x[1]["win_rate"], reverse=True))

    return {
        "indicators": sorted_results,
        "best_indicators": list(sorted_results.keys())[:5],
        "worst_indicators": list(sorted_results.keys())[-5:],
        "total_trades_analyzed": len(trades),
        "timestamp": time.time(),
    }


def analyze_coin_specific_patterns(trades: List[dict] = None) -> dict:
    """
    Analyze which indicator values work best for each specific coin.
    """
    if trades is None:
        trades = _load_trades()

    if len(trades) < 20:
        return {"error": "Need at least 20 trades for analysis"}

    # Group trades by coin
    coin_trades = defaultdict(list)
    for trade in trades:
        market = trade.get("market", "UNKNOWN")
        coin_trades[market].append(trade)

    coin_analysis = {}

    for market, market_trades in coin_trades.items():
        if len(market_trades) < 5:
            continue

        wins = [t for t in market_trades if t.get("profit", t.get("pnl", 0)) > 0]
        losses = [t for t in market_trades if t.get("profit", t.get("pnl", 0)) <= 0]

        # Calculate optimal RSI range for this coin
        winning_rsis = [t.get("rsi_at_entry", t.get("rsi", 50)) for t in wins if t.get("rsi_at_entry", t.get("rsi"))]
        losing_rsis = [t.get("rsi_at_entry", t.get("rsi", 50)) for t in losses if t.get("rsi_at_entry", t.get("rsi"))]

        # Calculate optimal score for this coin
        winning_scores = [t.get("score", t.get("entry_score", 8)) for t in wins if t.get("score", t.get("entry_score"))]
        losing_scores = [
            t.get("score", t.get("entry_score", 8)) for t in losses if t.get("score", t.get("entry_score"))
        ]

        analysis = {
            "total_trades": len(market_trades),
            "win_rate": round(len(wins) / len(market_trades), 3),
            "total_pnl": round(sum(t.get("profit", t.get("pnl", 0)) for t in market_trades), 2),
        }

        if winning_rsis:
            analysis["optimal_rsi"] = {
                "avg_winning": round(sum(winning_rsis) / len(winning_rsis), 1),
                "avg_losing": round(sum(losing_rsis) / len(losing_rsis), 1) if losing_rsis else None,
                "recommended_max": round(sum(winning_rsis) / len(winning_rsis) + 5, 0),
            }

        if winning_scores:
            analysis["optimal_score"] = {
                "avg_winning": round(sum(winning_scores) / len(winning_scores), 1),
                "avg_losing": round(sum(losing_scores) / len(losing_scores), 1) if losing_scores else None,
                "recommended_min": round(sum(winning_scores) / len(winning_scores) - 0.5, 1),
            }

        coin_analysis[market] = analysis

    # Sort by win rate
    sorted_coins = dict(sorted(coin_analysis.items(), key=lambda x: x[1]["win_rate"], reverse=True))

    return {
        "coin_patterns": sorted_coins,
        "best_performing": list(sorted_coins.keys())[:5],
        "worst_performing": list(sorted_coins.keys())[-5:],
        "timestamp": time.time(),
    }


def get_optimal_parameters_for_coin(market: str) -> dict:
    """
    Get recommended optimal parameters for a specific coin based on historical analysis.
    """
    correlations = _load_correlations()
    coin_data = correlations.get("coin_correlations", {}).get(market, {})

    if not coin_data or time.time() - coin_data.get("timestamp", 0) > 86400:  # Refresh if > 24h old
        # Run fresh analysis
        coin_patterns = analyze_coin_specific_patterns()
        if "error" not in coin_patterns:
            correlations["coin_correlations"] = coin_patterns.get("coin_patterns", {})
            correlations["last_analysis"] = time.time()
            _save_correlations(correlations)
            coin_data = correlations["coin_correlations"].get(market, {})

    if not coin_data:
        return {"error": f"No data available for {market}"}

    recommendations = {}

    # RSI recommendation
    if "optimal_rsi" in coin_data:
        rsi_data = coin_data["optimal_rsi"]
        if rsi_data.get("recommended_max"):
            recommendations["RSI_MAX_BUY"] = {
                "value": int(rsi_data["recommended_max"]),
                "reason": f"Historical winning trades avg RSI: {rsi_data['avg_winning']}",
            }

    # Score recommendation
    if "optimal_score" in coin_data:
        score_data = coin_data["optimal_score"]
        if score_data.get("recommended_min"):
            recommendations["MIN_SCORE_TO_BUY"] = {
                "value": score_data["recommended_min"],
                "reason": f"Historical winning trades avg score: {score_data['avg_winning']}",
            }

    return {
        "market": market,
        "win_rate": coin_data.get("win_rate", 0),
        "total_trades": coin_data.get("total_trades", 0),
        "recommendations": recommendations,
        "timestamp": time.time(),
    }


def calculate_indicator_weights() -> dict:
    """
    Calculate which indicators are most predictive of trade success.
    Returns weights that can be used to adjust trading score.
    """
    analysis = analyze_indicator_performance()

    if "error" in analysis:
        return analysis

    indicators = analysis.get("indicators", {})

    # Calculate weights based on win rate deviation from baseline
    baseline_wr = 0.5  # 50% baseline
    weights = {}

    for indicator, data in indicators.items():
        if data["total_trades"] >= 5:
            # Weight = how much better/worse than baseline
            deviation = data["win_rate"] - baseline_wr
            weights[indicator] = {
                "weight": round(deviation * 2, 3),  # Scale to -1 to 1
                "reliability": min(1.0, data["total_trades"] / 20),  # More trades = more reliable
                "win_rate": data["win_rate"],
                "sample_size": data["total_trades"],
            }

    # Sort by absolute weight (most impactful indicators)
    sorted_weights = dict(sorted(weights.items(), key=lambda x: abs(x[1]["weight"]), reverse=True))

    return {
        "indicator_weights": sorted_weights,
        "most_predictive": list(sorted_weights.keys())[:5],
        "timestamp": time.time(),
    }


def run_full_correlation_analysis() -> dict:
    """
    Run complete correlation analysis and save results.
    """
    log("[INDICATOR] Running full correlation analysis...", level="info")

    results = {
        "indicator_performance": analyze_indicator_performance(),
        "coin_patterns": analyze_coin_specific_patterns(),
        "indicator_weights": calculate_indicator_weights(),
        "analysis_time": time.time(),
    }

    # Save to correlations file
    correlations = _load_correlations()
    correlations["global_correlations"] = results.get("indicator_performance", {})
    correlations["coin_correlations"] = results.get("coin_patterns", {}).get("coin_patterns", {})
    correlations["indicator_weights"] = results.get("indicator_weights", {})
    correlations["last_analysis"] = time.time()
    _save_correlations(correlations)

    log(
        f"[INDICATOR] Analysis complete: {len(results.get('coin_patterns', {}).get('coin_patterns', {}))} coins analyzed",
        level="info",
    )

    return results


# Integration function for AI supervisor
def get_correlation_adjustments(market: str) -> dict:
    """
    Get correlation-based parameter adjustments for AI supervisor.
    """
    optimal = get_optimal_parameters_for_coin(market)

    if "error" in optimal:
        return {"adjustments": {}, "error": optimal["error"]}

    adjustments = {}

    for param, data in optimal.get("recommendations", {}).items():
        adjustments[param] = {
            "suggested_value": data["value"],
            "reason": data["reason"],
            "source": "indicator_correlation",
        }

    return {
        "market": market,
        "adjustments": adjustments,
        "confidence": min(1.0, optimal.get("total_trades", 0) / 20),
        "timestamp": time.time(),
    }


if __name__ == "__main__":
    print("=== Indicator Correlation Analysis ===\n")

    # Run full analysis
    results = run_full_correlation_analysis()

    print("\n--- Indicator Performance ---")
    if "error" not in results.get("indicator_performance", {}):
        for ind, data in list(results["indicator_performance"].get("indicators", {}).items())[:10]:
            print(f"  {ind}: WR={data['win_rate']:.1%}, trades={data['total_trades']}, PnL=€{data['total_pnl']:.2f}")

    print("\n--- Best Coins ---")
    if "error" not in results.get("coin_patterns", {}):
        for coin in results["coin_patterns"].get("best_performing", [])[:5]:
            data = results["coin_patterns"]["coin_patterns"].get(coin, {})
            print(f"  {coin}: WR={data.get('win_rate', 0):.1%}, PnL=€{data.get('total_pnl', 0):.2f}")

    print("\n--- Most Predictive Indicators ---")
    if "error" not in results.get("indicator_weights", {}):
        for ind in results["indicator_weights"].get("most_predictive", [])[:5]:
            data = results["indicator_weights"]["indicator_weights"].get(ind, {})
            print(f"  {ind}: weight={data.get('weight', 0):+.3f}, WR={data.get('win_rate', 0):.1%}")
