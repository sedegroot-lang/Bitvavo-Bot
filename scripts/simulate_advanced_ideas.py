"""
Advanced Ideas Simulator — Backtests all 20+ ultra-advanced trading concepts
against historical trade data and synthetic price series.

Simulates each idea independently and measures incremental value vs baseline.
Uses real trade archive + synthetic GBM data for comprehensive testing.

Usage:
    python scripts/simulate_advanced_ideas.py
"""

from __future__ import annotations

import json
import math
import os
import random
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_CONFIG_PATH = PROJECT_ROOT / "config" / "bot_config.json"
try:
    with open(_CONFIG_PATH, encoding="utf-8") as _f:
        CONFIG: Dict[str, Any] = json.load(_f)
except Exception:
    CONFIG = {}

MIN_SCORE = float(CONFIG.get("MIN_SCORE_TO_BUY", 7.0))
BASE_EUR = float(CONFIG.get("BASE_AMOUNT_EUR", 38.0))
FEE_TAKER = float(CONFIG.get("FEE_TAKER", 0.0025))
TRAIL_PCT = float(CONFIG.get("DEFAULT_TRAILING", 0.025))
TRAIL_ACT = float(CONFIG.get("TRAILING_ACTIVATION_PCT", 0.015))
HARD_SL = float(CONFIG.get("HARD_SL_ALT_PCT", 0.25))

# ---------------------------------------------------------------------------
# Load real trade data
# ---------------------------------------------------------------------------

def load_archive_trades() -> List[Dict[str, Any]]:
    """Load closed trades from archive."""
    path = PROJECT_ROOT / "data" / "trade_archive.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "trades" in data:
        return data["trades"]
    return data if isinstance(data, list) else []


def load_pnl_history() -> List[Dict[str, Any]]:
    """Load PnL history from JSONL."""
    path = PROJECT_ROOT / "data" / "trade_pnl_history.jsonl"
    if not path.exists():
        return []
    trades = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    trades.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    pass
    return trades


# ---------------------------------------------------------------------------
# Synthetic price generation (GBM with regime switches)
# ---------------------------------------------------------------------------

def generate_multi_regime_prices(
    n: int = 10000,
    start: float = 100.0,
    seed: int = 42,
) -> Tuple[List[float], List[float], List[float], List[float], List[str]]:
    """Generate OHLCV-like data with regime switches.
    Returns: (closes, highs, lows, volumes, regimes)
    """
    rng = random.Random(seed)
    closes, highs, lows, volumes, regimes = [], [], [], [], []
    price = start

    regime_defs = {
        "trending_up": (0.002, 0.012),
        "ranging": (0.0, 0.008),
        "high_volatility": (0.0, 0.025),
        "bearish": (-0.002, 0.015),
    }
    regime_names = list(regime_defs.keys())
    current_regime = "trending_up"
    regime_length = rng.randint(200, 600)
    regime_counter = 0

    for i in range(n):
        if regime_counter >= regime_length:
            current_regime = rng.choice(regime_names)
            regime_length = rng.randint(200, 600)
            regime_counter = 0

        drift, vol = regime_defs[current_regime]
        ret = rng.gauss(drift, vol)
        if rng.random() < 0.02:
            ret *= 3.0

        close = max(0.01, price * (1 + ret))
        high = close * (1 + abs(rng.gauss(0, vol * 0.5)))
        low = close * (1 - abs(rng.gauss(0, vol * 0.5)))
        low = max(0.001, low)
        base_vol = rng.lognormvariate(8, 1)
        if abs(ret) > vol * 2:
            base_vol *= rng.uniform(2, 5)

        closes.append(close)
        highs.append(high)
        lows.append(low)
        volumes.append(base_vol)
        regimes.append(current_regime)

        price = close
        regime_counter += 1

    return closes, highs, lows, volumes, regimes


# ---------------------------------------------------------------------------
# Indicator helpers
# ---------------------------------------------------------------------------

def sma(vals: List[float], window: int) -> List[float]:
    result = [float("nan")] * len(vals)
    for i in range(window - 1, len(vals)):
        result[i] = sum(vals[i - window + 1: i + 1]) / window
    return result


def ema(vals: List[float], window: int) -> List[float]:
    result = [float("nan")] * len(vals)
    if len(vals) < window:
        return result
    k = 2.0 / (window + 1)
    result[window - 1] = sum(vals[:window]) / window
    for i in range(window, len(vals)):
        result[i] = vals[i] * k + result[i - 1] * (1 - k)
    return result


def rsi(vals: List[float], period: int = 14) -> List[float]:
    result = [float("nan")] * len(vals)
    if len(vals) < period + 1:
        return result
    gains, losses_l = [], []
    for i in range(1, len(vals)):
        d = vals[i] - vals[i - 1]
        gains.append(max(d, 0))
        losses_l.append(max(-d, 0))
    ag = sum(gains[:period]) / period
    al = sum(losses_l[:period]) / period
    for i in range(period, len(vals) - 1):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses_l[i]) / period
        rs = ag / al if al > 1e-9 else 1e9
        result[i + 1] = 100 - (100 / (1 + rs))
    return result


def bollinger_bands(vals: List[float], window: int = 20, num_std: float = 2.0):
    upper, mid, lower = [float("nan")] * len(vals), [float("nan")] * len(vals), [float("nan")] * len(vals)
    for i in range(window - 1, len(vals)):
        w = vals[i - window + 1: i + 1]
        m = sum(w) / window
        std = (sum((x - m) ** 2 for x in w) / window) ** 0.5
        mid[i] = m
        upper[i] = m + num_std * std
        lower[i] = m - num_std * std
    return upper, mid, lower


def atr(highs: List[float], lows: List[float], closes: List[float], window: int = 14) -> List[float]:
    result = [float("nan")] * len(closes)
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    if len(trs) < window:
        return result
    avg = sum(trs[:window]) / window
    result[window] = avg
    for i in range(window, len(trs)):
        avg = (avg * (window - 1) + trs[i]) / window
        result[i + 1] = avg
    return result


# ---------------------------------------------------------------------------
# IDEA SIMULATORS
# Each returns: dict with { "trades": int, "wins": int, "total_pnl": float,
#                           "filtered_bad": int, "filtered_good": int,
#                           "description": str }
# ---------------------------------------------------------------------------

def _safe(v):
    return v if not math.isnan(v) else None


# ---- IDEA 1: Transfer Entropy (simplified cross-asset lead-lag) ----
def simulate_transfer_entropy(
    prices_a: List[float], prices_b: List[float], regimes: List[str]
) -> Dict[str, Any]:
    """Simulates lead-lag trading: when asset A moves, buy asset B before it follows."""
    trades, wins, total_pnl = 0, 0, 0.0
    lookback = 20

    for i in range(lookback + 5, len(prices_a) - 10):
        # Measure if A leads B: compute lagged correlation
        rets_a = [prices_a[j] / prices_a[j - 1] - 1 for j in range(i - lookback, i)]
        rets_b = [prices_b[j] / prices_b[j - 1] - 1 for j in range(i - lookback + 1, i + 1)]

        if len(rets_a) != len(rets_b):
            continue

        # Simple cross-correlation at lag 1
        mean_a = sum(rets_a) / len(rets_a)
        mean_b = sum(rets_b) / len(rets_b)
        cov = sum((a - mean_a) * (b - mean_b) for a, b in zip(rets_a, rets_b)) / len(rets_a)
        std_a = (sum((a - mean_a) ** 2 for a in rets_a) / len(rets_a)) ** 0.5
        std_b = (sum((b - mean_b) ** 2 for b in rets_b) / len(rets_b)) ** 0.5
        if std_a < 1e-9 or std_b < 1e-9:
            continue
        lag_corr = cov / (std_a * std_b)

        # If A strongly leads B and A just moved up → buy B
        if lag_corr > 0.3 and rets_a[-1] > 0.005:
            entry = prices_b[i]
            # Hold for 5 bars
            exit_price = prices_b[min(i + 5, len(prices_b) - 1)]
            pnl = (exit_price / entry - 1) * BASE_EUR - 2 * FEE_TAKER * BASE_EUR
            trades += 1
            total_pnl += pnl
            if pnl > 0:
                wins += 1

    return {
        "name": "Transfer Entropy (Lead-Lag)",
        "trades": trades,
        "wins": wins,
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(wins / max(trades, 1) * 100, 1),
        "avg_pnl": round(total_pnl / max(trades, 1), 4),
    }


