# -*- coding: utf-8 -*-
"""Kill-Zone Filter — anti-XGBoost veto layer.

Filters fresh entries based on patterns mined from the bot's OWN historical
losing trades (see tmp/find_kill_zones.py). Cross-validated decision tree on
658 production trades found these patterns lead to ~20% win-rate (vs 61% baseline):

  - RSI < 45 + low 1m volume → 20.8% win
  - Markets in historical blacklist (USDC-EUR, DOT-EUR, ADA-EUR) → ~0-30% win
  - Price extended >80% above short MA → 26% win

Backtest impact: blocking 13% of trades raises overall win-rate +6.3pp.

Pure functions — no I/O, safe to call from anywhere. Returns (blocked, reason).
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple


# Mined from production data (870 closed trades, see tmp/backtest_all_ideas.py).
# Markets where the bot historically loses money (Wilson lower bound win-rate <40%
# OR negative average PnL with n>=15).
DEFAULT_BLACKLIST = (
    "USDC-EUR",  # 0/24 win-rate
    "DOT-EUR",   # 16% / 61 trades / -€35
    "ADA-EUR",   # 24% / 21 / -€17
    "INJ-EUR",   # 29% / 21 / -€89
    "SOL-EUR",   # 46% / 26 / -€30
    "AVAX-EUR",  # 48% / 23 / -€10
    "XRP-EUR",   # 54% / 37 / -€13
    "ZEUS-EUR",  # 42% / 19 — outlier risk (1 mega-winner skews stats)
)

# Markets with structural high win-rate (Wilson lower bound >=70% AND profitable).
# These get a score boost so they're more likely to be picked by the entry scanner.
DEFAULT_WHITELIST = (
    "WIF-EUR",      # 100% / 95 trades / +€552
    "ACT-EUR",      # 97%  / 32 / +€28
    "MOODENG-EUR",  # 92%  / 26 / +€38
    "PTB-EUR",      # 91%  / 23 / +€68
)


def _as_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def is_kill_zone(
    market: str,
    features: Optional[Mapping[str, Any]] = None,
    config: Optional[Mapping[str, Any]] = None,
) -> Tuple[bool, str]:
    """Return (blocked, reason). Blocked=True means do NOT enter this trade.

    `features` may contain: rsi (0-100), volume_1m (sum recent 1m volume),
    price_to_sma (current_price / sma_short, 1.0 = at MA), macd.
    Missing features mean the corresponding rule is skipped (graceful).
    """
    cfg = config or {}
    if not bool(cfg.get("KILL_ZONE_ENABLED", True)):
        return False, ""

    mkt_upper = market.upper() if isinstance(market, str) else ""

    # Rule 0 — whitelist takes precedence (high-quality markets bypass all filters)
    whitelist = cfg.get("KILL_ZONE_WHITELIST", DEFAULT_WHITELIST) or ()
    try:
        wl = tuple(str(m).upper() for m in whitelist)
    except TypeError:
        wl = DEFAULT_WHITELIST
    if mkt_upper in wl:
        return False, ""

    # Rule 1 — hard blacklist (free, always evaluated)
    blacklist = cfg.get("KILL_ZONE_MARKETS", DEFAULT_BLACKLIST) or ()
    try:
        bl = tuple(str(m).upper() for m in blacklist)
    except TypeError:
        bl = DEFAULT_BLACKLIST
    if mkt_upper in bl:
        return True, "kz_blacklist"

    feats = features or {}

    # Rule 2 — RSI < 45 combined with low volume (53 trades, 20.8% win in archive)
    rsi_thr = _as_float(cfg.get("KILL_ZONE_RSI_MAX", 45.0), 45.0)
    vol_thr = _as_float(cfg.get("KILL_ZONE_VOL_MIN", 5000.0), 5000.0)
    rsi = feats.get("rsi")
    vol = feats.get("volume_1m", feats.get("volume"))
    if rsi is not None and vol is not None:
        if _as_float(rsi, 50.0) < rsi_thr and _as_float(vol, 0.0) < vol_thr:
            return True, "kz_rsi_low_vol_low"

    # Rule 3 — price extended too far above short MA (65 trades, 26.2% win)
    ext_thr = _as_float(cfg.get("KILL_ZONE_PRICE_EXT", 1.8), 1.8)
    p2sma = feats.get("price_to_sma")
    if p2sma is not None and _as_float(p2sma, 1.0) > ext_thr:
        return True, "kz_price_extended"

    return False, ""


def compute_features_from_candles(candles_1m) -> dict:
    """Helper: derive the feature dict from a 1m candle sequence.

    Best-effort — returns an empty dict if computation fails. Pure function.
    Candle format: [timestamp, open, high, low, close, volume].
    """
    try:
        from core.indicators import close_prices, rsi as _rsi, sma as _sma  # type: ignore
    except Exception:
        return {}
    try:
        closes = close_prices(candles_1m)
        if not closes or len(closes) < 20:
            return {}
        rsi_val = _rsi(closes, period=14)
        sma_short = _sma(closes, 10)
        cur = float(closes[-1])
        feats = {}
        if rsi_val is not None:
            feats["rsi"] = float(rsi_val)
        if sma_short:
            feats["price_to_sma"] = cur / float(sma_short) if float(sma_short) > 0 else 1.0
        # 1m rolling 30-bar volume sum
        try:
            vols = [float(c[5]) for c in candles_1m[-30:] if len(c) > 5]
            if vols:
                feats["volume_1m"] = sum(vols)
        except Exception:
            pass
        return feats
    except Exception:
        return {}


def whitelist_score_boost(
    market: str,
    config: Optional[Mapping[str, Any]] = None,
) -> float:
    """Return a score bonus to add for whitelisted high-potential markets.

    Returns 0.0 if market not whitelisted, feature disabled, or input invalid.
    Default boost = +2.0 (enough to push a borderline score over the 7.0
    MIN_SCORE_TO_BUY threshold but not enough to bypass quality filters).
    """
    cfg = config or {}
    if not bool(cfg.get("KILL_ZONE_ENABLED", True)):
        return 0.0
    if not bool(cfg.get("WHITELIST_BOOST_ENABLED", True)):
        return 0.0
    if not isinstance(market, str):
        return 0.0
    whitelist = cfg.get("KILL_ZONE_WHITELIST", DEFAULT_WHITELIST) or ()
    try:
        wl = tuple(str(m).upper() for m in whitelist)
    except TypeError:
        wl = DEFAULT_WHITELIST
    if market.upper() not in wl:
        return 0.0
    return _as_float(cfg.get("WHITELIST_SCORE_BOOST", 2.0), 2.0)
