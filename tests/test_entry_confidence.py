"""Tests for bot.entry_confidence — 6-pillar entry-confidence framework."""
from __future__ import annotations

import math

import pytest

from bot.entry_confidence import (
    EntryConfidenceResult,
    compute_entry_confidence,
    is_confidence_enabled,
    min_confidence_threshold,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bullish_uptrend(n: int = 120, base: float = 100.0, step: float = 0.5) -> list[float]:
    return [base + step * i for i in range(n)]


def _flat(n: int = 120, base: float = 100.0, jitter: float = 0.05) -> list[float]:
    out = []
    for i in range(n):
        out.append(base + jitter * (1 if i % 2 == 0 else -1))
    return out


def _bearish_downtrend(n: int = 120, base: float = 100.0, step: float = 0.4) -> list[float]:
    return [base - step * i for i in range(n)]


def _make_hl_from_closes(closes: list[float], spread_pct: float = 0.005) -> tuple[list[float], list[float]]:
    highs = [c * (1 + spread_pct) for c in closes]
    lows = [c * (1 - spread_pct) for c in closes]
    return highs, lows


def _make_volumes(n: int = 120, base: float = 1000.0) -> list[float]:
    return [base for _ in range(n)]


# ---------------------------------------------------------------------------
# compute_entry_confidence — happy paths
# ---------------------------------------------------------------------------

class TestComputeEntryConfidence:
    def test_returns_result_dataclass(self):
        closes = _bullish_uptrend()
        h, lo = _make_hl_from_closes(closes)
        v = _make_volumes()
        res = compute_entry_confidence(closes, h, lo, v, ml_info={"rsi": 55, "ml_signal": 1, "ml_confidence": 0.8})
        assert isinstance(res, EntryConfidenceResult)
        assert 0.0 <= res.confidence <= 1.0
        assert set(res.pillars.keys()) == {"trend", "momentum", "volume", "volatility", "ml", "cross"}

    def test_strong_bullish_setup_high_confidence(self):
        # Uptrend + good RSI + adequate volume + reasonable volatility + ML-buy + no open trades
        closes = _bullish_uptrend()
        h, lo = _make_hl_from_closes(closes, spread_pct=0.008)
        v = _make_volumes(base=1500)
        # Spike last 5 volumes to 1.5x for the volume pillar
        v[-5:] = [2200] * 5
        ml_info = {"rsi": 58, "ml_signal": 1, "ml_confidence": 0.85}
        res = compute_entry_confidence(closes, h, lo, v, ml_info=ml_info, regime="trending_up")
        assert res.confidence >= 0.55, f"expected high confidence, got {res.confidence:.3f} pillars={res.pillars}"
        assert res.pillars["trend"] >= 0.5

    def test_bearish_downtrend_low_confidence(self):
        closes = _bearish_downtrend()
        h, lo = _make_hl_from_closes(closes)
        v = _make_volumes()
        ml_info = {"rsi": 30, "ml_signal": -1, "ml_confidence": 0.7}
        res = compute_entry_confidence(closes, h, lo, v, ml_info=ml_info)
        assert res.confidence < 0.5
        # trend should be 0
        assert res.pillars["trend"] <= 0.5

    def test_extreme_rsi_kills_momentum_pillar(self):
        closes = _bullish_uptrend()
        h, lo = _make_hl_from_closes(closes)
        v = _make_volumes()
        ml_info = {"rsi": 85, "ml_signal": 1, "ml_confidence": 0.7}  # overbought
        res = compute_entry_confidence(closes, h, lo, v, ml_info=ml_info)
        assert res.pillars["momentum"] <= 0.2
        assert res.weakest_pillar == "momentum"

    def test_zero_pillar_floored_not_zero_total(self):
        # If a pillar would be 0, it should be floored at 0.05 so total isn't 0.
        closes = _bullish_uptrend()
        h, lo = _make_hl_from_closes(closes)
        v = _make_volumes()
        # No ML info → ml pillar = 0.5; rsi extreme → momentum = 0.1
        ml_info = {"rsi": 90, "ml_signal": 0, "ml_confidence": 0.0}
        res = compute_entry_confidence(closes, h, lo, v, ml_info=ml_info)
        assert res.confidence > 0.0  # floored, never zero

    def test_passed_flag_respects_threshold(self):
        closes = _bullish_uptrend()
        h, lo = _make_hl_from_closes(closes)
        v = _make_volumes()
        v[-5:] = [2200] * 5
        ml_info = {"rsi": 58, "ml_signal": 1, "ml_confidence": 0.85}
        res_pass = compute_entry_confidence(closes, h, lo, v, ml_info=ml_info, regime="trending_up", min_threshold=0.3)
        res_fail = compute_entry_confidence(closes, h, lo, v, ml_info=ml_info, regime="trending_up", min_threshold=0.99)
        assert res_pass.passed is True
        assert res_fail.passed is False


# ---------------------------------------------------------------------------
# Pillar-specific behaviours
# ---------------------------------------------------------------------------

class TestPillars:
    def test_volume_pillar_dry_market_low(self):
        closes = _bullish_uptrend()
        h, lo = _make_hl_from_closes(closes)
        v = _make_volumes(base=1000)
        v[-5:] = [200] * 5  # dry
        res = compute_entry_confidence(closes, h, lo, v, ml_info={"rsi": 55, "ml_signal": 1, "ml_confidence": 0.7})
        assert res.pillars["volume"] <= 0.3

    def test_volume_pillar_pump_low(self):
        closes = _bullish_uptrend()
        h, lo = _make_hl_from_closes(closes)
        v = _make_volumes(base=1000)
        v[-5:] = [10000] * 5  # pump
        res = compute_entry_confidence(closes, h, lo, v, ml_info={"rsi": 55, "ml_signal": 1, "ml_confidence": 0.7})
        assert res.pillars["volume"] <= 0.4

    def test_volatility_pillar_too_quiet(self):
        # Tiny price changes → atr_pct very small
        closes = [100.0 + (0.001 if i % 2 == 0 else -0.001) for i in range(120)]
        h, lo = _make_hl_from_closes(closes, spread_pct=0.00005)
        v = _make_volumes()
        res = compute_entry_confidence(closes, h, lo, v, ml_info={"rsi": 55, "ml_signal": 1, "ml_confidence": 0.7})
        assert res.pillars["volatility"] <= 0.3

    def test_volatility_pillar_too_wild(self):
        # Huge swings
        closes = [100.0 + (15 if i % 2 == 0 else -15) for i in range(120)]
        h, lo = _make_hl_from_closes(closes, spread_pct=0.05)
        v = _make_volumes()
        res = compute_entry_confidence(closes, h, lo, v, ml_info={"rsi": 55, "ml_signal": 1, "ml_confidence": 0.7})
        assert res.pillars["volatility"] <= 0.3

    def test_cross_pillar_high_correlation_lowers_score(self):
        closes = _bullish_uptrend()
        h, lo = _make_hl_from_closes(closes)
        v = _make_volumes()
        # Open trade has identical price series → correlation ≈ 1
        open_closes = {"BTC-EUR": list(closes)}
        res_corr = compute_entry_confidence(
            closes, h, lo, v,
            ml_info={"rsi": 55, "ml_signal": 1, "ml_confidence": 0.7},
            open_market_closes=open_closes,
        )
        assert res_corr.pillars["cross"] <= 0.2  # heavily correlated → low score

        res_no_open = compute_entry_confidence(
            closes, h, lo, v,
            ml_info={"rsi": 55, "ml_signal": 1, "ml_confidence": 0.7},
        )
        assert res_no_open.pillars["cross"] == 1.0

    def test_ml_pillar_buy_with_high_conf(self):
        closes = _bullish_uptrend()
        h, lo = _make_hl_from_closes(closes)
        v = _make_volumes()
        res = compute_entry_confidence(closes, h, lo, v, ml_info={"rsi": 55, "ml_signal": "buy", "ml_confidence": 0.9})
        assert res.pillars["ml"] >= 0.9

    def test_ml_pillar_sell_signal_low(self):
        closes = _bullish_uptrend()
        h, lo = _make_hl_from_closes(closes)
        v = _make_volumes()
        res = compute_entry_confidence(closes, h, lo, v, ml_info={"rsi": 55, "ml_signal": "sell", "ml_confidence": 0.8})
        assert res.pillars["ml"] <= 0.15


# ---------------------------------------------------------------------------
# Edge cases / robustness
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_inputs_dont_crash(self):
        res = compute_entry_confidence([], [], [], [], ml_info=None)
        assert isinstance(res, EntryConfidenceResult)
        assert 0.0 <= res.confidence <= 1.0

    def test_short_inputs_use_neutral_defaults(self):
        # Less than required data points → pillars default to 0.5
        closes = [100.0] * 10
        res = compute_entry_confidence(closes, closes, closes, closes, ml_info=None)
        assert all(0.0 <= v <= 1.0 for v in res.pillars.values())

    def test_no_ml_info_neutral(self):
        closes = _bullish_uptrend()
        h, lo = _make_hl_from_closes(closes)
        v = _make_volumes()
        res = compute_entry_confidence(closes, h, lo, v, ml_info=None)
        assert res.pillars["ml"] == 0.5
        assert res.pillars["momentum"] == 0.5  # rsi missing

    def test_nan_inf_in_inputs_safe(self):
        closes = [100.0, float("nan"), float("inf")] + _bullish_uptrend(n=60)
        h = list(closes)
        lo = list(closes)
        v = _make_volumes(n=63)
        # Should not raise
        res = compute_entry_confidence(closes, h, lo, v, ml_info={"rsi": 55})
        assert isinstance(res, EntryConfidenceResult)

    def test_as_dict_serializable(self):
        closes = _bullish_uptrend()
        h, lo = _make_hl_from_closes(closes)
        v = _make_volumes()
        res = compute_entry_confidence(closes, h, lo, v, ml_info={"rsi": 55, "ml_signal": 1, "ml_confidence": 0.7})
        d = res.as_dict()
        assert "confidence" in d
        assert "pillars" in d
        assert "passed" in d
        # All values json-serializable primitives
        import json
        json.dumps(d)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

class TestConfigHelpers:
    def test_is_enabled_default_false(self):
        assert is_confidence_enabled({}) is False

    def test_is_enabled_true(self):
        assert is_confidence_enabled({"ENTRY_CONFIDENCE_ENABLED": True}) is True

    def test_min_threshold_default(self):
        assert min_confidence_threshold({}) == pytest.approx(0.55)

    def test_min_threshold_custom(self):
        assert min_confidence_threshold({"ENTRY_CONFIDENCE_MIN": 0.7}) == pytest.approx(0.7)

    def test_min_threshold_invalid_falls_back(self):
        assert min_confidence_threshold({"ENTRY_CONFIDENCE_MIN": "abc"}) == pytest.approx(0.55)