# ---- IDEA 2: Hurst Exponent Regime Switch ----
def _hurst(prices: List[float], window: int = 100) -> float:
    """Simplified Hurst exponent via R/S analysis."""
    if len(prices) < window:
        return 0.5
    rets = [prices[i] / prices[i - 1] - 1 for i in range(1, len(prices))]
    rets = rets[-window:]
    mean_r = sum(rets) / len(rets)
    dev = [r - mean_r for r in rets]
    cum = []
    s = 0
    for d in dev:
        s += d
        cum.append(s)
    R = max(cum) - min(cum)
    S = (sum((r - mean_r) ** 2 for r in rets) / len(rets)) ** 0.5
    if S < 1e-10:
        return 0.5
    RS = R / S
    if RS <= 0:
        return 0.5
    H = math.log(RS) / math.log(window)
    return max(0.0, min(1.0, H))


def simulate_hurst_regime(closes: List[float], regimes: List[str]) -> Dict[str, Any]:
    """Use Hurst exponent to decide strategy: trend-follow if H>0.55, mean-revert if H<0.45."""
    trades, wins, total_pnl = 0, 0, 0.0
    filtered_bad = 0

    for i in range(200, len(closes) - 10, 5):
        H = _hurst(closes[:i + 1])

        if H > 0.55:
            # Trend following: buy if uptrend, hold 10 bars
            if closes[i] > closes[i - 5]:
                entry = closes[i]
                exit_p = closes[min(i + 10, len(closes) - 1)]
                pnl = (exit_p / entry - 1) * BASE_EUR - 2 * FEE_TAKER * BASE_EUR
                trades += 1
                total_pnl += pnl
                if pnl > 0:
                    wins += 1
        elif H < 0.45:
            # Mean reversion: buy if below SMA, hold 5 bars
            s = sum(closes[i - 20:i]) / 20
            if closes[i] < s * 0.99:
                entry = closes[i]
                exit_p = closes[min(i + 5, len(closes) - 1)]
                pnl = (exit_p / entry - 1) * BASE_EUR - 2 * FEE_TAKER * BASE_EUR
                trades += 1
                total_pnl += pnl
                if pnl > 0:
                    wins += 1
        else:
            filtered_bad += 1  # H ≈ 0.5, random walk → skip

    return {
        "name": "Hurst Exponent Regime",
        "trades": trades,
        "wins": wins,
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(wins / max(trades, 1) * 100, 1),
        "filtered_random_walk": filtered_bad,
        "avg_pnl": round(total_pnl / max(trades, 1), 4),
    }


# ---- IDEA 3: Shannon Entropy Gate ----
def _shannon_entropy(returns: List[float], bins: int = 20) -> float:
    """Shannon entropy of return distribution."""
    if len(returns) < 10:
        return 0.0
    mn, mx = min(returns), max(returns)
    if mx - mn < 1e-10:
        return 0.0
    bin_width = (mx - mn) / bins
    counts = [0] * bins
    for r in returns:
        idx = min(int((r - mn) / bin_width), bins - 1)
        counts[idx] += 1
    total = len(returns)
    entropy = 0.0
    for c in counts:
        if c > 0:
            p = c / total
            entropy -= p * math.log2(p)
    return entropy


def simulate_shannon_entropy_gate(closes: List[float], regimes: List[str]) -> Dict[str, Any]:
    """Gate trades by entropy: low entropy = predictable → trade. High = chaos → skip."""
    # Baseline: trade at every score opportunity
    # Filtered: skip when entropy is too high
    baseline_trades, baseline_wins, baseline_pnl = 0, 0, 0.0
    filtered_trades, filtered_wins, filtered_pnl = 0, 0, 0.0
    skipped_good, skipped_bad = 0, 0

    sma_7 = sma(closes, 7)
    sma_25 = sma(closes, 25)
    rsi_vals = rsi(closes)

    for i in range(100, len(closes) - 10, 3):
        # Simple score
        score = 0.0
        if not math.isnan(sma_7[i]) and not math.isnan(sma_25[i]):
            if sma_7[i] > sma_25[i]:
                score += 3.0
        if not math.isnan(rsi_vals[i]) and 35 <= rsi_vals[i] <= 65:
            score += 2.0

        if score < 3.0:
            continue

        entry = closes[i]
        exit_p = closes[min(i + 8, len(closes) - 1)]
        pnl = (exit_p / entry - 1) * BASE_EUR - 2 * FEE_TAKER * BASE_EUR

        baseline_trades += 1
        baseline_pnl += pnl
        if pnl > 0:
            baseline_wins += 1

        # Entropy filter
        rets = [closes[j] / closes[j - 1] - 1 for j in range(max(1, i - 60), i)]
        entropy = _shannon_entropy(rets)
        max_entropy = math.log2(20)  # max for 20 bins

        if entropy < max_entropy * 0.7:  # Low entropy = predictable
            filtered_trades += 1
            filtered_pnl += pnl
            if pnl > 0:
                filtered_wins += 1
        else:
            if pnl > 0:
                skipped_good += 1
            else:
                skipped_bad += 1

    return {
        "name": "Shannon Entropy Gate",
        "baseline_trades": baseline_trades,
        "baseline_winrate": round(baseline_wins / max(baseline_trades, 1) * 100, 1),
        "baseline_pnl": round(baseline_pnl, 2),
        "filtered_trades": filtered_trades,
        "filtered_winrate": round(filtered_wins / max(filtered_trades, 1) * 100, 1),
        "filtered_pnl": round(filtered_pnl, 2),
        "improvement_pnl": round(filtered_pnl - baseline_pnl, 2),
        "skipped_bad_trades": skipped_bad,
        "skipped_good_trades": skipped_good,
        "net_filter_value": skipped_bad - skipped_good,
    }


# ---- IDEA 4: Bayesian Signal Fusion (online weight updating) ----
def simulate_bayesian_fusion(closes: List[float], regimes: List[str]) -> Dict[str, Any]:
    """Dynamically weight signals based on recent performance using Bayesian updating."""
    sma_7 = sma(closes, 7)
    sma_25 = sma(closes, 25)
    rsi_vals = rsi(closes)
    bb_up, bb_mid, bb_low = bollinger_bands(closes)

    # Signal weights (start equal)
    weights = {"sma_cross": 1.0, "rsi_zone": 1.0, "bb_bounce": 1.0}
    alpha = 0.1  # learning rate

    static_trades, static_wins, static_pnl = 0, 0, 0.0
    adaptive_trades, adaptive_wins, adaptive_pnl = 0, 0, 0.0

    trade_history = []  # (signal_name, pnl) tuples

    for i in range(100, len(closes) - 10, 3):
        signals = {}
        if not math.isnan(sma_7[i]) and not math.isnan(sma_25[i]):
            signals["sma_cross"] = 1.0 if sma_7[i] > sma_25[i] else 0.0
        if not math.isnan(rsi_vals[i]):
            signals["rsi_zone"] = 1.0 if 30 <= rsi_vals[i] <= 60 else 0.0
        if not math.isnan(bb_low[i]):
            signals["bb_bounce"] = 1.0 if closes[i] < bb_low[i] * 1.02 else 0.0

        # Static score
        static_score = sum(signals.values())
        # Weighted score
        weighted_score = sum(signals.get(k, 0) * weights[k] for k in weights)

        entry = closes[i]
        exit_p = closes[min(i + 8, len(closes) - 1)]
        pnl = (exit_p / entry - 1) * BASE_EUR - 2 * FEE_TAKER * BASE_EUR

        # Static: trade if score >= 2
        if static_score >= 2.0:
            static_trades += 1
            static_pnl += pnl
            if pnl > 0:
                static_wins += 1

        # Adaptive: trade if weighted score >= adaptive threshold
        w_total = sum(weights.values())
        threshold = w_total * 0.6
        if weighted_score >= threshold:
            adaptive_trades += 1
            adaptive_pnl += pnl
            if pnl > 0:
                adaptive_wins += 1

        # Update weights based on outcome
        for sig_name, sig_val in signals.items():
            if sig_val > 0.5:
                # Signal was active → update weight based on trade outcome
                if pnl > 0:
                    weights[sig_name] = min(3.0, weights[sig_name] + alpha)
                else:
                    weights[sig_name] = max(0.1, weights[sig_name] - alpha * 0.5)

    return {
        "name": "Bayesian Signal Fusion",
        "static_trades": static_trades,
        "static_winrate": round(static_wins / max(static_trades, 1) * 100, 1),
        "static_pnl": round(static_pnl, 2),
        "adaptive_trades": adaptive_trades,
        "adaptive_winrate": round(adaptive_wins / max(adaptive_trades, 1) * 100, 1),
        "adaptive_pnl": round(adaptive_pnl, 2),
        "improvement_pnl": round(adaptive_pnl - static_pnl, 2),
        "final_weights": {k: round(v, 3) for k, v in weights.items()},
    }


