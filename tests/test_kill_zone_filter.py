# -*- coding: utf-8 -*-
"""Tests for core/kill_zone_filter.py"""
from __future__ import annotations

import pytest

from core.kill_zone_filter import (
    DEFAULT_BLACKLIST,
    DEFAULT_WHITELIST,
    compute_features_from_candles,
    is_kill_zone,
    whitelist_score_boost,
)


class TestBlacklist:
    def test_default_blacklist_blocks_usdc(self):
        blocked, reason = is_kill_zone("USDC-EUR", {}, {})
        assert blocked is True
        assert reason == "kz_blacklist"

    def test_default_blacklist_blocks_dot(self):
        blocked, reason = is_kill_zone("DOT-EUR", {}, {})
        assert blocked is True

    def test_non_blacklisted_market_passes(self):
        blocked, reason = is_kill_zone("BTC-EUR", {}, {})
        assert blocked is False
        assert reason == ""

    def test_case_insensitive(self):
        blocked, _ = is_kill_zone("usdc-eur", {}, {})
        assert blocked is True

    def test_custom_blacklist_overrides(self):
        cfg = {"KILL_ZONE_MARKETS": ["TRUMP-EUR"]}
        # USDC no longer blocked
        b1, _ = is_kill_zone("USDC-EUR", {}, cfg)
        b2, _ = is_kill_zone("TRUMP-EUR", {}, cfg)
        assert b1 is False
        assert b2 is True


class TestRsiVolumeRule:
    def test_low_rsi_low_vol_blocks(self):
        feats = {"rsi": 35.0, "volume_1m": 2000.0}
        blocked, reason = is_kill_zone("BTC-EUR", feats, {})
        assert blocked is True
        assert reason == "kz_rsi_low_vol_low"

    def test_low_rsi_high_vol_passes(self):
        feats = {"rsi": 35.0, "volume_1m": 50000.0}
        blocked, _ = is_kill_zone("BTC-EUR", feats, {})
        assert blocked is False

    def test_high_rsi_low_vol_passes(self):
        feats = {"rsi": 60.0, "volume_1m": 1000.0}
        blocked, _ = is_kill_zone("BTC-EUR", feats, {})
        assert blocked is False

    def test_volume_alias(self):
        # accepts 'volume' alias (legacy feature dict)
        feats = {"rsi": 30.0, "volume": 100.0}
        blocked, _ = is_kill_zone("BTC-EUR", feats, {})
        assert blocked is True

    def test_missing_features_skip_rule(self):
        blocked, _ = is_kill_zone("BTC-EUR", {"rsi": 30.0}, {})
        assert blocked is False  # vol missing → rule skipped

    def test_threshold_override(self):
        cfg = {"KILL_ZONE_RSI_MAX": 40.0, "KILL_ZONE_VOL_MIN": 1000.0}
        # rsi 42 with low vol — would block at default 45, passes at 40
        b1, _ = is_kill_zone("BTC-EUR", {"rsi": 42.0, "volume_1m": 500.0}, cfg)
        assert b1 is False


class TestPriceExtended:
    def test_price_far_above_ma_blocks(self):
        feats = {"price_to_sma": 2.0}
        blocked, reason = is_kill_zone("BTC-EUR", feats, {})
        assert blocked is True
        assert reason == "kz_price_extended"

    def test_price_at_ma_passes(self):
        feats = {"price_to_sma": 1.05}
        blocked, _ = is_kill_zone("BTC-EUR", feats, {})
        assert blocked is False


class TestEnableFlag:
    def test_disabled_passes_everything(self):
        cfg = {"KILL_ZONE_ENABLED": False}
        feats = {"rsi": 30.0, "volume_1m": 100.0, "price_to_sma": 5.0}
        blocked, _ = is_kill_zone("USDC-EUR", feats, cfg)
        assert blocked is False


