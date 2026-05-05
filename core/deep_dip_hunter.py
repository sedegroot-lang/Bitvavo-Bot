# -*- coding: utf-8 -*-
"""Deep-Dip Hunter — detect markets that crashed -25%+ in 24-48h and are stabilising.

Pattern: when a quality market dumps hard (forced sellers exhausted) and the last
few hours show stabilisation (last close >= recent low + small green tick), there
is often a relief bounce of 8-20% within 24-72h. The standard signal pipeline
INTENTIONALLY avoids this (looks like falling knife), so this hunter runs as a
separate veto-bypass score booster.

Quality gates (must pass ALL):
  - Drawdown peak→now in last DEEP_DIP_LOOKBACK_HOURS >= DEEP_DIP_MIN_DROP_PCT
  - Last DEEP_DIP_STABILISE_HOURS show no new low (price has bottomed)
  - Last hour close > last hour open (small green confirmation)
  - 24h volume in EUR >= DEEP_DIP_MIN_VOLUME_EUR (avoid shitcoins)
  - Market not in kill_zone blacklist (these are blacklisted for a reason)

Returns a score boost (additive to normal signal score) when ALL gates pass.
This boost helps the dip get through MIN_SCORE_TO_BUY despite weak MACD/regime.

Pure-ish: takes pre-fetched 1h candles + 24h volume + blacklist set. No I/O.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence, Tuple


# ---------------------------------------------------------------------------
# Defaults (override via CONFIG keys with same name uppercased)
# ---------------------------------------------------------------------------
DEFAULT_LOOKBACK_HOURS = 48        # window to find peak high
DEFAULT_MIN_DROP_PCT = 25.0        # peak→now drawdown threshold
DEFAULT_STABILISE_HOURS = 4        # last N hours: no new low
DEFAULT_MIN_VOLUME_EUR = 500_000   # quality gate (no shitcoin moonshots)
DEFAULT_SCORE_BOOST = 5.0          # additive boost when active
DEFAULT_MAX_DROP_PCT = 60.0        # cap: -60%+ is a true rug, skip


def _as_float(v: Any, default: float) -> float:
    try:
        if v is None:
            return float(default)
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _as_int(v: Any, default: int) -> int:
    try:
        if v is None:
            return int(default)
        return int(v)
    except (TypeError, ValueError):
        return int(default)


def _as_bool(v: Any, default: bool) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on", "y", "t")
    try:
        return bool(v)
    except Exception:
        return default


def _norm_market(m: str) -> str:
    return (m or "").strip().upper()


def detect_deep_dip(
    market: str,
    candles_1h: Sequence[Sequence[Any]],
    volume_24h_eur: float,
    config: Mapping[str, Any] | None = None,
    blacklist: Iterable[str] | None = None,
) -> Tuple[bool, float, str, dict]:
    """Detect a deep-dip-with-stabilisation pattern.

    Args:
        market: e.g. "ZEUS-EUR".
        candles_1h: list of [ts, open, high, low, close, volume] from Bitvavo
                    (oldest first; newest last). Need at least lookback_hours+1.
        volume_24h_eur: 24h trading volume in EUR.
        config: CONFIG dict (uppercase keys).
        blacklist: set of UPPER-CASE markets to skip (kill_zone blacklist).

    Returns:
        (active, score_boost, reason, details_dict)
    """
    cfg = config or {}
    enabled = _as_bool(cfg.get("DEEP_DIP_HUNTER_ENABLED"), True)
    if not enabled:
        return False, 0.0, "disabled", {}

    m_up = _norm_market(market)
    if not m_up:
        return False, 0.0, "no_market", {}

    # Blacklist veto (these markets crashed for fundamental reasons)
    bl = {_norm_market(x) for x in (blacklist or ()) if x}
    if m_up in bl:
        return False, 0.0, "blacklisted", {"market": m_up}

    lookback = _as_int(cfg.get("DEEP_DIP_LOOKBACK_HOURS"), DEFAULT_LOOKBACK_HOURS)
    min_drop = _as_float(cfg.get("DEEP_DIP_MIN_DROP_PCT"), DEFAULT_MIN_DROP_PCT)
    max_drop = _as_float(cfg.get("DEEP_DIP_MAX_DROP_PCT"), DEFAULT_MAX_DROP_PCT)
    stab_hours = _as_int(cfg.get("DEEP_DIP_STABILISE_HOURS"), DEFAULT_STABILISE_HOURS)
    min_vol = _as_float(cfg.get("DEEP_DIP_MIN_VOLUME_EUR"), DEFAULT_MIN_VOLUME_EUR)
    boost = _as_float(cfg.get("DEEP_DIP_SCORE_BOOST"), DEFAULT_SCORE_BOOST)

    if not candles_1h or len(candles_1h) < max(lookback, stab_hours + 1):
        return False, 0.0, "insufficient_candles", {"have": len(candles_1h or []), "need": lookback}

    # Take last `lookback+1` candles
    window = list(candles_1h[-(lookback + 1):])

    # Parse OHLC: Bitvavo format is [ts, open, high, low, close, volume]
    try:
        highs = [float(c[2]) for c in window]
        lows = [float(c[3]) for c in window]
        opens = [float(c[1]) for c in window]
        closes = [float(c[4]) for c in window]
    except (IndexError, TypeError, ValueError):
        return False, 0.0, "bad_candle_format", {}

    if not closes:
        return False, 0.0, "empty_window", {}

    peak_high = max(highs)
    now_close = closes[-1]
    if peak_high <= 0:
        return False, 0.0, "bad_price", {}

    drop_pct = (peak_high - now_close) / peak_high * 100.0
    if drop_pct < min_drop:
        return False, 0.0, "no_deep_dip", {"drop_pct": round(drop_pct, 2)}
    if drop_pct > max_drop:
        return False, 0.0, "rug_too_deep", {"drop_pct": round(drop_pct, 2)}

    # Volume gate
    if volume_24h_eur and volume_24h_eur < min_vol:
        return False, 0.0, "low_volume", {"volume_eur": int(volume_24h_eur)}

    # Stabilisation: last `stab_hours` should NOT contain the absolute window low.
    # If the lowest low of the entire window is in the recent stabilisation hours,
    # we are still falling — skip.
    abs_low = min(lows)
    stab_lows = lows[-stab_hours:]
    if abs_low in stab_lows:
        # Allow if abs_low is NOT in the very last bar (one-bar tolerance)
        if lows[-1] == abs_low:
            return False, 0.0, "still_falling", {"low": abs_low, "now": now_close}

    # Last bar must be green-ish (close >= open or close >= prev close)
    last_open = opens[-1]
    last_close = closes[-1]
    if last_close < last_open and last_close < closes[-2]:
        return False, 0.0, "no_green_tick", {"open": last_open, "close": last_close}

    # Bounce-from-low confirmation: now_close should be at least 1% above abs_low
    if abs_low > 0:
        bounce_from_low = (now_close - abs_low) / abs_low * 100.0
        if bounce_from_low < 1.0:
            return False, 0.0, "no_bounce_yet", {"bounce_pct": round(bounce_from_low, 2)}
    else:
        bounce_from_low = 0.0

    details = {
        "peak_high": round(peak_high, 6),
        "now_close": round(now_close, 6),
        "abs_low": round(abs_low, 6),
        "drop_pct": round(drop_pct, 2),
        "bounce_from_low_pct": round(bounce_from_low, 2),
        "volume_24h_eur": int(volume_24h_eur or 0),
        "lookback_hours": lookback,
        "stab_hours": stab_hours,
    }
    reason = (
        f"deep_dip_active drop={drop_pct:.1f}% bounce={bounce_from_low:.1f}% "
        f"vol=€{int(volume_24h_eur or 0):,}"
    )
    return True, float(boost), reason, details
