"""Tests for modules/config_schema.py — config validation logic."""

import pytest
from modules.config_schema import validate_config, get_schema


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_cfg() -> dict:
    """Return a minimal valid config dict."""
    return {
        "BASE_AMOUNT_EUR": 6.0,
        "MAX_OPEN_TRADES": 10,
        "SMA_SHORT": 20,
        "SMA_LONG": 50,
        "MACD_FAST": 12,
        "MACD_SLOW": 26,
        "RSI_MIN_BUY": 35.0,
        "RSI_MAX_BUY": 65.0,
        "MIN_ORDER_EUR": 5.0,
        "MAX_TOTAL_EXPOSURE_EUR": 200.0,
        "TEST_MODE": False,
        "LIVE_TRADING": True,
        "WHITELIST_MARKETS": ["BTC-EUR", "ETH-EUR"],
        "TRAILING_ACTIVATION_PCT": 0.045,
        "DEFAULT_TRAILING": 0.032,
    }


# ---------------------------------------------------------------------------
# Basic validation
# ---------------------------------------------------------------------------

class TestBasicValidation:
    def test_valid_config_returns_no_issues(self):
        issues = validate_config(_valid_cfg())
        assert issues == []

    def test_missing_keys_are_ok(self):
        """An empty dict should not produce issues — defaults are used elsewhere."""
        issues = validate_config({})
        assert issues == []

    def test_extra_keys_are_ignored(self):
        cfg = _valid_cfg()
        cfg["SOME_UNKNOWN_KEY"] = "whatever"
        issues = validate_config(cfg)
        assert issues == []


# ---------------------------------------------------------------------------
# Type validation
# ---------------------------------------------------------------------------

class TestTypeValidation:
    def test_float_wrong_type(self):
        cfg = _valid_cfg()
        cfg["BASE_AMOUNT_EUR"] = "not-a-number"
        issues = validate_config(cfg)
        assert any(i["key"] == "BASE_AMOUNT_EUR" and i["severity"] == "error" for i in issues)

    def test_int_wrong_type(self):
        cfg = _valid_cfg()
        cfg["MAX_OPEN_TRADES"] = "abc"
        issues = validate_config(cfg)
        assert any(i["key"] == "MAX_OPEN_TRADES" and i["severity"] == "error" for i in issues)

    def test_bool_accepts_string_true(self):
        cfg = _valid_cfg()
        cfg["TEST_MODE"] = "true"
        issues = validate_config(cfg)
        # Should not produce a warning for string bools
        assert not any(i["key"] == "TEST_MODE" for i in issues)

    def test_bool_rejects_random_string(self):
        cfg = _valid_cfg()
        cfg["TEST_MODE"] = "maybe"
        issues = validate_config(cfg)
        assert any(i["key"] == "TEST_MODE" for i in issues)

    def test_list_wrong_type(self):
        cfg = _valid_cfg()
        cfg["WHITELIST_MARKETS"] = "BTC-EUR"
        issues = validate_config(cfg)
        assert any(i["key"] == "WHITELIST_MARKETS" and i["severity"] == "error" for i in issues)


# ---------------------------------------------------------------------------
# Range validation
# ---------------------------------------------------------------------------

class TestRangeValidation:
    def test_float_out_of_range_low(self):
        cfg = _valid_cfg()
        cfg["BASE_AMOUNT_EUR"] = 1.0  # min is 5.0
        issues = validate_config(cfg)
        assert any(i["key"] == "BASE_AMOUNT_EUR" and "min" in i["issue"] for i in issues)

    def test_float_out_of_range_high(self):
        cfg = _valid_cfg()
        cfg["BASE_AMOUNT_EUR"] = 999.0  # max is 500.0
        issues = validate_config(cfg)
        assert any(i["key"] == "BASE_AMOUNT_EUR" and "max" in i["issue"] for i in issues)

    def test_int_out_of_range_low(self):
        cfg = _valid_cfg()
        cfg["MAX_OPEN_TRADES"] = 0  # min is 1
        issues = validate_config(cfg)
        assert any(i["key"] == "MAX_OPEN_TRADES" for i in issues)

    def test_int_out_of_range_high(self):
        cfg = _valid_cfg()
        cfg["MAX_OPEN_TRADES"] = 100  # max is 50
        issues = validate_config(cfg)
        assert any(i["key"] == "MAX_OPEN_TRADES" for i in issues)


