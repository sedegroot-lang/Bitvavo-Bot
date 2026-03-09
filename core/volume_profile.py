"""Volume Profile & VWAP Engine — institutional-grade price-level analysis.

Provides:
1. VWAP (Volume Weighted Average Price) — dynamic support/resistance
2. Volume Profile — identifies High-Volume Nodes (HVN) as key levels
3. Score modifier based on price position relative to VWAP & HVN

Usage
-----
    from core.volume_profile import vwap_score_modifier, calculate_vwap
    modifier, details = vwap_score_modifier(candles_1m)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# VWAP Calculation
# ---------------------------------------------------------------------------

def calculate_vwap(
    closes: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    volumes: Sequence[float],
) -> Optional[float]:
    """Calculate Volume Weighted Average Price.
    
    VWAP = Σ(Typical_Price × Volume) / Σ(Volume)
    Typical_Price = (High + Low + Close) / 3
    """
    n = min(len(closes), len(highs), len(lows), len(volumes))
    if n < 10:
        return None
    
    try:
        c = np.array(closes[-n:], dtype=np.float64)
        h = np.array(highs[-n:], dtype=np.float64)
        l = np.array(lows[-n:], dtype=np.float64)
        v = np.array(volumes[-n:], dtype=np.float64)
        
        typical_price = (h + l + c) / 3.0
        cum_tpv = np.sum(typical_price * v)
        cum_vol = np.sum(v)
        
        if cum_vol < 1e-12:
            return None
        
        return float(cum_tpv / cum_vol)
    except Exception:
        return None


def calculate_vwap_bands(
    closes: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    volumes: Sequence[float],
    std_multiplier: float = 1.0,
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """VWAP with upper and lower bands (± std dev).
    
    Returns (vwap, upper_band, lower_band).
    """
    n = min(len(closes), len(highs), len(lows), len(volumes))
    if n < 10:
        return None, None, None
    
    try:
        c = np.array(closes[-n:], dtype=np.float64)
        h = np.array(highs[-n:], dtype=np.float64)
        l = np.array(lows[-n:], dtype=np.float64)
        v = np.array(volumes[-n:], dtype=np.float64)
        
        typical_price = (h + l + c) / 3.0
        cum_tpv = np.cumsum(typical_price * v)
        cum_vol = np.cumsum(v)
        
        # Avoid division by zero
        mask = cum_vol > 1e-12
        if not np.any(mask):
            return None, None, None
        
        vwap_series = np.where(mask, cum_tpv / cum_vol, np.nan)
        vwap = float(vwap_series[-1])
        
        # VWAP standard deviation
        squared_diff = (typical_price - vwap) ** 2
        variance = float(np.sum(squared_diff * v) / np.sum(v))
        std = float(np.sqrt(variance))
        
        upper = vwap + std_multiplier * std
        lower = vwap - std_multiplier * std
        
        return vwap, upper, lower
    except Exception:
        return None, None, None


# ---------------------------------------------------------------------------
# Volume Profile
# ---------------------------------------------------------------------------

def calculate_volume_profile(
    closes: Sequence[float],
    volumes: Sequence[float],
    n_bins: int = 20,
) -> Dict[str, Any]:
    """Build a volume profile — distribution of volume at price levels.
    
    Returns dict with:
    - poc (Point of Control): price level with highest volume
    - hvn_levels: list of high-volume node prices
    - value_area_high/low: 70% value area bounds
    """
    n = min(len(closes), len(volumes))
    if n < 20:
        return {"poc": None, "hvn_levels": [], "value_area_high": None, "value_area_low": None}
    
    try:
        c = np.array(closes[-n:], dtype=np.float64)
        v = np.array(volumes[-n:], dtype=np.float64)
        
        price_min, price_max = float(np.min(c)), float(np.max(c))
        if price_max - price_min < 1e-12:
            return {"poc": float(np.mean(c)), "hvn_levels": [], "value_area_high": None, "value_area_low": None}
        
        bin_edges = np.linspace(price_min, price_max, n_bins + 1)
        bin_volumes = np.zeros(n_bins, dtype=np.float64)
        
        for i in range(n):
            bin_idx = int((c[i] - price_min) / (price_max - price_min) * (n_bins - 1))
            bin_idx = max(0, min(n_bins - 1, bin_idx))
            bin_volumes[bin_idx] += v[i]
        
        # Point of Control — highest volume bin
        poc_idx = int(np.argmax(bin_volumes))
        poc_price = float((bin_edges[poc_idx] + bin_edges[poc_idx + 1]) / 2)
        
        # High Volume Nodes — bins with volume > 1.5× average
        avg_bin_vol = float(np.mean(bin_volumes))
        hvn_mask = bin_volumes > avg_bin_vol * 1.5
        hvn_levels = [
            float((bin_edges[i] + bin_edges[i + 1]) / 2)
            for i in range(n_bins) if hvn_mask[i]
        ]
        
        # Value Area (70% of total volume)
        total_vol = float(np.sum(bin_volumes))
        target_vol = total_vol * 0.70
        
        # Expand outward from POC
        sorted_indices = np.argsort(bin_volumes)[::-1]
        cumulative = 0.0
        va_bins = set()
        for idx in sorted_indices:
            va_bins.add(int(idx))
            cumulative += bin_volumes[idx]
            if cumulative >= target_vol:
                break
        
        va_indices = sorted(va_bins)
        value_area_low = float(bin_edges[va_indices[0]]) if va_indices else price_min
        value_area_high = float(bin_edges[va_indices[-1] + 1]) if va_indices else price_max
        
        return {
            "poc": poc_price,
            "hvn_levels": hvn_levels,
            "value_area_high": value_area_high,
            "value_area_low": value_area_low,
            "bin_edges": bin_edges.tolist(),
            "bin_volumes": bin_volumes.tolist(),
        }
    except Exception as exc:
        logger.debug(f"[VP] Volume profile error: {exc}")
        return {"poc": None, "hvn_levels": [], "value_area_high": None, "value_area_low": None}


# ---------------------------------------------------------------------------
# Score Modifier
# ---------------------------------------------------------------------------

def vwap_score_modifier(
    closes: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    volumes: Sequence[float],
) -> Tuple[float, Dict[str, Any]]:
    """Calculate entry score modifier based on VWAP and Volume Profile.
    
    Returns
    -------
    (modifier, details) : tuple
        modifier in range [-1.5, +3.0]
    """
    if not closes or len(closes) < 30:
        return 0.0, {"reason": "insufficient_data"}
    
    price = closes[-1]
    
    # VWAP analysis
    vwap, vwap_upper, vwap_lower = calculate_vwap_bands(closes, highs, lows, volumes)
    
    # Volume profile
    vp = calculate_volume_profile(closes, volumes)
    
    modifier = 0.0
    reasons = []
    
    if vwap is not None:
        pct_from_vwap = (price - vwap) / vwap * 100
        
        if pct_from_vwap < -0.5:
            # Price significantly below VWAP = institutional discount zone
            modifier += min(2.0, abs(pct_from_vwap) * 0.8)
            reasons.append(f"below_vwap ({pct_from_vwap:+.2f}%)")
        elif pct_from_vwap < -0.1:
            # Slightly below VWAP
            modifier += 0.5
            reasons.append(f"near_below_vwap ({pct_from_vwap:+.2f}%)")
        elif pct_from_vwap > 1.0:
            # Extended above VWAP = chasing
            modifier -= min(1.5, pct_from_vwap * 0.3)
            reasons.append(f"extended_above_vwap ({pct_from_vwap:+.2f}%)")
    
    # Volume Profile analysis
    poc = vp.get("poc")
    va_low = vp.get("value_area_low")
    va_high = vp.get("value_area_high")
    
    if poc is not None and va_low is not None:
        if price <= va_low:
            # Below value area = undervalued
            modifier += 1.0
            reasons.append("below_value_area")
        elif poc is not None and abs(price - poc) / poc < 0.002:
            # Near Point of Control = strong support
            modifier += 0.5
            reasons.append("near_poc")
        elif va_high is not None and price >= va_high:
            # Above value area = overextended
            modifier -= 0.5
            reasons.append("above_value_area")
    
    modifier = max(-1.5, min(3.0, modifier))
    
    details = {
        "vwap": round(vwap, 8) if vwap is not None else None,
        "vwap_upper": round(vwap_upper, 8) if vwap_upper is not None else None,
        "vwap_lower": round(vwap_lower, 8) if vwap_lower is not None else None,
        "poc": round(poc, 8) if poc is not None else None,
        "value_area_high": round(va_high, 8) if va_high is not None else None,
        "value_area_low": round(va_low, 8) if va_low is not None else None,
        "price": round(price, 8),
        "modifier": round(modifier, 2),
        "reasons": reasons,
    }
    
    return modifier, details
