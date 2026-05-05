"""Per-market trailing parameters — top performers (BTC/ETH/SOL) get tuned configs.

Lookup order:
  1. config['PER_MARKET_TRAILING'][market] (runtime override)
  2. PER_MARKET_DEFAULTS in this module (curated defaults)
  3. Global config keys (TRAILING_ACTIVATION_PCT, BASE_TRAILING_PCT, etc.)

Pure helper — never raises. Returns dict with keys:
  trailing_activation_pct, base_trailing_pct, cost_buffer_pct.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

# Curated per-market defaults (tuned 2026-04-30 from #064 backtest review):
#  - BTC/ETH: tight trailing (less volatile, smaller % moves matter)
#  - SOL: medium (more volatile than BTC/ETH, less than alts)
PER_MARKET_DEFAULTS: Dict[str, Dict[str, float]] = {
    "BTC-EUR": {
        "trailing_activation_pct": 1.0,
        "base_trailing_pct": 0.6,
        "cost_buffer_pct": 0.4,
    },
    "ETH-EUR": {
        "trailing_activation_pct": 1.2,
        "base_trailing_pct": 0.7,
        "cost_buffer_pct": 0.5,
    },
    "SOL-EUR": {
        "trailing_activation_pct": 1.5,
        "base_trailing_pct": 0.9,
        "cost_buffer_pct": 0.6,
    },
}


def _as_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except Exception:
        return default


def get_trailing_params(market: str, config: Optional[Mapping[str, Any]] = None) -> Dict[str, float]:
    """Resolve trailing params for a market with override → default → global fallback chain."""
    cfg = config or {}
    global_act = _as_float(cfg.get("TRAILING_ACTIVATION_PCT", 1.5), 1.5)
    global_base = _as_float(cfg.get("BASE_TRAILING_PCT", 0.8), 0.8)
    global_buf = _as_float(cfg.get("COST_BUFFER_PCT", 0.5), 0.5)

    fallback = {
        "trailing_activation_pct": global_act,
        "base_trailing_pct": global_base,
        "cost_buffer_pct": global_buf,
    }

    overrides = cfg.get("PER_MARKET_TRAILING") or {}
    if isinstance(overrides, Mapping):
        ov = overrides.get(market)
        if isinstance(ov, Mapping):
            return {
                "trailing_activation_pct": _as_float(
                    ov.get("trailing_activation_pct"), fallback["trailing_activation_pct"]
                ),
                "base_trailing_pct": _as_float(ov.get("base_trailing_pct"), fallback["base_trailing_pct"]),
                "cost_buffer_pct": _as_float(ov.get("cost_buffer_pct"), fallback["cost_buffer_pct"]),
            }

    if market in PER_MARKET_DEFAULTS:
        d = PER_MARKET_DEFAULTS[market]
        return {
            "trailing_activation_pct": _as_float(d.get("trailing_activation_pct"), fallback["trailing_activation_pct"]),
            "base_trailing_pct": _as_float(d.get("base_trailing_pct"), fallback["base_trailing_pct"]),
            "cost_buffer_pct": _as_float(d.get("cost_buffer_pct"), fallback["cost_buffer_pct"]),
        }

    return fallback
