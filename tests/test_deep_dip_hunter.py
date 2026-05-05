# -*- coding: utf-8 -*-
"""Tests for core.deep_dip_hunter."""

from __future__ import annotations

import pytest

from core.deep_dip_hunter import detect_deep_dip


def _candle(ts: int, o: float, h: float, lo: float, c: float, v: float = 1000.0):
    return [ts, o, h, lo, c, v]


def _crash_then_stabilise(peak: float = 100.0, bottom: float = 70.0,
                          stab_close: float = 73.0, n_total: int = 50,
                          stab_hours: int = 4):
    """Build a candle series that:
      - starts at `peak`
      - crashes linearly to `bottom` over (n_total - stab_hours) hours
      - stabilises at `stab_close` (with last bar green) for `stab_hours` hours
    """
    out = []
    crash_bars = n_total - stab_hours
    for i in range(crash_bars):
        frac = i / max(1, crash_bars - 1)
        price = peak - (peak - bottom) * frac
        out.append(_candle(i, price, price * 1.005, price * 0.99, price))
    # stabilisation: oscillate around stab_close, last bar GREEN
    for i in range(stab_hours):
        ts = crash_bars + i
        if i == stab_hours - 1:
            # last bar: green
            out.append(_candle(ts, stab_close * 0.995, stab_close * 1.01,
                               stab_close * 0.99, stab_close))
        else:
            out.append(_candle(ts, stab_close, stab_close * 1.005,
                               stab_close * 0.995, stab_close * 0.998))
    return out


class TestDeepDipBasics:
    def test_disabled_returns_inactive(self):
        candles = _crash_then_stabilise()
        active, boost, reason, _ = detect_deep_dip(
            "TEST-EUR", candles, 1_000_000, {"DEEP_DIP_HUNTER_ENABLED": False}
        )
        assert not active
        assert boost == 0.0
        assert reason == "disabled"

    def test_empty_market_returns_inactive(self):
        active, _, reason, _ = detect_deep_dip("", [], 0, {})
        assert not active
        assert reason == "no_market"

    def test_blacklisted_market_skipped(self):
        candles = _crash_then_stabilise()
        active, _, reason, _ = detect_deep_dip(
            "DOT-EUR", candles, 1_000_000, {}, blacklist=["DOT-EUR"]
        )
        assert not active
        assert reason == "blacklisted"

    def test_blacklist_case_insensitive(self):
        candles = _crash_then_stabilise()
        active, _, reason, _ = detect_deep_dip(
            "dot-eur", candles, 1_000_000, {}, blacklist=["DOT-EUR"]
        )
        assert not active
        assert reason == "blacklisted"


class TestQualityGates:
    def test_insufficient_candles(self):
        candles = [_candle(i, 100, 101, 99, 100) for i in range(10)]
        active, _, reason, _ = detect_deep_dip("X-EUR", candles, 1_000_000, {})
        assert not active
        assert reason == "insufficient_candles"

    def test_no_deep_dip(self):
        # Only 5% drop — below threshold
        candles = _crash_then_stabilise(peak=100, bottom=95, stab_close=96)
        active, _, reason, _ = detect_deep_dip("X-EUR", candles, 1_000_000, {})
        assert not active
        assert reason == "no_deep_dip"

    def test_rug_too_deep_skipped(self):
        # 70% drop — likely a rug
        candles = _crash_then_stabilise(peak=100, bottom=30, stab_close=31)
        active, _, reason, _ = detect_deep_dip("X-EUR", candles, 1_000_000, {})
        assert not active
        assert reason == "rug_too_deep"

    def test_low_volume_blocks(self):
        candles = _crash_then_stabilise()
        active, _, reason, _ = detect_deep_dip(
            "X-EUR", candles, 100_000, {}  # below 500k default
        )
        assert not active
        assert reason == "low_volume"


class TestStabilisation:
    def test_active_when_dip_and_bounce(self):
        candles = _crash_then_stabilise(peak=100, bottom=70, stab_close=73)
        active, boost, reason, details = detect_deep_dip(
            "WIF-EUR", candles, 1_000_000, {}
        )
        assert active is True
        assert boost == 5.0
        assert "deep_dip_active" in reason
        assert details["drop_pct"] >= 25.0
        assert details["bounce_from_low_pct"] >= 1.0

    def test_still_falling_blocks(self):
        # Build a series where last bar IS the absolute low — falling knife
        candles = []
        for i in range(50):
            price = 100 - i * 0.6  # crashes throughout
            candles.append(_candle(i, price + 0.5, price + 1, price - 0.5, price))
        active, _, reason, _ = detect_deep_dip("X-EUR", candles, 1_000_000, {})
        # Either no_bounce_yet or still_falling
        assert not active
        assert reason in ("still_falling", "no_bounce_yet", "no_green_tick")


class TestConfigOverrides:
    def test_custom_score_boost(self):
        candles = _crash_then_stabilise()
        _, boost, _, _ = detect_deep_dip(
            "X-EUR", candles, 1_000_000,
            {"DEEP_DIP_SCORE_BOOST": 7.5}
        )
        assert boost == 7.5

    def test_custom_min_drop_threshold(self):
        # 15% drop only, but config lowers threshold to 10%
        candles = _crash_then_stabilise(peak=100, bottom=85, stab_close=86)
        active, _, _, _ = detect_deep_dip(
            "X-EUR", candles, 1_000_000,
            {"DEEP_DIP_MIN_DROP_PCT": 10.0}
        )
        assert active is True


class TestRobustness:
    def test_bad_candle_format(self):
        candles = [["bad"], ["data"]] * 30
        active, _, reason, _ = detect_deep_dip("X-EUR", candles, 1_000_000, {})
        assert not active
        assert reason in ("bad_candle_format", "insufficient_candles")

    def test_no_volume_data_passes_volume_gate(self):
        # When volume_24h_eur=0 (unknown), the gate should NOT block
        candles = _crash_then_stabilise()
        active, _, _, _ = detect_deep_dip("X-EUR", candles, 0, {})
        assert active is True
