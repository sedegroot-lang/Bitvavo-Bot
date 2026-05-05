# -*- coding: utf-8 -*-
"""Position size floor — kills micro-trades that lose money to fees.

Backtested on March-April 2026 dataset (159 trades):
  bucket       n   avg_pnl    avg_ROI   verdict
  0-25 EUR    48   -€0.12    +0.81%    NETTO VERLIES (fees eten 0.5%)
  25-75 EUR   39   +€0.41    +0.91%    marginaal
  75-150 EUR  11   +€3.34    +2.95%    SWEET SPOT (3x betere ROI)
  150-400 EUR 23   +€1.91    +0.98%    sterk
  400+ EUR     2   +€11.24   +1.34%    klein sample

Rules:
  - proposed < SOFT_MIN: abort (always net negative)
  - SOFT_MIN <= proposed < ABS_MIN: bump to ABS_MIN if balance allows,
    otherwise allow only when score is high-conviction, else abort.
  - proposed >= ABS_MIN: pass through unchanged.

NOTE: DCA buys are exempt — they extend an existing position and the
total invested is what matters, not the size of the individual add.
"""

from __future__ import annotations

from typing import Optional

# Backtest-derived defaults; overridable via CONFIG keys
DEFAULT_ABS_MIN_POSITION_EUR = 75.0
DEFAULT_SOFT_MIN_POSITION_EUR = 50.0
DEFAULT_HIGH_CONVICTION_SCORE = 14.0


def _cfg_float(cfg, key: str, default: float) -> float:
    try:
        v = cfg.get(key, default)
        if v is None:
            return float(default)
        return float(v)
    except Exception:
        return float(default)


def enforce_size_floor(
    market: str,
    proposed_eur: float,
    *,
    score: float = 0.0,
    eur_balance: float = 0.0,
    is_dca: bool = False,
    cfg: Optional[dict] = None,
    log=None,
) -> Optional[float]:
    """Return adjusted size (float) or None to abort entry.

    Args:
        market: e.g. 'XRP-EUR'.
        proposed_eur: the size the upstream sizing logic suggested.
        score: signal score for high-conviction bypass.
        eur_balance: free EUR balance (used to decide if we can bump up).
        is_dca: skip the floor for DCA buys (entire position is what matters).
        cfg: optional dict with overrides for ABS_MIN/SOFT_MIN/conviction.
        log: optional callable(msg, level=...) for diagnostic output.
    """
    if is_dca:
        return float(proposed_eur)

    cfg = cfg or {}
    abs_min = _cfg_float(cfg, "POSITION_SIZE_ABS_MIN_EUR", DEFAULT_ABS_MIN_POSITION_EUR)
    soft_min = _cfg_float(cfg, "POSITION_SIZE_SOFT_MIN_EUR", DEFAULT_SOFT_MIN_POSITION_EUR)
    conviction_score = _cfg_float(cfg, "POSITION_SIZE_HIGH_CONVICTION_SCORE", DEFAULT_HIGH_CONVICTION_SCORE)

    enabled = bool(cfg.get("POSITION_SIZE_FLOOR_ENABLED", True))
    if not enabled:
        return float(proposed_eur)

    proposed = float(proposed_eur)

    def _log(msg: str, level: str = "info") -> None:
        if log is not None:
            try:
                log(msg, level=level)
            except Exception:
                pass

    if proposed < soft_min:
        _log(f"[SIZE-FLOOR] {market} {proposed:.2f} EUR < soft_min {soft_min:.0f} → abort", "info")
        return None

    if proposed < abs_min:
        if score >= conviction_score:
            _log(f"[SIZE-FLOOR] {market} high-conviction score={score:.1f}, allow {proposed:.2f} EUR", "info")
            return proposed
        # Try to bump up
        bumped = abs_min
        if eur_balance >= bumped * 1.05:
            _log(f"[SIZE-FLOOR] {market} bump {proposed:.2f} → {bumped:.2f} EUR", "info")
            return bumped
        _log(
            f"[SIZE-FLOOR] {market} {proposed:.2f} < abs_min {abs_min:.0f}, balance {eur_balance:.2f} insufficient → abort",
            "info",
        )
        return None

    return proposed
