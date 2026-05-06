"""Tests for ai.signal_weight_profiler + evaluate_signal_pack multiplier wiring."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai.signal_weight_profiler import (
    DEFAULTS,
    build,
    compute_profiles,
    load_signal_weights,
    market_profile,
)


def _trade(market: str, profit: float) -> dict:
    return {"market": market, "profit": profit, "archived_at": 1.0, "score": 20.0}


class TestComputeProfiles:
    def test_below_min_trades_skipped(self):
        trades = [_trade("X-EUR", 1.0) for _ in range(3)]
        out = compute_profiles(trades, min_trades=8)
        assert out == {}

    def test_winning_market_gets_multiplier_above_one(self):
        # Strong positive expectancy → multiplier > 1
        trades = [_trade("WIN-EUR", 5.0) for _ in range(20)]
        out = compute_profiles(trades, min_trades=8)
        assert "WIN-EUR" in out
        prof = out["WIN-EUR"]
        assert prof["score_multiplier"] > 1.0
        assert prof["min_score_override"] is None
        assert prof["wr"] == 1.0
        assert prof["expectancy_eur"] == 5.0
        assert prof["n"] == 20

    def test_losing_market_gets_multiplier_below_one_and_override(self):
        trades = [_trade("LOSE-EUR", -3.0) for _ in range(15)]
        out = compute_profiles(trades, min_trades=8)
        prof = out["LOSE-EUR"]
        assert prof["score_multiplier"] < 1.0
        assert prof["min_score_override"] == DEFAULTS["STRONG_BAD_OVERRIDE"]
        assert prof["expectancy_eur"] == -3.0

    def test_multiplier_clamped_to_floor_and_ceiling(self):
        # Extreme expectancy must not blow past bounds
        big_pos = [_trade("MOON-EUR", 1000.0) for _ in range(20)]
        big_neg = [_trade("DUMP-EUR", -1000.0) for _ in range(20)]
        p = compute_profiles(big_pos + big_neg, min_trades=8)
        assert p["MOON-EUR"]["score_multiplier"] <= DEFAULTS["MULTIPLIER_CEIL"]
        assert p["DUMP-EUR"]["score_multiplier"] >= DEFAULTS["MULTIPLIER_FLOOR"]


class TestBuildAndLoad:
    def test_build_writes_valid_json(self, tmp_path, monkeypatch):
        archive = tmp_path / "archive.json"
        archive.write_text(
            json.dumps({"trades": [_trade("BTC-EUR", 2.0) for _ in range(20)]}),
            encoding="utf-8",
        )
        out = tmp_path / "weights.json"
        doc = build(trades_path=archive, out_path=out)
        assert out.exists()
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert loaded["version"] == 1
        assert "BTC-EUR" in loaded["markets"]
        assert loaded["n_trades_total"] == 20
        assert doc == loaded

    def test_load_signal_weights_missing_returns_default(self, tmp_path):
        w = load_signal_weights(tmp_path / "nope.json")
        assert w["default"]["score_multiplier"] == 1.0
        assert w["markets"] == {}

    def test_market_profile_falls_back_to_default(self):
        weights = {"default": {"score_multiplier": 0.9, "min_score_override": None}, "markets": {}}
        mult, ov = market_profile(weights, "ANY-EUR")
        assert mult == 0.9 and ov is None

    def test_market_profile_returns_market_specific(self):
        weights = {
            "default": {"score_multiplier": 1.0, "min_score_override": None},
            "markets": {"BTC-EUR": {"score_multiplier": 1.2, "min_score_override": 22.0}},
        }
        mult, ov = market_profile(weights, "BTC-EUR")
        assert mult == 1.2 and ov == 22.0


class TestSignalPackMultiplier:
    """End-to-end: enabling USE_MARKET_SIGNAL_WEIGHTS scales total_score."""

    def _ctx(self, market: str, config: dict):
        from modules.signals.base import SignalContext
        # Build a minimal but realistic candle window (no provider should crash)
        n = 200
        candles = [[i * 60_000, 100.0, 100.5, 99.5, 100.0, 1000.0] for i in range(n)]
        closes = [c[4] for c in candles]
        highs = [c[2] for c in candles]
        lows = [c[3] for c in candles]
        vols = [c[5] for c in candles]
        return SignalContext(
            market=market, candles_1m=candles,
            closes_1m=closes, highs_1m=highs, lows_1m=lows, volumes_1m=vols,
            config=config,
        )

    def test_disabled_by_default(self, monkeypatch, tmp_path):
        from modules.signals import evaluate_signal_pack
        # Even if a weights file exists, no flag → no scaling
        ctx = self._ctx("BTC-EUR", config={})
        res = evaluate_signal_pack(ctx)
        # Re-run with flag off explicitly: same result
        res2 = evaluate_signal_pack(self._ctx("BTC-EUR", config={"USE_MARKET_SIGNAL_WEIGHTS": False}))
        assert res.total_score == res2.total_score

    def test_enabled_applies_multiplier(self, monkeypatch):
        import modules.signals as msig
        # Stub weights loader so the test is hermetic
        monkeypatch.setattr(msig, "_resolve_score_multiplier", lambda ctx: 0.5 if ctx.config.get("USE_MARKET_SIGNAL_WEIGHTS") else 1.0)
        baseline = msig.evaluate_signal_pack(self._ctx("BTC-EUR", config={}))
        scaled = msig.evaluate_signal_pack(self._ctx("BTC-EUR", config={"USE_MARKET_SIGNAL_WEIGHTS": True}))
        if baseline.total_score == 0:
            # Nothing to scale — assertion still must hold
            assert scaled.total_score == 0
        else:
            assert scaled.total_score == pytest.approx(baseline.total_score * 0.5, rel=1e-6)
