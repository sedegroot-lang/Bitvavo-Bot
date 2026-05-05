"""Entry-confidence framework — multi-pillar gating for new trade entries.

Computes a composite confidence score in [0, 1] from 6 pillars:

  A. Trend agreement (multi-timeframe via 1m + downsampled 5m windows)
  B. Momentum quality (RSI vs regime archetype)
  C. Volume confirmation (volume z-score vs rolling median)
  D. Volatility opportunity (ATR/price band sweet-spot 0.4%-2.5%)
  E. ML model agreement (XGB confidence proxied via score-before-ml gap)
  F. Cross-market context (correlation with currently-open trades)

Aggregation = geometric mean → ONE weak pillar tanks the score.

Usage:
    res = compute_entry_confidence(closes_1m, highs_1m, lows_1m, volumes_1m,
                                   ml_info=ml_info, open_market_closes=...)
    if res.confidence >= cfg.get('ENTRY_CONFIDENCE_MIN', 0.55):
        ... allow trade ...

Design notes:
- Pure function (no I/O, no global state) → trivially unit-testable.
- Read-only inputs; never mutates trade or config.
- Returns a dataclass with all sub-scores so the caller can log / persist.
- Time-stop is INTENTIONALLY NOT included here — see FIX_LOG #003 (no
  time-based exits, no loss sells). Better entries solve the stuck-trade
  problem at the source.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

__all__ = [
    "EntryConfidenceResult",
    "compute_entry_confidence",
    "is_confidence_enabled",
    "min_confidence_threshold",
]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class EntryConfidenceResult:
    confidence: float = 0.0  # geometric mean of pillars, [0, 1]
    pillars: Dict[str, float] = field(default_factory=dict)
    reasons: Dict[str, str] = field(default_factory=dict)
    passed: bool = False
    weakest_pillar: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "confidence": round(self.confidence, 4),
            "pillars": {k: round(v, 4) for k, v in self.pillars.items()},
            "reasons": dict(self.reasons),
            "passed": self.passed,
            "weakest_pillar": self.weakest_pillar,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except Exception:
        return default


def _clip01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _ema(values: Sequence[float], period: int) -> Optional[float]:
    if not values or period <= 0 or len(values) < period:
        return None
    k = 2.0 / (period + 1.0)
    ema_val = sum(values[:period]) / period
    for v in values[period:]:
        ema_val = (v - ema_val) * k + ema_val
    return ema_val


def _atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14) -> Optional[float]:
    if not highs or not lows or not closes:
        return None
    n = min(len(highs), len(lows), len(closes))
    if n < period + 1:
        return None
    trs: List[float] = []
    for i in range(n - period, n):
        h = float(highs[i])
        lw = float(lows[i])
        cp = float(closes[i - 1])
        tr = max(h - lw, abs(h - cp), abs(lw - cp))
        trs.append(tr)
    if not trs:
        return None
    return sum(trs) / len(trs)


def _resample_5m(closes_1m: Sequence[float]) -> List[float]:
    """Downsample 1m closes → 5m by taking every 5th bar."""
    if not closes_1m:
        return []
    n = len(closes_1m)
    return [float(closes_1m[i]) for i in range(n - 1, -1, -5)][::-1]


def _correlation(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    n = min(len(a), len(b))
    if n < 10:
        return None
    aa = [float(x) for x in a[-n:]]
    bb = [float(x) for x in b[-n:]]
    ma = sum(aa) / n
    mb = sum(bb) / n
    sa = math.sqrt(sum((x - ma) ** 2 for x in aa))
    sb = math.sqrt(sum((x - mb) ** 2 for x in bb))
    if sa == 0 or sb == 0:
        return None
    cov = sum((aa[i] - ma) * (bb[i] - mb) for i in range(n))
    return cov / (sa * sb)


# ---------------------------------------------------------------------------
# Pillar A — Multi-timeframe trend agreement
# ---------------------------------------------------------------------------


def _pillar_trend(closes_1m: Sequence[float]) -> tuple[float, str]:
    if len(closes_1m) < 60:
        return 0.5, "insufficient_data"
    ema20_1m = _ema(closes_1m, 20)
    ema50_1m = _ema(closes_1m, 50)
    closes_5m = _resample_5m(closes_1m)
    ema20_5m = _ema(closes_5m, 20) if len(closes_5m) >= 20 else None
    ema50_5m = _ema(closes_5m, 50) if len(closes_5m) >= 50 else None

    votes = 0
    total = 0
    if ema20_1m is not None and ema50_1m is not None:
        total += 1
        if ema20_1m > ema50_1m:
            votes += 1
    if ema20_5m is not None and ema50_5m is not None:
        total += 1
        if ema20_5m > ema50_5m:
            votes += 1

    if total == 0:
        return 0.5, "no_emas"
    score = votes / total
    return _clip01(score), f"{votes}/{total}_tfs_bullish"


# ---------------------------------------------------------------------------
# Pillar B — Momentum quality (RSI sweet spots)
# ---------------------------------------------------------------------------


def _pillar_momentum(rsi: Optional[float], regime: str = "neutral") -> tuple[float, str]:
    if rsi is None:
        return 0.5, "rsi_missing"
    r = float(rsi)
    # Reject extremes
    if r >= 75 or r <= 25:
        return 0.1, f"rsi_extreme_{r:.0f}"
    # Continuation in trending: prefer 50-65
    # Bounce in ranging: prefer 35-50
    if regime in ("trending_up", "aggressive"):
        if 50 <= r <= 65:
            return 1.0, f"rsi_continuation_{r:.0f}"
        if 45 <= r < 50:
            return 0.7, f"rsi_pullback_{r:.0f}"
        if 65 < r <= 70:
            return 0.5, f"rsi_late_{r:.0f}"
        return 0.3, f"rsi_unaligned_trending_{r:.0f}"
    # neutral / ranging / defensive
    if 35 <= r <= 50:
        return 1.0, f"rsi_bounce_zone_{r:.0f}"
    if 50 < r <= 60:
        return 0.7, f"rsi_neutral_up_{r:.0f}"
    return 0.4, f"rsi_neutral_other_{r:.0f}"


# ---------------------------------------------------------------------------
# Pillar C — Volume confirmation
# ---------------------------------------------------------------------------


def _pillar_volume(volumes_1m: Sequence[float]) -> tuple[float, str]:
    if not volumes_1m or len(volumes_1m) < 30:
        return 0.5, "vol_insufficient"
    last5 = [float(v) for v in volumes_1m[-5:]]
    base = sorted([float(v) for v in volumes_1m[-30:]])
    median = base[len(base) // 2]
    if median <= 0:
        return 0.5, "vol_median_zero"
    last5_sum = sum(last5)
    last5_avg = last5_sum / 5.0
    ratio = last5_avg / median
    # Quality-Hunter tightening (May 2026): require a real spike, not drift.
    # Sweet spot: 2.0x to 4.0x median (clear "something is happening NOW",
    # not a pump-and-dump). 1.5x-2.0x = mild interest, below 1.5x = drift.
    if 2.0 <= ratio <= 4.0:
        return _clip01(0.85 + 0.05 * min(ratio - 2.0, 2.0)), f"vol_spike_{ratio:.2f}"
    if 1.5 <= ratio < 2.0:
        return _clip01(0.55 + 0.6 * (ratio - 1.5)), f"vol_rising_{ratio:.2f}"
    if ratio < 0.6:
        return 0.15, f"vol_dry_{ratio:.2f}"
    if ratio > 5.0:
        return 0.25, f"vol_pump_{ratio:.2f}"
    if ratio < 1.2:
        return 0.4, f"vol_low_{ratio:.2f}"
    if ratio < 1.5:
        return 0.5, f"vol_ok_{ratio:.2f}"
    return 0.55, f"vol_high_{ratio:.2f}"


# ---------------------------------------------------------------------------
# Pillar D — Volatility opportunity
# ---------------------------------------------------------------------------


def _pillar_volatility(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]) -> tuple[float, str]:
    if len(closes) < 16:
        return 0.5, "vol_insufficient"
    atr = _atr(highs, lows, closes, period=14)
    last = _safe_float(closes[-1])
    if atr is None or last <= 0:
        return 0.5, "atr_unavailable"
    vol_pct = atr / last
    if vol_pct < 0.002:
        return 0.2, f"too_quiet_{vol_pct:.4f}"
    if vol_pct > 0.030:
        return 0.2, f"too_wild_{vol_pct:.4f}"
    # Sweet spot 0.005-0.020 (0.5%-2.0%); peak at 0.012 (1.2%)
    sweet = 0.012
    span = 0.013
    score = 1.0 - abs(vol_pct - sweet) / span
    return _clip01(score), f"atr_pct_{vol_pct:.4f}"


# ---------------------------------------------------------------------------
# Pillar E — ML agreement
# ---------------------------------------------------------------------------


def _pillar_ml(ml_info: Optional[Mapping[str, Any]]) -> tuple[float, str]:
    if not ml_info:
        return 0.5, "ml_missing"
    ml_signal = ml_info.get("ml_signal")
    ml_conf = _safe_float(ml_info.get("ml_confidence"), 0.5)
    if ml_signal is None:
        return 0.5, "ml_no_signal"
    sig = str(ml_signal).lower()
    if sig in ("buy", "long", "1", "true"):
        return _clip01(0.5 + ml_conf * 0.5), f"ml_buy_conf_{ml_conf:.2f}"
    if sig in ("sell", "short", "-1", "false"):
        return _clip01(0.5 - ml_conf * 0.5), f"ml_sell_conf_{ml_conf:.2f}"
    return 0.5, f"ml_neutral_{sig}"


# ---------------------------------------------------------------------------
# Pillar F — Cross-market correlation
# ---------------------------------------------------------------------------


def _pillar_cross(
    closes_1m: Sequence[float], open_market_closes: Optional[Mapping[str, Sequence[float]]]
) -> tuple[float, str]:
    if not open_market_closes:
        return 1.0, "no_open_trades"
    if not closes_1m or len(closes_1m) < 20:
        return 1.0, "self_insufficient"
    max_corr = 0.0
    matched = "none"
    for mkt, other_closes in open_market_closes.items():
        c = _correlation(closes_1m, other_closes)
        if c is None:
            continue
        if c > max_corr:
            max_corr = c
            matched = mkt
    # max_corr of 0.7 = highly correlated → score 0.3
    score = 1.0 - _clip01(max_corr)
    return _clip01(score), f"max_corr_{max_corr:.2f}_with_{matched}"


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------


def compute_entry_confidence(
    closes_1m: Sequence[float],
    highs_1m: Sequence[float],
    lows_1m: Sequence[float],
    volumes_1m: Sequence[float],
    *,
    ml_info: Optional[Mapping[str, Any]] = None,
    regime: str = "neutral",
    open_market_closes: Optional[Mapping[str, Sequence[float]]] = None,
    min_threshold: float = 0.55,
) -> EntryConfidenceResult:
    """Compute the 6-pillar entry confidence score.

    Returns an :class:`EntryConfidenceResult` with the geometric mean and
    sub-scores. Caller decides how to act on `passed`.
    """
    rsi_val: Optional[float] = None
    if ml_info:
        rsi_val = ml_info.get("rsi")  # type: ignore[assignment]
        if rsi_val is not None:
            rsi_val = _safe_float(rsi_val)

    pa, ra = _pillar_trend(closes_1m)
    pb, rb = _pillar_momentum(rsi_val, regime=regime)
    pc, rc = _pillar_volume(volumes_1m)
    pd, rd = _pillar_volatility(highs_1m, lows_1m, closes_1m)
    pe, re = _pillar_ml(ml_info)
    pf, rf = _pillar_cross(closes_1m, open_market_closes)

    pillars = {"trend": pa, "momentum": pb, "volume": pc, "volatility": pd, "ml": pe, "cross": pf}
    reasons = {"trend": ra, "momentum": rb, "volume": rc, "volatility": rd, "ml": re, "cross": rf}

    # Geometric mean — but guard against 0.0 in any pillar wiping the whole score.
    # Floor each pillar at 0.05 so a single zero doesn't make the result undefined.
    pillar_vals = [max(v, 0.05) for v in pillars.values()]
    product = 1.0
    for v in pillar_vals:
        product *= v
    confidence = product ** (1.0 / len(pillar_vals))
    weakest = min(pillars.items(), key=lambda kv: kv[1])[0]

    return EntryConfidenceResult(
        confidence=confidence,
        pillars=pillars,
        reasons=reasons,
        passed=confidence >= float(min_threshold),
        weakest_pillar=weakest,
    )


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def is_confidence_enabled(config: Mapping[str, Any]) -> bool:
    return bool(config.get("ENTRY_CONFIDENCE_ENABLED", False))


def min_confidence_threshold(config: Mapping[str, Any]) -> float:
    try:
        return float(config.get("ENTRY_CONFIDENCE_MIN", 0.55))
    except Exception:
        return 0.55