class TestComputeFeaturesFromCandles:
    def _candles(self, closes):
        # Bitvavo format: [ts, open, high, low, close, volume]
        return [[i * 60000, c, c * 1.01, c * 0.99, c, 100.0] for i, c in enumerate(closes)]

    def test_returns_dict_with_expected_keys(self):
        candles = self._candles([100.0 + i * 0.1 for i in range(50)])
        feats = compute_features_from_candles(candles)
        assert "rsi" in feats
        assert "price_to_sma" in feats
        assert "volume_1m" in feats
        assert feats["volume_1m"] == pytest.approx(30 * 100.0)

    def test_too_few_candles_returns_empty(self):
        feats = compute_features_from_candles(self._candles([100.0] * 5))
        assert feats == {}

    def test_invalid_candles_returns_empty(self):
        feats = compute_features_from_candles(None)
        assert feats == {}


def test_default_blacklist_constant():
    assert "USDC-EUR" in DEFAULT_BLACKLIST
    assert "DOT-EUR" in DEFAULT_BLACKLIST
    assert "ADA-EUR" in DEFAULT_BLACKLIST
    # Extended after backtest (FIX #079)
    assert "INJ-EUR" in DEFAULT_BLACKLIST
    assert "SOL-EUR" in DEFAULT_BLACKLIST


def test_default_whitelist_constant():
    assert "WIF-EUR" in DEFAULT_WHITELIST
    assert "ACT-EUR" in DEFAULT_WHITELIST
    assert "MOODENG-EUR" in DEFAULT_WHITELIST
    assert "PTB-EUR" in DEFAULT_WHITELIST


class TestWhitelist:
    def test_whitelist_bypasses_all_rules(self):
        # WIF-EUR is whitelisted: even with bad features it should pass
        feats = {"rsi": 30.0, "volume_1m": 100.0, "price_to_sma": 5.0}
        blocked, reason = is_kill_zone("WIF-EUR", feats, {})
        assert blocked is False
        assert reason == ""

    def test_whitelist_takes_precedence_over_blacklist(self):
        # If a market is on BOTH lists, whitelist wins
        cfg = {
            "KILL_ZONE_MARKETS": ["WIF-EUR"],
            "KILL_ZONE_WHITELIST": ["WIF-EUR"],
        }
        blocked, _ = is_kill_zone("WIF-EUR", {}, cfg)
        assert blocked is False

    def test_custom_whitelist_overrides_default(self):
        cfg = {"KILL_ZONE_WHITELIST": ["TRUMP-EUR"]}
        # WIF no longer auto-pass
        feats = {"rsi": 30.0, "volume_1m": 100.0}
        b1, _ = is_kill_zone("WIF-EUR", feats, cfg)
        # but TRUMP does
        b2, _ = is_kill_zone("TRUMP-EUR", feats, cfg)
        assert b1 is True  # gets blocked by RSI rule now
        assert b2 is False


class TestScoreBoost:
    def test_whitelisted_market_gets_default_boost(self):
        boost = whitelist_score_boost("WIF-EUR", {})
        assert boost == 2.0

    def test_non_whitelisted_market_gets_zero(self):
        boost = whitelist_score_boost("BTC-EUR", {})
        assert boost == 0.0

    def test_custom_boost_value(self):
        cfg = {"WHITELIST_SCORE_BOOST": 3.5}
        assert whitelist_score_boost("WIF-EUR", cfg) == 3.5

    def test_disabled_globally(self):
        cfg = {"KILL_ZONE_ENABLED": False}
        assert whitelist_score_boost("WIF-EUR", cfg) == 0.0

    def test_disabled_boost_only(self):
        cfg = {"WHITELIST_BOOST_ENABLED": False}
        assert whitelist_score_boost("WIF-EUR", cfg) == 0.0

    def test_invalid_market(self):
        assert whitelist_score_boost(None, {}) == 0.0
        assert whitelist_score_boost(123, {}) == 0.0

    def test_case_insensitive(self):
        assert whitelist_score_boost("wif-eur", {}) == 2.0
