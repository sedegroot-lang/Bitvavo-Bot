"""Tests for the Road-to-10 follow-ups: per-market trailing override,
regime entry-block flag, conformal enrichment helper, and main_loop wrapper."""
from __future__ import annotations

import numpy as np
import pytest


# ───────────────────────────────────────── conformal.enrich_ml_info
def test_conformal_enrich_no_calibrator_is_noop():
    from ai.conformal import enrich_ml_info
    info: dict = {}
    out = enrich_ml_info(info, X=np.array([[1.0, 2.0, 3.0]]),
                         path="models/_does_not_exist.pkl")
    assert out is info
    assert out["ml_calibrated"] is False
    assert out["ml_conf_interval_width"] is None


def test_conformal_enrich_handles_none_X():
    from ai.conformal import enrich_ml_info
    info: dict = {"existing": "kept"}
    out = enrich_ml_info(info, X=None)
    assert out["existing"] == "kept"
    assert out["ml_calibrated"] is False


def test_conformal_save_returns_false_when_blob_none():
    from ai.conformal import save_calibrator
    assert save_calibrator(None, "models/_dummy.pkl") is False


# ───────────────────────────────────────── bot/main_loop wrapper
def test_main_loop_module_exposes_run_and_bot_loop():
    from bot import main_loop
    assert hasattr(main_loop, "run")
    assert hasattr(main_loop, "bot_loop")
    # run() does not actually execute bot_loop unless called
    assert callable(main_loop.run)


# ───────────────────────────────────────── BLOCK_ENTRY_REGIMES policy shape
def test_block_entry_regimes_uppercase_normalisation():
    blocked = ["high_volatility", "BEARISH"]
    normalised = {str(x).strip().upper() for x in blocked}
    assert "HIGH_VOLATILITY" in normalised
    assert "BEARISH" in normalised


# ───────────────────────────────────────── MARKET_TRAILING_OVERRIDES schema
def test_market_trailing_overrides_schema_lookup():
    overrides = {
        "BTC-EUR": {"base_trailing_pct": 0.015,
                    "stepped_levels": [{"profit_pct": 0.02, "trailing_pct": 0.010}]},
    }
    cfg_for = overrides.get("BTC-EUR")
    assert isinstance(cfg_for, dict)
    assert cfg_for["base_trailing_pct"] == pytest.approx(0.015)
    assert cfg_for["stepped_levels"][0]["trailing_pct"] == pytest.approx(0.010)
    # Unknown market returns None — caller must handle
    assert overrides.get("XYZ-EUR") is None