# ---- IDEA 5: Adversarial Stop-Loss Placement ----
def simulate_adversarial_stops(closes: List[float], highs: List[float], lows: List[float]) -> Dict[str, Any]:
    """Compare standard stop-loss placement vs adversarial (offset from common levels)."""
    standard_stopped, adversarial_stopped = 0, 0
    standard_pnl, adversarial_pnl = 0.0, 0.0
    trades = 0

    for i in range(50, len(closes) - 20, 10):
        entry = closes[i]
        standard_sl = entry * (1 - 0.025)  # standard 2.5% SL

        # Adversarial: find nearest round number and common SMA, offset past it
        round_levels = [round(entry * (1 - 0.02), 1), round(entry * (1 - 0.03), 1)]
        # Offset SL below the cluster of common levels
        adversarial_sl = min(round_levels) * 0.997  # 0.3% below round number cluster

        # Simulate price path
        std_stopped = False
        adv_stopped = False
        std_exit = entry
        adv_exit = entry

        for j in range(i + 1, min(i + 20, len(closes))):
            if not std_stopped and lows[j] <= standard_sl:
                std_stopped = True
                std_exit = standard_sl
            if not adv_stopped and lows[j] <= adversarial_sl:
                adv_stopped = True
                adv_exit = adversarial_sl

        if not std_stopped:
            std_exit = closes[min(i + 20, len(closes) - 1)]
        if not adv_stopped:
            adv_exit = closes[min(i + 20, len(closes) - 1)]

        trades += 1
        s_pnl = (std_exit / entry - 1) * BASE_EUR
        a_pnl = (adv_exit / entry - 1) * BASE_EUR
        standard_pnl += s_pnl
        adversarial_pnl += a_pnl
        if std_stopped:
            standard_stopped += 1
        if adv_stopped:
            adversarial_stopped += 1

    return {
        "name": "Adversarial Stop-Loss",
        "trades": trades,
        "standard_stopped": standard_stopped,
        "adversarial_stopped": adversarial_stopped,
        "stops_avoided": standard_stopped - adversarial_stopped,
        "standard_pnl": round(standard_pnl, 2),
        "adversarial_pnl": round(adversarial_pnl, 2),
        "improvement_pnl": round(adversarial_pnl - standard_pnl, 2),
    }


# ---- IDEA 6: Volatility Term Structure ----
def simulate_vol_term_structure(
    closes: List[float], highs: List[float], lows: List[float], regimes: List[str]
) -> Dict[str, Any]:
    """Use short-term vs long-term volatility ratio to predict breakouts/mean-reversion."""
    trades, wins, total_pnl = 0, 0, 0.0
    atr_short = atr(highs, lows, closes, 5)
    atr_long = atr(highs, lows, closes, 50)

    for i in range(60, len(closes) - 10, 5):
        if math.isnan(atr_short[i]) or math.isnan(atr_long[i]) or atr_long[i] < 1e-9:
            continue
        vol_ratio = atr_short[i] / atr_long[i]

        if vol_ratio < 0.5:
            # Calm before storm → breakout expected, larger position
            entry = closes[i]
            exit_p = closes[min(i + 10, len(closes) - 1)]
            pnl = (exit_p / entry - 1) * BASE_EUR * 1.5 - 2 * FEE_TAKER * BASE_EUR * 1.5
            trades += 1
            total_pnl += pnl
            if pnl > 0:
                wins += 1
        elif vol_ratio > 2.0:
            # Micro-spike → mean reversion
            s = sum(closes[i - 10:i]) / 10
            if closes[i] < s:
                entry = closes[i]
                exit_p = closes[min(i + 5, len(closes) - 1)]
                pnl = (exit_p / entry - 1) * BASE_EUR - 2 * FEE_TAKER * BASE_EUR
                trades += 1
                total_pnl += pnl
                if pnl > 0:
                    wins += 1

    return {
        "name": "Volatility Term Structure",
        "trades": trades,
        "wins": wins,
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(wins / max(trades, 1) * 100, 1),
        "avg_pnl": round(total_pnl / max(trades, 1), 4),
    }


# ---- IDEA 7: Trade DNA Fingerprinting ----
def simulate_trade_dna(closes: List[float], regimes: List[str]) -> Dict[str, Any]:
    """Cluster trade setups into DNA profiles and match new setups to best clusters."""
    sma_7 = sma(closes, 7)
    sma_25 = sma(closes, 25)
    rsi_vals = rsi(closes)
    bb_up, bb_mid, bb_low = bollinger_bands(closes)

    # Phase 1: Build DNA database from first 60% of data
    split = int(len(closes) * 0.6)
    dna_db: List[Tuple[List[float], float]] = []  # (feature_vector, pnl)

    for i in range(100, split - 10, 3):
        if any(math.isnan(v[i]) for v in [sma_7, sma_25, rsi_vals, bb_up, bb_low]):
            continue

        rel_sma = (sma_7[i] - sma_25[i]) / closes[i]
        rel_bb = (closes[i] - bb_low[i]) / max(bb_up[i] - bb_low[i], 1e-9)
        rets_5 = (closes[i] - closes[i - 5]) / closes[i - 5]
        features = [rel_sma, rsi_vals[i] / 100, rel_bb, rets_5]

        entry = closes[i]
        exit_p = closes[min(i + 8, len(closes) - 1)]
        pnl = (exit_p / entry - 1) * BASE_EUR - 2 * FEE_TAKER * BASE_EUR
        dna_db.append((features, pnl))

    # Phase 2: Use DNA matching on remaining 40%
    baseline_trades, baseline_pnl, baseline_wins = 0, 0.0, 0
    dna_trades, dna_pnl, dna_wins = 0, 0.0, 0

    def _euclidean(a, b):
        return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5

    for i in range(split, len(closes) - 10, 3):
        if any(math.isnan(v[i]) for v in [sma_7, sma_25, rsi_vals, bb_up, bb_low]):
            continue

        rel_sma = (sma_7[i] - sma_25[i]) / closes[i]
        rel_bb = (closes[i] - bb_low[i]) / max(bb_up[i] - bb_low[i], 1e-9)
        rets_5 = (closes[i] - closes[i - 5]) / closes[i - 5]
        features = [rel_sma, rsi_vals[i] / 100, rel_bb, rets_5]

        entry = closes[i]
        exit_p = closes[min(i + 8, len(closes) - 1)]
        pnl = (exit_p / entry - 1) * BASE_EUR - 2 * FEE_TAKER * BASE_EUR

        baseline_trades += 1
        baseline_pnl += pnl
        if pnl > 0:
            baseline_wins += 1

        # Find K nearest neighbors in DNA db
        K = 10
        dists = [(d, _euclidean(features, db_f)) for db_f, d in dna_db]
        dists.sort(key=lambda x: x[1])
        neighbors = dists[:K]
        avg_neighbor_pnl = sum(p for p, _ in neighbors) / K if neighbors else 0

        # Only trade if similar historical setups were profitable
        if avg_neighbor_pnl > 0:
            dna_trades += 1
            dna_pnl += pnl
            if pnl > 0:
                dna_wins += 1

    return {
        "name": "Trade DNA Fingerprinting",
        "baseline_trades": baseline_trades,
        "baseline_winrate": round(baseline_wins / max(baseline_trades, 1) * 100, 1),
        "baseline_pnl": round(baseline_pnl, 2),
        "dna_trades": dna_trades,
        "dna_winrate": round(dna_wins / max(dna_trades, 1) * 100, 1),
        "dna_pnl": round(dna_pnl, 2),
        "improvement_pnl": round(dna_pnl - baseline_pnl, 2),
    }