# ---------------------------------------------------------------------------
# Coerce
# ---------------------------------------------------------------------------

class TestCoerce:
    def test_coerce_clamps_float_to_min(self):
        cfg = {"BASE_AMOUNT_EUR": 1.0}
        validate_config(cfg, coerce=True)
        assert cfg["BASE_AMOUNT_EUR"] >= 5.0

    def test_coerce_clamps_float_to_max(self):
        cfg = {"BASE_AMOUNT_EUR": 999.0}
        validate_config(cfg, coerce=True)
        assert cfg["BASE_AMOUNT_EUR"] <= 500.0

    def test_coerce_replaces_invalid_type_with_default(self):
        cfg = {"MAX_OPEN_TRADES": "abc"}
        validate_config(cfg, coerce=True)
        assert cfg["MAX_OPEN_TRADES"] == 10  # default

    def test_coerce_replaces_invalid_list(self):
        cfg = {"WHITELIST_MARKETS": "not-a-list"}
        validate_config(cfg, coerce=True)
        assert isinstance(cfg["WHITELIST_MARKETS"], list)


# ---------------------------------------------------------------------------
# Cross-field validation
# ---------------------------------------------------------------------------

class TestCrossValidation:
    def test_sma_short_gte_long(self):
        cfg = _valid_cfg()
        cfg["SMA_SHORT"] = 50
        cfg["SMA_LONG"] = 20
        issues = validate_config(cfg)
        assert any("SMA_SHORT" in i["key"] and i["severity"] == "error" for i in issues)

    def test_macd_fast_gte_slow(self):
        cfg = _valid_cfg()
        cfg["MACD_FAST"] = 30
        cfg["MACD_SLOW"] = 10
        issues = validate_config(cfg)
        assert any("MACD_FAST" in i["key"] and i["severity"] == "error" for i in issues)

    def test_base_below_min_order(self):
        cfg = _valid_cfg()
        cfg["BASE_AMOUNT_EUR"] = 5.0
        cfg["MIN_ORDER_EUR"] = 10.0
        issues = validate_config(cfg)
        assert any("BASE_AMOUNT_EUR" in i["key"] and i["severity"] == "error" for i in issues)

    def test_rsi_inverted(self):
        cfg = _valid_cfg()
        cfg["RSI_MIN_BUY"] = 70.0
        cfg["RSI_MAX_BUY"] = 30.0
        issues = validate_config(cfg)
        assert any("RSI" in i["key"] for i in issues)

    def test_test_and_live_both_true(self):
        cfg = _valid_cfg()
        cfg["TEST_MODE"] = True
        cfg["LIVE_TRADING"] = True
        issues = validate_config(cfg)
        assert any("TEST_MODE" in i["key"] and i["severity"] == "warning" for i in issues)

    def test_exposure_below_base(self):
        cfg = _valid_cfg()
        cfg["MAX_TOTAL_EXPOSURE_EUR"] = 5.0
        cfg["BASE_AMOUNT_EUR"] = 10.0
        issues = validate_config(cfg)
        assert any("MAX_TOTAL_EXPOSURE_EUR" in i["key"] for i in issues)


# ---------------------------------------------------------------------------
# get_schema
# ---------------------------------------------------------------------------

class TestGetSchema:
    def test_returns_dict(self):
        schema = get_schema()
        assert isinstance(schema, dict)
        assert len(schema) > 20  # We have ~40 keys defined

    def test_mutation_safe(self):
        schema = get_schema()
        schema["FAKE_KEY"] = {"type": "int"}
        schema2 = get_schema()
        assert "FAKE_KEY" not in schema2
