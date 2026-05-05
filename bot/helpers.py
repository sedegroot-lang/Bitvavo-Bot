"""Pure helper/utility functions — no API or state dependencies.

Extracted from trailing_bot.py (Fase 3, Phase 1).
"""

from __future__ import annotations

from typing import Any, Optional


def as_bool(value: Any, default: bool = False) -> bool:
    """Convert any value to bool (handles str 'true'/'false', int, None)."""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "on"}:
            return True
        if lowered in {"false", "0", "no", "n", "off"}:
            return False
    try:
        return bool(int(value))
    except Exception:
        return bool(value) if value is not None else default


def as_int(value: Any, default: int = 0) -> int:
    """Convert any value to int, returning *default* on failure."""
    try:
        if value is None:
            return int(default)
        return int(value)
    except Exception:
        return int(default)


def as_float(value: Any, default: float = 0.0) -> float:
    """Convert any value to float, returning *default* on failure."""
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def clamp(val: float, lo: float, hi: float) -> float:
    """Clamp *val* between *lo* and *hi*."""
    try:
        return max(lo, min(hi, float(val)))
    except Exception:
        return lo


def safe_mul(a: Any, b: Any) -> Optional[float]:
    """Multiply two values, returning None on failure."""
    try:
        if a is None or b is None:
            return None
        return float(a) * float(b)
    except Exception:
        return None


def coerce_positive_float(value: Any) -> Optional[float]:
    """Return float(value) when finite and >0, otherwise None."""
    try:
        coerced = float(value)
    except (TypeError, ValueError):
        return None
    if coerced <= 0:
        return None
    try:
        import math

        if not math.isfinite(coerced):
            return None
    except Exception:
        pass
    return coerced