# ---- IDEA 8: Time-of-Day Seasonality ----
def simulate_time_of_day(closes: List[float], regimes: List[str]) -> Dict[str, Any]:
    """Simulate 1-minute candles mapped to 24hr cycle, measure hourly returns."""
    # Map index to hour-of-day (simulate 1440 candles = 1 day)
    hourly_returns: Dict[int, List[float]] = defaultdict(list)

    for i in range(1, len(closes)):
        hour = (i % 1440) // 60  # minute-to-hour mapping
        ret = closes[i] / closes[i - 1] - 1
        hourly_returns[hour].append(ret)

    # Find best and worst hours
    hour_stats = {}
    for h, rets in hourly_returns.items():
        hour_stats[h] = {
            "mean": sum(rets) / len(rets),
            "std": (sum((r - sum(rets) / len(rets)) ** 2 for r in rets) / len(rets)) ** 0.5,
            "count": len(rets),
        }

    good_hours = [h for h, s in hour_stats.items() if s["mean"] > 0.0001]
    bad_hours = [h for h, s in hour_stats.items() if s["mean"] < -0.0001]

    # Simulate: only trade during good hours
    baseline_trades, baseline_pnl = 0, 0.0
    filtered_trades, filtered_pnl = 0, 0.0

    sma_7_v = sma(closes, 7)
    sma_25_v = sma(closes, 25)

    for i in range(100, len(closes) - 10, 5):
        if math.isnan(sma_7_v[i]) or math.isnan(sma_25_v[i]):
            continue
        if sma_7_v[i] <= sma_25_v[i]:
            continue

        entry = closes[i]
        exit_p = closes[min(i + 8, len(closes) - 1)]
        pnl = (exit_p / entry - 1) * BASE_EUR - 2 * FEE_TAKER * BASE_EUR

        baseline_trades += 1
        baseline_pnl += pnl

        hour = (i % 1440) // 60
        if hour in good_hours:
            filtered_trades += 1
            filtered_pnl += pnl

    return {
        "name": "Time-of-Day Seasonality",
        "good_hours": sorted(good_hours),
        "bad_hours": sorted(bad_hours),
        "baseline_trades": baseline_trades,
        "baseline_pnl": round(baseline_pnl, 2),
        "filtered_trades": filtered_trades,
        "filtered_pnl": round(filtered_pnl, 2),
        "improvement_pnl": round(filtered_pnl - baseline_pnl, 2),
    }


# ---- IDEA 9: Regime Transition Markov Chain ----
def simulate_markov_regime(closes: List[float], regimes: List[str]) -> Dict[str, Any]:
    """Build transition matrix from regimes and anticipate regime changes."""
    # Build transition matrix
    transitions: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for i in range(1, len(regimes)):
        transitions[regimes[i - 1]][regimes[i]] += 1

    # Normalize to probabilities
    trans_probs: Dict[str, Dict[str, float]] = {}
    for from_r, to_dict in transitions.items():
        total = sum(to_dict.values())
        trans_probs[from_r] = {to_r: c / total for to_r, c in to_dict.items()}

    # Simulate: anticipate favorable transitions
    trades, wins, total_pnl = 0, 0, 0.0
    anticipation_trades, ant_wins, ant_pnl = 0, 0, 0.0

    for i in range(100, len(closes) - 10, 5):
        current = regimes[i]
        probs = trans_probs.get(current, {})

        # Baseline: always trade in trending_up
        if current == "trending_up":
            entry = closes[i]
            exit_p = closes[min(i + 8, len(closes) - 1)]
            pnl = (exit_p / entry - 1) * BASE_EUR - 2 * FEE_TAKER * BASE_EUR
            trades += 1
            total_pnl += pnl
            if pnl > 0:
                wins += 1

        # Anticipation: also trade when ranging has high chance of transitioning to trending
        if current == "ranging" and probs.get("trending_up", 0) > 0.15:
            # Pre-position for trend
            entry = closes[i]
            exit_p = closes[min(i + 10, len(closes) - 1)]
            pnl = (exit_p / entry - 1) * BASE_EUR * 0.5 - 2 * FEE_TAKER * BASE_EUR * 0.5
            anticipation_trades += 1
            ant_pnl += pnl
            if pnl > 0:
                ant_wins += 1

    return {
        "name": "Markov Regime Anticipation",
        "transition_matrix": {k: {k2: round(v2, 3) for k2, v2 in v.items()} for k, v in trans_probs.items()},
        "baseline_trades": trades,
        "baseline_pnl": round(total_pnl, 2),
        "anticipation_trades": anticipation_trades,
        "anticipation_pnl": round(ant_pnl, 2),
        "combined_pnl": round(total_pnl + ant_pnl, 2),
    }


# ---- IDEA 10-11: Liquidity-Weighted & Anticipatory DCA ----
def simulate_smart_dca(closes: List[float], regimes: List[str]) -> Dict[str, Any]:
    """Compare standard DCA vs volatility-aware DCA timing."""
    # Simulate a trade that needs DCA
    bb_up, bb_mid, bb_low = bollinger_bands(closes)

    standard_dca_pnl = 0.0
    smart_dca_pnl = 0.0
    std_count = 0
    smart_count = 0

    for i in range(100, len(closes) - 50, 50):
        entry = closes[i]
        # Simulate price dropping
        found_dip = False
        for j in range(i + 1, min(i + 50, len(closes))):
            drop = (closes[j] - entry) / entry
            if drop < -0.02:
                # Standard DCA: buy immediately at -2%
                if std_count == 0 or True:
                    dca_price = closes[j]
                    std_count += 1
                    # Exit: average of entry + DCA at +3% or end
                    avg_price = (entry + dca_price) / 2
                    for k in range(j + 1, min(j + 30, len(closes))):
                        if closes[k] >= avg_price * 1.03:
                            standard_dca_pnl += (closes[k] - avg_price) / avg_price * BASE_EUR * 2
                            break
                    else:
                        end_p = closes[min(j + 30, len(closes) - 1)]
                        standard_dca_pnl += (end_p - avg_price) / avg_price * BASE_EUR * 2

                # Smart DCA: wait for BB squeeze (selling exhaustion)
                if not math.isnan(bb_low[j]) and closes[j] < bb_low[j]:
                    # Below lower BB = oversold, check for squeeze
                    if j > 2 and not math.isnan(bb_up[j]) and not math.isnan(bb_low[j]):
                        bw = (bb_up[j] - bb_low[j]) / bb_mid[j] if bb_mid[j] > 0 else 0
                        if bw < 0.04:  # Tight squeeze = exhaustion
                            dca_price = closes[j]
                            smart_count += 1
                            avg_price = (entry + dca_price) / 2
                            for k in range(j + 1, min(j + 30, len(closes))):
                                if closes[k] >= avg_price * 1.03:
                                    smart_dca_pnl += (closes[k] - avg_price) / avg_price * BASE_EUR * 2
                                    break
                            else:
                                end_p = closes[min(j + 30, len(closes) - 1)]
                                smart_dca_pnl += (end_p - avg_price) / avg_price * BASE_EUR * 2
                found_dip = True
                break

    return {
        "name": "Smart DCA (Volatility-Aware)",
        "standard_dca_count": std_count,
        "standard_dca_pnl": round(standard_dca_pnl, 2),
        "smart_dca_count": smart_count,
        "smart_dca_pnl": round(smart_dca_pnl, 2),
        "improvement_pnl": round(smart_dca_pnl - standard_dca_pnl, 2),
    }


