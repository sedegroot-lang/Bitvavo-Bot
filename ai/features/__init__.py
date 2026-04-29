"""Feature store — versioned feature engineering for the trading model.

A single source of truth for feature names, computation, and version history.
Every trained model should reference a feature-store version so we can reproduce
predictions in backtests and shadow trading.

Versioning rule:
- Increment minor version when adding new features.
- Increment major version on breaking changes (rename, removal, semantics).
- Never silently change a feature's computation in place.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Sequence

FEATURE_STORE_VERSION = "1.0.0"


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    description: str
    source: str  # e.g. "1m_candles", "ml_info", "regime_engine"


# Canonical 11-feature schema used by ai/ai_xgb_model.json (n_features_in_=11).
FEATURE_SCHEMA: List[FeatureSpec] = [
    FeatureSpec("rsi", "Relative Strength Index 14", "1m_candles"),
    FeatureSpec("macd", "MACD line - signal line", "1m_candles"),
    FeatureSpec("ema20", "Exponential MA 20", "1m_candles"),
    FeatureSpec("sma_short", "Short SMA (config: SMA_SHORT)", "1m_candles"),
    FeatureSpec("sma_long", "Long SMA (config: SMA_LONG)", "1m_candles"),
    FeatureSpec("price", "Last close price", "1m_candles"),
    FeatureSpec("volume", "Last bar volume (base ccy)", "1m_candles"),
    FeatureSpec("bb_position", "Position in Bollinger band [0..1]", "1m_candles"),
    FeatureSpec("stochastic_k", "Stochastic %K", "1m_candles"),
    FeatureSpec("avg_volume", "Mean volume over 20 bars", "1m_candles"),
    FeatureSpec("trend_score", "Heuristic trend score [-2..+2]", "1m_candles"),
]


def feature_names() -> List[str]:
    return [f.name for f in FEATURE_SCHEMA]


def vectorize(ml_info: Mapping[str, Any]) -> List[float]:
    """Best-effort flat numeric vector aligned with FEATURE_SCHEMA.

    Returns 11 floats; missing values become 0.0. NEVER raises.
    """
    out: List[float] = []
    for spec in FEATURE_SCHEMA:
        v = ml_info.get(spec.name) if isinstance(ml_info, Mapping) else None
        try:
            out.append(float(v) if v is not None else 0.0)
        except Exception:
            out.append(0.0)
    return out


def schema_metadata() -> dict:
    return {
        "version": FEATURE_STORE_VERSION,
        "n_features": len(FEATURE_SCHEMA),
        "features": [{"name": f.name, "description": f.description, "source": f.source} for f in FEATURE_SCHEMA],
    }


__all__ = ["FEATURE_STORE_VERSION", "FEATURE_SCHEMA", "feature_names", "vectorize", "schema_metadata"]
