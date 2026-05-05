"""bot.ai_regime — AI heartbeat-based regime bias for position sizing.

Extracted from `trailing_bot.py` (#066 batch 3). Reads `AI_HEARTBEAT_FILE` and
returns a `(regime_name, size_multiplier)` tuple, with simple time-based cache.
All thresholds/multipliers come from `state.CONFIG`.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Tuple

from bot.shared import state

_CACHE: Dict[str, Any] = {"ts": 0.0, "value": ("neutral", 1.0)}


def _cfg_float(key: str, default: float) -> float:
    try:
        return float(state.CONFIG.get(key, default))
    except Exception:
        return default


def _cfg_int(key: str, default: int) -> int:
    try:
        return int(state.CONFIG.get(key, default))
    except Exception:
        return default


def get_ai_regime_bias() -> Tuple[str, float]:
    cfg = state.CONFIG
    neutral_mult = _cfg_float("AI_REGIME_NEUTRAL_SIZE_MULTIPLIER", 1.0)
    defensive_mult = _cfg_float("AI_REGIME_DEFENSIVE_SIZE_MULTIPLIER", 0.6)
    halt_mult = _cfg_float("AI_REGIME_HALT_SIZE_MULTIPLIER", 0.0)
    aggressive_mult = _cfg_float("AI_REGIME_AGGRESSIVE_SIZE_MULTIPLIER", 1.2)

    defensive_count = max(0, _cfg_int("AI_REGIME_DEFENSIVE_CRITICAL_COUNT", 1))
    halt_count = max(defensive_count, _cfg_int("AI_REGIME_HALT_CRITICAL_COUNT", 3))
    cache_seconds = max(10, _cfg_int("AI_REGIME_CACHE_SECONDS", 60))
    stale_seconds = max(60, _cfg_int("AI_HEARTBEAT_STALE_SECONDS", 900))
    heartbeat_path = cfg.get("AI_HEARTBEAT_FILE", "data/ai_heartbeat.json")

    now = time.time()
    cached = _CACHE.get("value")
    if cached and (now - float(_CACHE.get("ts", 0.0))) < cache_seconds:
        return cached  # type: ignore[return-value]

    regime = "neutral"
    multiplier = neutral_mult
    try:
        path = Path(heartbeat_path)
        data: Dict[str, Any] = {}
        if path.exists():
            with path.open("r", encoding="utf-8") as fh:
                loaded = json.load(fh) or {}
                data = loaded if isinstance(loaded, dict) else {}
        ts = float(data.get("ts", 0) or 0)
        stale = not ts or (now - ts) > stale_seconds
        critical = int(data.get("critical_suggestions", 0) or 0)
        declared_regime = str(data.get("regime") or "").lower()
        if critical >= halt_count:
            regime = "halt"
            multiplier = halt_mult
        elif critical >= defensive_count:
            regime = "defensive"
            multiplier = defensive_mult
        elif declared_regime == "aggressive":
            regime = "aggressive"
            multiplier = aggressive_mult
        else:
            regime = declared_regime or "neutral"
            multiplier = neutral_mult
        if stale and regime != "halt":
            regime = "neutral"
            multiplier = neutral_mult
            try:
                state.log(f"AI regime fallback to neutral (stale heartbeat: {int(now - ts)}s old)", level="debug")
            except Exception:
                pass
    except Exception:
        regime = "halt"
        multiplier = halt_mult

    _CACHE["value"] = (regime, multiplier)
    _CACHE["ts"] = now
    return regime, multiplier