# ---- IDEA 12: Eigen-Portfolio PCA Mean Reversion ----
def simulate_pca_mean_reversion(
    prices_list: List[List[float]],  # multiple asset price series
) -> Dict[str, Any]:
    """PCA-based statistical arbitrage across multiple assets."""
    n_assets = len(prices_list)
    min_len = min(len(p) for p in prices_list)

    # Calculate returns matrix
    returns_matrix = []
    for p in prices_list:
        rets = [p[i] / p[i - 1] - 1 for i in range(1, min_len)]
        returns_matrix.append(rets)

    # Simple PCA: compute covariance, use power iteration for first PC
    n_periods = len(returns_matrix[0])
    means = [sum(r) / n_periods for r in returns_matrix]
    centered = [[r[i] - means[j] for i in range(n_periods)] for j, r in enumerate(returns_matrix)]

    # Covariance matrix
    cov = [[0.0] * n_assets for _ in range(n_assets)]
    for i in range(n_assets):
        for j in range(n_assets):
            cov[i][j] = sum(centered[i][k] * centered[j][k] for k in range(n_periods)) / n_periods

    # Power iteration for first eigenvector (market factor)
    pc1 = [1.0 / n_assets] * n_assets
    for _ in range(50):
        new_pc = [sum(cov[i][j] * pc1[j] for j in range(n_assets)) for i in range(n_assets)]
        norm = sum(x ** 2 for x in new_pc) ** 0.5
        if norm < 1e-10:
            break
        pc1 = [x / norm for x in new_pc]

    # Calculate residuals (idiosyncratic returns)
    trades, wins, total_pnl = 0, 0, 0.0
    window = 60

    for t in range(window, n_periods - 10):
        # Market factor return
        market_ret = sum(pc1[j] * returns_matrix[j][t] for j in range(n_assets))

        # Find assets with extreme residuals
        for j in range(n_assets):
            residual = returns_matrix[j][t] - pc1[j] * market_ret
            # Rolling residual stats
            hist_residuals = [
                returns_matrix[j][k] - pc1[j] * sum(pc1[m] * returns_matrix[m][k] for m in range(n_assets))
                for k in range(t - window, t)
            ]
            if len(hist_residuals) < 10:
                continue
            mean_r = sum(hist_residuals) / len(hist_residuals)
            std_r = (sum((r - mean_r) ** 2 for r in hist_residuals) / len(hist_residuals)) ** 0.5
            if std_r < 1e-9:
                continue

            z = (residual - mean_r) / std_r

            if z < -2.0:  # Abnormally underperforming → buy
                entry = prices_list[j][t + 1]
                exit_p = prices_list[j][min(t + 6, min_len - 1)]
                pnl = (exit_p / entry - 1) * BASE_EUR - 2 * FEE_TAKER * BASE_EUR
                trades += 1
                total_pnl += pnl
                if pnl > 0:
                    wins += 1

    return {
        "name": "PCA Eigen-Portfolio Mean Reversion",
        "trades": trades,
        "wins": wins,
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(wins / max(trades, 1) * 100, 1),
        "pc1_weights": [round(w, 4) for w in pc1],
    }


# ---- IDEA 13: VPIN Toxicity ----
def simulate_vpin(closes: List[float], volumes: List[float]) -> Dict[str, Any]:
    """Volume-Synchronized Probability of Informed Trading."""
    bucket_size = sum(volumes[:100]) / 100 if len(volumes) > 100 else 1000
    buy_vol, sell_vol = [], []

    # Classify volume as buy or sell using tick rule
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            buy_vol.append(volumes[i])
            sell_vol.append(0)
        else:
            buy_vol.append(0)
            sell_vol.append(volumes[i])

    # Calculate VPIN in rolling windows
    vpin_window = 50
    vpins = [float("nan")] * len(buy_vol)
    for i in range(vpin_window, len(buy_vol)):
        total_buy = sum(buy_vol[i - vpin_window:i])
        total_sell = sum(sell_vol[i - vpin_window:i])
        total = total_buy + total_sell
        if total > 0:
            vpins[i] = abs(total_buy - total_sell) / total
        else:
            vpins[i] = 0

    # Simulate: avoid trading when VPIN is high (toxic flow)
    baseline_trades, baseline_pnl = 0, 0.0
    filtered_trades, filtered_pnl = 0, 0.0
    blocked_bad, blocked_good = 0, 0

    sma_7_v = sma(closes, 7)
    sma_25_v = sma(closes, 25)

    for i in range(100, len(closes) - 10, 5):
        if math.isnan(sma_7_v[i]) or math.isnan(sma_25_v[i]):
            continue
        if sma_7_v[i] <= sma_25_v[i]:
            continue

        entry = closes[i]
        exit_p = closes[min(i + 8, len(closes) - 1)]
        pnl = (exit_p / entry - 1) * BASE_EUR - 2 * FEE_TAKER * BASE_EUR

        baseline_trades += 1
        baseline_pnl += pnl

        if i < len(vpins) and not math.isnan(vpins[i]) and vpins[i] < 0.4:
            filtered_trades += 1
            filtered_pnl += pnl
        else:
            if pnl < 0:
                blocked_bad += 1
            else:
                blocked_good += 1

    return {
        "name": "VPIN Toxicity Filter",
        "baseline_trades": baseline_trades,
        "baseline_pnl": round(baseline_pnl, 2),
        "filtered_trades": filtered_trades,
        "filtered_pnl": round(filtered_pnl, 2),
        "improvement_pnl": round(filtered_pnl - baseline_pnl, 2),
        "blocked_bad_trades": blocked_bad,
        "blocked_good_trades": blocked_good,
    }


# ---- IDEA 14: Multi-Horizon Allocation ----
def simulate_multi_horizon(closes: List[float], regimes: List[str]) -> Dict[str, Any]:
    """Simultaneously run scalping, swing, and position strategies with adaptive allocation."""
    scalp_pnl, swing_pnl, position_pnl = 0.0, 0.0, 0.0
    scalp_w, swing_w, position_w = 0, 0, 0
    scalp_t, swing_t, position_t = 0, 0, 0

    for i in range(200, len(closes) - 50, 2):
        # Scalper: 3-bar hold
        entry = closes[i]
        exit_s = closes[min(i + 3, len(closes) - 1)]
        pnl_s = (exit_s / entry - 1) * BASE_EUR * 0.4 - 2 * FEE_TAKER * BASE_EUR * 0.4
        scalp_pnl += pnl_s
        scalp_t += 1
        if pnl_s > 0:
            scalp_w += 1

    for i in range(200, len(closes) - 50, 10):
        # Swing: 15-bar hold
        entry = closes[i]
        exit_sw = closes[min(i + 15, len(closes) - 1)]
        pnl_sw = (exit_sw / entry - 1) * BASE_EUR * 0.4 - 2 * FEE_TAKER * BASE_EUR * 0.4
        swing_pnl += pnl_sw
        swing_t += 1
        if pnl_sw > 0:
            swing_w += 1

    for i in range(200, len(closes) - 50, 50):
        # Position: 40-bar hold
        entry = closes[i]
        exit_p = closes[min(i + 40, len(closes) - 1)]
        pnl_p = (exit_p / entry - 1) * BASE_EUR * 0.2 - 2 * FEE_TAKER * BASE_EUR * 0.2
        position_pnl += pnl_p
        position_t += 1
        if pnl_p > 0:
            position_w += 1

    total = scalp_pnl + swing_pnl + position_pnl

    return {
        "name": "Multi-Horizon Allocation",
        "scalp": {"trades": scalp_t, "wins": scalp_w, "pnl": round(scalp_pnl, 2)},
        "swing": {"trades": swing_t, "wins": swing_w, "pnl": round(swing_pnl, 2)},
        "position": {"trades": position_t, "wins": position_w, "pnl": round(position_pnl, 2)},
        "combined_pnl": round(total, 2),
        "best_horizon": max([("scalp", scalp_pnl), ("swing", swing_pnl), ("position", position_pnl)], key=lambda x: x[1])[0],
    }


