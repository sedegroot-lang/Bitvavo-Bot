"""Entropy-Weighted Kelly Sizing — information-theoretic position sizing.

Combines Shannon entropy of recent price returns with Kelly criterion:
- Low entropy (predictable) → use full half-Kelly fraction
- High entropy (chaotic) → reduce to quarter-Kelly or less
- Unknown (insufficient data) → use default sizing

This creates an adaptive position sizing method that scales exposure to the
information content of the market, rather than using fixed sizing.
"""

from __future__ import annotations

import math
from typing import Any, Dict, MutableMapping, Optional, Sequence


def shannon_entropy_ratio(closes: Sequence[float], window: int = 60, bins: int = 20) -> Optional[float]:
    """Compute normalized Shannon entropy of price returns.

    Returns a value in [0, 1]:
        0 = perfectly predictable (all returns in one bin)
        1 = maximum randomness (uniform distribution)
    """
    if len(closes) < window + 1:
        return None

    returns = []
    for i in range(-window, 0):
        if closes[i - 1] > 0:
            returns.append((closes[i] - closes[i - 1]) / closes[i - 1])

    if len(returns) < bins:
        return None

    # Build histogram
    min_r = min(returns)
    max_r = max(returns)
    spread = max_r - min_r
    if spread < 1e-12:
        return 0.0  # All returns identical = zero entropy

    bin_width = spread / bins
    counts = [0] * bins
    for r in returns:
        idx = int((r - min_r) / bin_width)
        idx = min(idx, bins - 1)
        counts[idx] += 1

    # Compute entropy
    n = len(returns)
    entropy = 0.0
    for c in counts:
        if c > 0:
            p = c / n
            entropy -= p * math.log2(p)

    max_entropy = math.log2(bins)
    if max_entropy < 1e-12:
        return 0.0
    return entropy / max_entropy


def entropy_kelly_fraction(
    closes: Sequence[float],
    base_kelly: float = 0.5,
    window: int = 60,
    min_fraction: float = 0.1,
    max_fraction: float = 0.5,
    entropy_threshold: float = 0.70,
) -> float:
    """Compute entropy-adjusted Kelly fraction.

    Args:
        closes: recent close prices
        base_kelly: the base half-Kelly fraction (from kelly_sizing.py)
        window: entropy calculation window
        min_fraction: floor for the sizing fraction
        max_fraction: ceiling for the sizing fraction
        entropy_threshold: above this entropy ratio, start reducing

    Returns:
        Adjusted Kelly fraction in [min_fraction, max_fraction].
    """
    ratio = shannon_entropy_ratio(closes, window)
    if ratio is None:
        return base_kelly  # No data → use default

    if ratio <= entropy_threshold:
        # Predictable market: use full Kelly or even slightly above half-Kelly
        # Scale from base_kelly at threshold to max_fraction at zero entropy
        factor = 1.0 + (1.0 - ratio / entropy_threshold) * 0.3
        adjusted = base_kelly * factor
    else:
        # Chaotic market: reduce sizing linearly from base_kelly to min_fraction
        # at entropy_ratio = 1.0
        excess = (ratio - entropy_threshold) / (1.0 - entropy_threshold)
        adjusted = base_kelly * (1.0 - excess * 0.7)

    return max(min_fraction, min(max_fraction, adjusted))


def get_sizing_adjustment(
    closes: Sequence[float],
    config: MutableMapping[str, Any],
) -> Dict[str, Any]:
    """Convenience function: compute entropy-based sizing adjustment.

    Returns dict with:
        - fraction: the adjusted Kelly fraction
        - entropy_ratio: current Shannon entropy ratio
        - regime: 'predictable', 'normal', or 'chaotic'
    """
    window = int(config.get('ENTROPY_KELLY_WINDOW', 60))
    base = float(config.get('KELLY_FRACTION', 0.5))
    threshold = float(config.get('ENTROPY_KELLY_THRESHOLD', 0.70))

    ratio = shannon_entropy_ratio(closes, window)
    fraction = entropy_kelly_fraction(closes, base, window, entropy_threshold=threshold)

    if ratio is None:
        regime = 'unknown'
    elif ratio < 0.40:
        regime = 'predictable'
    elif ratio > threshold:
        regime = 'chaotic'
    else:
        regime = 'normal'

    return {
        'fraction': round(fraction, 4),
        'entropy_ratio': round(ratio, 4) if ratio is not None else None,
        'regime': regime,
    }
