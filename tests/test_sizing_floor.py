# -*- coding: utf-8 -*-
"""Tests for bot.sizing_floor."""
from __future__ import annotations

from bot.sizing_floor import enforce_size_floor


class TestSizeFloorBasic:
    def test_above_abs_min_passes_through(self):
        result = enforce_size_floor("XRP-EUR", 100.0, score=10.0, eur_balance=500.0, cfg={})
        assert result == 100.0

    def test_below_soft_min_aborts(self):
        result = enforce_size_floor("XRP-EUR", 30.0, score=10.0, eur_balance=500.0, cfg={})
        assert result is None

    def test_between_soft_and_abs_bumps_up_when_balance_allows(self):
        result = enforce_size_floor("XRP-EUR", 60.0, score=10.0, eur_balance=500.0, cfg={})
        assert result == 75.0

    def test_between_soft_and_abs_aborts_when_balance_too_low(self):
        # Need at least 75 * 1.05 = 78.75 to bump
        result = enforce_size_floor("XRP-EUR", 60.0, score=10.0, eur_balance=70.0, cfg={})
        assert result is None

    def test_high_conviction_bypass_allows_proposed(self):
        # score ≥ 14.0 with proposed in soft-abs band returns proposed unchanged
        result = enforce_size_floor("XRP-EUR", 60.0, score=15.0, eur_balance=70.0, cfg={})
        assert result == 60.0

    def test_dca_buys_skip_floor_entirely(self):
        # Even tiny DCAs must pass — they extend an existing position
        result = enforce_size_floor("XRP-EUR", 10.0, score=0.0, eur_balance=20.0, is_dca=True, cfg={})
        assert result == 10.0

    def test_disabled_via_config_passes_anything(self):
        cfg = {"POSITION_SIZE_FLOOR_ENABLED": False}
        result = enforce_size_floor("XRP-EUR", 5.0, score=0.0, eur_balance=0.0, cfg=cfg)
        assert result == 5.0


class TestSizeFloorOverrides:
    def test_custom_thresholds_via_config(self):
        cfg = {
            "POSITION_SIZE_ABS_MIN_EUR": 200.0,
            "POSITION_SIZE_SOFT_MIN_EUR": 100.0,
            "POSITION_SIZE_HIGH_CONVICTION_SCORE": 20.0,
        }
        # 150 EUR is between custom soft (100) and abs (200), score below conviction
        result = enforce_size_floor("XRP-EUR", 150.0, score=10.0, eur_balance=500.0, cfg=cfg)
        assert result == 200.0  # bumped to custom abs min

    def test_log_callable_invoked(self):
        captured = []

        def fake_log(msg, level="info"):
            captured.append((msg, level))

        enforce_size_floor("XRP-EUR", 10.0, score=0.0, eur_balance=100.0, cfg={}, log=fake_log)
        assert len(captured) == 1
        assert "soft_min" in captured[0][0].lower() or "abort" in captured[0][0].lower()