# ---- IDEA 15: Spread Regime Detector ----
def simulate_spread_regime(closes: List[float], highs: List[float], lows: List[float]) -> Dict[str, Any]:
    """Use simulated spread (high-low range) as information signal."""
    spreads = [(h - l) / c if c > 0 else 0 for h, l, c in zip(highs, lows, closes)]

    # Rolling z-score of spread
    baseline_pnl, filtered_pnl = 0.0, 0.0
    baseline_t, filtered_t = 0, 0

    sma_7_v = sma(closes, 7)
    sma_25_v = sma(closes, 25)

    for i in range(100, len(closes) - 10, 5):
        if math.isnan(sma_7_v[i]) or math.isnan(sma_25_v[i]):
            continue
        if sma_7_v[i] <= sma_25_v[i]:
            continue

        entry = closes[i]
        exit_p = closes[min(i + 8, len(closes) - 1)]
        pnl = (exit_p / entry - 1) * BASE_EUR - 2 * FEE_TAKER * BASE_EUR

        baseline_t += 1
        baseline_pnl += pnl

        # Spread z-score
        recent = spreads[max(0, i - 50):i]
        if len(recent) < 10:
            continue
        m = sum(recent) / len(recent)
        s = (sum((x - m) ** 2 for x in recent) / len(recent)) ** 0.5
        if s < 1e-10:
            continue
        z = (spreads[i] - m) / s

        if z < 1.0:  # Normal or tight spread → safe to trade
            filtered_t += 1
            filtered_pnl += pnl

    return {
        "name": "Spread Regime Detector",
        "baseline_trades": baseline_t,
        "baseline_pnl": round(baseline_pnl, 2),
        "filtered_trades": filtered_t,
        "filtered_pnl": round(filtered_pnl, 2),
        "improvement_pnl": round(filtered_pnl - baseline_pnl, 2),
    }


# ---- IDEA 16: Reflexivity Loop ----
def simulate_reflexivity(closes: List[float], volumes: List[float]) -> Dict[str, Any]:
    """Detect self-reinforcing price-volume feedback loops."""
    trades, wins, total_pnl = 0, 0, 0.0

    for i in range(50, len(closes) - 10, 5):
        # Autocorrelation of returns (lag 1-5)
        rets = [closes[j] / closes[j - 1] - 1 for j in range(i - 20, i)]
        if len(rets) < 10:
            continue

        # Simple lag-1 autocorrelation
        mean_r = sum(rets) / len(rets)
        var_r = sum((r - mean_r) ** 2 for r in rets) / len(rets)
        if var_r < 1e-12:
            continue
        autocorr = sum((rets[j] - mean_r) * (rets[j + 1] - mean_r) for j in range(len(rets) - 1))
        autocorr /= (len(rets) - 1) * var_r

        # Volume acceleration
        avg_vol = sum(volumes[max(0, i - 20):i]) / 20 if i >= 20 else 1
        vol_acc = volumes[i] / avg_vol if avg_vol > 0 else 1

        reflexivity = autocorr * vol_acc

        if reflexivity > 0.5:  # Strong positive feedback → ride the trend
            entry = closes[i]
            exit_p = closes[min(i + 10, len(closes) - 1)]  # wider hold
            pnl = (exit_p / entry - 1) * BASE_EUR * 1.3 - 2 * FEE_TAKER * BASE_EUR * 1.3
            trades += 1
            total_pnl += pnl
            if pnl > 0:
                wins += 1
        elif reflexivity < -0.3:  # Negative feedback → short opportunity
            entry = closes[i]
            exit_p = closes[min(i + 8, len(closes) - 1)]
            pnl = (entry / exit_p - 1) * BASE_EUR - 2 * FEE_TAKER * BASE_EUR  # short
            trades += 1
            total_pnl += pnl
            if pnl > 0:
                wins += 1

    return {
        "name": "Reflexivity Loop Detector",
        "trades": trades,
        "wins": wins,
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(wins / max(trades, 1) * 100, 1),
        "avg_pnl": round(total_pnl / max(trades, 1), 4),
    }


# ---- IDEA 17: Synthetic Pair Trading ----
def simulate_pair_trading(prices_a: List[float], prices_b: List[float]) -> Dict[str, Any]:
    """Pair trading: long underperformer, short outperformer when spread deviates."""
    min_len = min(len(prices_a), len(prices_b))
    # Calculate spread ratio
    ratio = [prices_a[i] / prices_b[i] for i in range(min_len)]

    trades, wins, total_pnl = 0, 0, 0.0
    window = 60

    for i in range(window, min_len - 10, 5):
        recent = ratio[i - window:i]
        mean_r = sum(recent) / len(recent)
        std_r = (sum((r - mean_r) ** 2 for r in recent) / len(recent)) ** 0.5
        if std_r < 1e-9:
            continue

        z = (ratio[i] - mean_r) / std_r

        if abs(z) > 2.0:
            # Mean reversion trade
            entry_i = i
            exit_i = min(i + 10, min_len - 1)

            if z > 2.0:
                # Ratio too high → short A, long B
                pnl_a = (prices_a[entry_i] - prices_a[exit_i]) / prices_a[entry_i] * BASE_EUR * 0.5
                pnl_b = (prices_b[exit_i] - prices_b[entry_i]) / prices_b[entry_i] * BASE_EUR * 0.5
            else:
                # Ratio too low → long A, short B
                pnl_a = (prices_a[exit_i] - prices_a[entry_i]) / prices_a[entry_i] * BASE_EUR * 0.5
                pnl_b = (prices_b[entry_i] - prices_b[exit_i]) / prices_b[entry_i] * BASE_EUR * 0.5

            pnl = pnl_a + pnl_b - 4 * FEE_TAKER * BASE_EUR * 0.5
            trades += 1
            total_pnl += pnl
            if pnl > 0:
                wins += 1

    return {
        "name": "Synthetic Pair Trading",
        "trades": trades,
        "wins": wins,
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(wins / max(trades, 1) * 100, 1),
        "avg_pnl": round(total_pnl / max(trades, 1), 4),
    }


# ---- IDEA 19: Cascade Profit Recycling ----
def simulate_cascade_recycling(closes: List[float], regimes: List[str]) -> Dict[str, Any]:
    """Re-invest profits immediately into same asset if signal still active."""
    sma_7_v = sma(closes, 7)
    sma_25_v = sma(closes, 25)

    normal_pnl = 0.0
    recycled_pnl = 0.0
    normal_t, recycle_t = 0, 0
    profit_pool = 0.0

    for i in range(100, len(closes) - 20, 8):
        if math.isnan(sma_7_v[i]) or math.isnan(sma_25_v[i]):
            continue
        if sma_7_v[i] <= sma_25_v[i]:
            continue

        entry = closes[i]
        exit_p = closes[min(i + 8, len(closes) - 1)]
        pnl = (exit_p / entry - 1) * BASE_EUR - 2 * FEE_TAKER * BASE_EUR
        normal_pnl += pnl
        normal_t += 1

        # Recycled: use profit_pool as extra investment
        recycled_base = BASE_EUR + max(0, profit_pool * 0.5)
        pnl_r = (exit_p / entry - 1) * recycled_base - 2 * FEE_TAKER * recycled_base
        recycled_pnl += pnl_r
        recycle_t += 1

        if pnl > 0:
            profit_pool += pnl * 0.3  # 30% of profit goes to recycling pool
        else:
            profit_pool = max(0, profit_pool + pnl)  # losses reduce pool

    return {
        "name": "Cascade Profit Recycling",
        "normal_trades": normal_t,
        "normal_pnl": round(normal_pnl, 2),
        "recycled_trades": recycle_t,
        "recycled_pnl": round(recycled_pnl, 2),
        "improvement_pnl": round(recycled_pnl - normal_pnl, 2),
        "final_profit_pool": round(profit_pool, 2),
    }


# ---- IDEA 20: Meta-Learning Strategy Selector ----
def simulate_meta_learning(closes: List[float], regimes: List[str]) -> Dict[str, Any]:
    """Meta-learner that selects optimal strategy mix based on recent performance."""
    # Three sub-strategies
    def strategy_momentum(c, i):
        if i < 10:
            return 0
        return (c[i] - c[i - 5]) / c[i - 5] * BASE_EUR - FEE_TAKER * BASE_EUR

    def strategy_mean_rev(c, i):
        if i < 30:
            return 0
        m = sum(c[i - 20:i]) / 20
        if c[i] < m * 0.98:
            exit_p = c[min(i + 5, len(c) - 1)]
            return (exit_p / c[i] - 1) * BASE_EUR - FEE_TAKER * BASE_EUR
        return 0

    def strategy_breakout(c, i):
        if i < 30:
            return 0
        highest = max(c[i - 20:i])
        if c[i] > highest * 1.005:
            exit_p = c[min(i + 8, len(c) - 1)]
            return (exit_p / c[i] - 1) * BASE_EUR - FEE_TAKER * BASE_EUR
        return 0

    # Rolling performance tracking
    strat_perf = {"momentum": [], "mean_rev": [], "breakout": []}
    weights = {"momentum": 0.33, "mean_rev": 0.33, "breakout": 0.33}

    static_pnl = 0.0
    adaptive_pnl = 0.0
    eval_window = 50

    for i in range(100, len(closes) - 10, 3):
        # Calculate each strategy's return
        pnl_m = strategy_momentum(closes, i)
        pnl_mr = strategy_mean_rev(closes, i)
        pnl_br = strategy_breakout(closes, i)

        strat_perf["momentum"].append(pnl_m)
        strat_perf["mean_rev"].append(pnl_mr)
        strat_perf["breakout"].append(pnl_br)

        # Static: equal weight
        static_pnl += (pnl_m + pnl_mr + pnl_br) / 3

        # Adaptive: weight by recent performance
        if len(strat_perf["momentum"]) > eval_window:
            for strat in weights:
                recent = strat_perf[strat][-eval_window:]
                sharpe = (sum(recent) / len(recent)) / (
                    max((sum((r - sum(recent) / len(recent)) ** 2 for r in recent) / len(recent)) ** 0.5, 1e-9)
                )
                weights[strat] = max(0.05, sharpe)

            # Normalize weights
            w_total = sum(weights.values())
            for k in weights:
                weights[k] /= w_total

        adaptive_pnl += weights["momentum"] * pnl_m + weights["mean_rev"] * pnl_mr + weights["breakout"] * pnl_br

    return {
        "name": "Meta-Learning Strategy Selector",
        "static_pnl": round(static_pnl, 2),
        "adaptive_pnl": round(adaptive_pnl, 2),
        "improvement_pnl": round(adaptive_pnl - static_pnl, 2),
        "final_weights": {k: round(v, 3) for k, v in weights.items()},
    }


# ---- Apply ideas as filters to REAL historical trades ----
def simulate_on_real_trades(archive_trades: List[Dict]) -> Dict[str, Any]:
    """Backtest filter ideas on actual trade outcomes."""
    valid = [t for t in archive_trades if t.get("profit") is not None and t.get("buy_price")]

    total_trades = len(valid)
    total_pnl = sum(t.get("profit", 0) or 0 for t in valid)
    wins = sum(1 for t in valid if (t.get("profit", 0) or 0) > 0)

    # Idea 3 & 8: Score-based filtering on real trades
    # Filter: only keep trades with score >= 7
    high_score = [t for t in valid if (t.get("score") or 0) >= 7.0]
    hs_pnl = sum(t.get("profit", 0) or 0 for t in high_score)
    hs_wins = sum(1 for t in high_score if (t.get("profit", 0) or 0) > 0)

    # Filter: RSI sweet spot (35-55)
    rsi_filter = [t for t in valid if t.get("rsi_at_entry") and 35 <= t["rsi_at_entry"] <= 55]
    rsi_pnl = sum(t.get("profit", 0) or 0 for t in rsi_filter)
    rsi_wins = sum(1 for t in rsi_filter if (t.get("profit", 0) or 0) > 0)

    # Filter: Volume > median
    vol_trades = [t for t in valid if t.get("volume_24h_eur")]
    if vol_trades:
        med_vol = sorted(t["volume_24h_eur"] for t in vol_trades)[len(vol_trades) // 2]
        high_vol = [t for t in vol_trades if t["volume_24h_eur"] >= med_vol]
        hv_pnl = sum(t.get("profit", 0) or 0 for t in high_vol)
        hv_wins = sum(1 for t in high_vol if (t.get("profit", 0) or 0) > 0)
    else:
        high_vol, hv_pnl, hv_wins = [], 0, 0

    # Filter: Regime
    regime_trades = {r: [] for r in ["neutral", "defensive", "aggressive", "unknown"]}
    for t in valid:
        r = t.get("opened_regime", "unknown") or "unknown"
        if r in regime_trades:
            regime_trades[r].append(t)

    regime_stats = {}
    for r, trades_list in regime_trades.items():
        if trades_list:
            r_pnl = sum(t.get("profit", 0) or 0 for t in trades_list)
            r_wins = sum(1 for t in trades_list if (t.get("profit", 0) or 0) > 0)
            regime_stats[r] = {
                "trades": len(trades_list),
                "pnl": round(r_pnl, 2),
                "winrate": round(r_wins / len(trades_list) * 100, 1),
            }

    # Combined filter: score >= 7 AND RSI 35-55
    combined = [
        t for t in valid
        if (t.get("score") or 0) >= 7.0
        and t.get("rsi_at_entry")
        and 35 <= t["rsi_at_entry"] <= 55
    ]
    comb_pnl = sum(t.get("profit", 0) or 0 for t in combined)
    comb_wins = sum(1 for t in combined if (t.get("profit", 0) or 0) > 0)

    return {
        "name": "Real Trade Analysis",
        "total": {"trades": total_trades, "pnl": round(total_pnl, 2), "winrate": round(wins / max(total_trades, 1) * 100, 1)},
        "high_score_7+": {"trades": len(high_score), "pnl": round(hs_pnl, 2), "winrate": round(hs_wins / max(len(high_score), 1) * 100, 1)},
        "rsi_35_55": {"trades": len(rsi_filter), "pnl": round(rsi_pnl, 2), "winrate": round(rsi_wins / max(len(rsi_filter), 1) * 100, 1)},
        "high_volume": {"trades": len(high_vol), "pnl": round(hv_pnl, 2), "winrate": round(hv_wins / max(len(high_vol), 1) * 100, 1)},
        "combined_score_rsi": {"trades": len(combined), "pnl": round(comb_pnl, 2), "winrate": round(comb_wins / max(len(combined), 1) * 100, 1)},
        "by_regime": regime_stats,
    }


# ===========================================================================
# MAIN SIMULATION
# ===========================================================================

def main():
    print("=" * 80)
    print("  ADVANCED IDEAS SIMULATOR — Bitvavo Trading Bot")
    print("  Testing 20 ultra-advanced concepts on historical + synthetic data")
    print("=" * 80)

    # Generate synthetic data (5 correlated assets)
    seeds = [42, 137, 256, 314, 500]
    all_prices = []
    for seed in seeds:
        c, h, l, v, r = generate_multi_regime_prices(n=8000, start=100.0, seed=seed)
        all_prices.append({"closes": c, "highs": h, "lows": l, "volumes": v, "regimes": r})

    primary = all_prices[0]
    closes = primary["closes"]
    highs = primary["highs"]
    lows = primary["lows"]
    volumes = primary["volumes"]
    regimes = primary["regimes"]

    results = []

    # Run all simulations
    print("\n[1/15] Transfer Entropy (Lead-Lag)...")
    r1 = simulate_transfer_entropy(closes, all_prices[1]["closes"], regimes)
    results.append(r1)
    print(f"       Trades: {r1['trades']}, Win%: {r1['win_rate']}%, PnL: €{r1['total_pnl']}")

    print("[2/15] Hurst Exponent Regime...")
    r2 = simulate_hurst_regime(closes, regimes)
    results.append(r2)
    print(f"       Trades: {r2['trades']}, Win%: {r2['win_rate']}%, PnL: €{r2['total_pnl']}")

    print("[3/15] Shannon Entropy Gate...")
    r3 = simulate_shannon_entropy_gate(closes, regimes)
    results.append(r3)
    print(f"       Baseline PnL: €{r3['baseline_pnl']} → Filtered PnL: €{r3['filtered_pnl']} (Δ€{r3['improvement_pnl']})")

    print("[4/15] Bayesian Signal Fusion...")
    r4 = simulate_bayesian_fusion(closes, regimes)
    results.append(r4)
    print(f"       Static PnL: €{r4['static_pnl']} → Adaptive PnL: €{r4['adaptive_pnl']} (Δ€{r4['improvement_pnl']})")

    print("[5/15] Adversarial Stop-Loss...")
    r5 = simulate_adversarial_stops(closes, highs, lows)
    results.append(r5)
    print(f"       Stops avoided: {r5['stops_avoided']}, PnL improvement: €{r5['improvement_pnl']}")

    print("[6/15] Volatility Term Structure...")
    r6 = simulate_vol_term_structure(closes, highs, lows, regimes)
    results.append(r6)
    print(f"       Trades: {r6['trades']}, Win%: {r6['win_rate']}%, PnL: €{r6['total_pnl']}")

    print("[7/15] Trade DNA Fingerprinting...")
    r7 = simulate_trade_dna(closes, regimes)
    results.append(r7)
    print(f"       Baseline PnL: €{r7['baseline_pnl']} → DNA PnL: €{r7['dna_pnl']} (Δ€{r7['improvement_pnl']})")

    print("[8/15] Time-of-Day Seasonality...")
    r8 = simulate_time_of_day(closes, regimes)
    results.append(r8)
    print(f"       Baseline PnL: €{r8['baseline_pnl']} → Filtered PnL: €{r8['filtered_pnl']} (Δ€{r8['improvement_pnl']})")

    print("[9/15] Markov Regime Anticipation...")
    r9 = simulate_markov_regime(closes, regimes)
    results.append(r9)
    print(f"       Baseline PnL: €{r9['baseline_pnl']}, Anticipation PnL: €{r9['anticipation_pnl']}")

    print("[10/15] Smart DCA (Volatility-Aware)...")
    r10 = simulate_smart_dca(closes, regimes)
    results.append(r10)
    print(f"       Standard DCA: €{r10['standard_dca_pnl']} → Smart DCA: €{r10['smart_dca_pnl']} (Δ€{r10['improvement_pnl']})")

    print("[11/15] PCA Eigen-Portfolio...")
    r11 = simulate_pca_mean_reversion([p["closes"] for p in all_prices])
    results.append(r11)
    print(f"       Trades: {r11['trades']}, Win%: {r11['win_rate']}%, PnL: €{r11['total_pnl']}")

    print("[12/15] VPIN Toxicity Filter...")
    r12 = simulate_vpin(closes, volumes)
    results.append(r12)
    print(f"       Baseline PnL: €{r12['baseline_pnl']} → Filtered PnL: €{r12['filtered_pnl']} (Δ€{r12['improvement_pnl']})")

    print("[13/15] Multi-Horizon Allocation...")
    r13 = simulate_multi_horizon(closes, regimes)
    results.append(r13)
    print(f"       Scalp: €{r13['scalp']['pnl']}, Swing: €{r13['swing']['pnl']}, Position: €{r13['position']['pnl']}")

    print("[14/15] Reflexivity Loop Detector...")
    r14 = simulate_reflexivity(closes, volumes)
    results.append(r14)
    print(f"       Trades: {r14['trades']}, Win%: {r14['win_rate']}%, PnL: €{r14['total_pnl']}")

    print("[15/15] Pair Trading + Meta-Learning...")
    r15 = simulate_pair_trading(closes, all_prices[1]["closes"])
    results.append(r15)
    print(f"       Pair: Trades={r15['trades']}, Win%={r15['win_rate']}%, PnL=€{r15['total_pnl']}")

    r16 = simulate_meta_learning(closes, regimes)
    results.append(r16)
    print(f"       Meta: Static=€{r16['static_pnl']} → Adaptive=€{r16['adaptive_pnl']} (Δ€{r16['improvement_pnl']})")

    r17 = simulate_spread_regime(closes, highs, lows)
    results.append(r17)
    print(f"       Spread: Baseline=€{r17['baseline_pnl']} → Filtered=€{r17['filtered_pnl']} (Δ€{r17['improvement_pnl']})")

    r18 = simulate_cascade_recycling(closes, regimes)
    results.append(r18)
    print(f"       Recycling: Normal=€{r18['normal_pnl']} → Recycled=€{r18['recycled_pnl']} (Δ€{r18['improvement_pnl']})")

    # Real trades analysis
    print("\n" + "=" * 80)
    print("  REAL TRADE ANALYSIS (890 historical trades)")
    print("=" * 80)
    archive = load_archive_trades()
    if archive:
        r_real = simulate_on_real_trades(archive)
        results.append(r_real)
        print(f"  All trades:        {r_real['total']['trades']} trades, €{r_real['total']['pnl']}, {r_real['total']['winrate']}% win")
        print(f"  Score >= 7:        {r_real['high_score_7+']['trades']} trades, €{r_real['high_score_7+']['pnl']}, {r_real['high_score_7+']['winrate']}% win")
        print(f"  RSI 35-55:         {r_real['rsi_35_55']['trades']} trades, €{r_real['rsi_35_55']['pnl']}, {r_real['rsi_35_55']['winrate']}% win")
        print(f"  High Volume:       {r_real['high_volume']['trades']} trades, €{r_real['high_volume']['pnl']}, {r_real['high_volume']['winrate']}% win")
        print(f"  Combined (S+RSI):  {r_real['combined_score_rsi']['trades']} trades, €{r_real['combined_score_rsi']['pnl']}, {r_real['combined_score_rsi']['winrate']}% win")
        print(f"\n  By Regime:")
        for regime, stats in r_real.get("by_regime", {}).items():
            print(f"    {regime:15s} {stats['trades']:3d} trades  €{stats['pnl']:8.2f}  {stats['winrate']}% win")

    # ---- RANKING ----
    print("\n" + "=" * 80)
    print("  IMPACT RANKING — Ideas sorted by profitability improvement")
    print("=" * 80)

    ranking = []
    for r in results:
        name = r.get("name", "?")
        # Extract improvement metric
        if "improvement_pnl" in r:
            ranking.append((name, r["improvement_pnl"], "filter_improvement"))
        elif "total_pnl" in r:
            ranking.append((name, r["total_pnl"], "absolute"))
        elif "combined_pnl" in r:
            ranking.append((name, r["combined_pnl"], "combined"))
        elif "adaptive_pnl" in r:
            ranking.append((name, r["adaptive_pnl"], "adaptive"))

    ranking.sort(key=lambda x: x[1], reverse=True)
    print(f"\n  {'Rank':>4}  {'Idea':<40} {'PnL Impact':>12}  {'Type':<20}")
    print(f"  {'─' * 4}  {'─' * 40} {'─' * 12}  {'─' * 20}")
    for idx, (name, pnl, typ) in enumerate(ranking, 1):
        marker = " ★" if pnl > 0 else "  "
        print(f"  {idx:>4}  {name:<40} €{pnl:>10.2f}  {typ:<20}{marker}")

    # Save results
    output_path = PROJECT_ROOT / "data" / "advanced_ideas_simulation.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to {output_path}")

    # Save recommended implementations
    positive = [(name, pnl) for name, pnl, _ in ranking if pnl > 0]
    print(f"\n  ✓ {len(positive)} ideas showed POSITIVE impact")
    print(f"  ✗ {len(ranking) - len(positive)} ideas showed negative/neutral impact")

    if positive:
        print(f"\n  TOP RECOMMENDATIONS FOR IMPLEMENTATION:")
        for name, pnl in positive[:5]:
            print(f"    → {name}: +€{pnl:.2f}")

    return results


if __name__ == "__main__":
    main()
