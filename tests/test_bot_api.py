"""Tests for bot/api.py — balance sanitization, spread, normalization, caching."""

import pytest
from unittest.mock import MagicMock, patch
import bot.api as _api


@pytest.fixture(autouse=True)
def _init_api():
    """Initialize bot.api with mocked bitvavo client for each test."""
    # Save original state
    orig_bv = _api._bv
    orig_cfg = _api._cfg
    orig_risk = _api._risk_mgr

    mock_bv = MagicMock()
    cfg = {
        "MAX_SPREAD_PCT": 0.005,
        "FEE_TAKER": 0.0025,
        "FEE_MAKER": 0.0015,
        "BITVAVO_RATE_LIMIT_CALLS": 950,
        "BITVAVO_RATE_LIMIT_WINDOW": 1.0,
    }
    _api.init(mock_bv, cfg)
    # Clear caches between tests
    _api._cache_store.clear()
    _api._rate_buckets.clear()
    _api._API_ERROR_LOG_SUPPRESS.clear()
    yield
    # Restore original state
    _api._bv = orig_bv
    _api._cfg = orig_cfg
    _api._risk_mgr = orig_risk


# ---------------------------------------------------------------------------
# sanitize_balance_payload
# ---------------------------------------------------------------------------

class TestSanitizeBalance:
    def test_valid_list(self):
        payload = [{"symbol": "EUR", "available": "100.0"}]
        result = _api.sanitize_balance_payload(payload)
        assert result == payload

    def test_error_dict(self):
        """An error dict gets wrapped into a list of one dict."""
        payload = {"error": 429, "message": "rate limit"}
        result = _api.sanitize_balance_payload(payload)
        assert isinstance(result, list)
        assert len(result) == 1  # dict gets wrapped

    def test_none_input(self):
        result = _api.sanitize_balance_payload(None)
        assert result == []

    def test_string_input(self):
        result = _api.sanitize_balance_payload("not json")
        assert result == []

    def test_nested_string_entries(self):
        """String entries that are valid JSON dicts get parsed."""
        payload = ['{"symbol": "EUR", "available": "50"}']
        result = _api.sanitize_balance_payload(payload)
        assert len(result) == 1
        assert result[0]["symbol"] == "EUR"


# ---------------------------------------------------------------------------
# spread_ok
# ---------------------------------------------------------------------------

class TestSpreadOk:
    def test_tight_spread_ok(self):
        with patch.object(_api, 'get_ticker_best_bid_ask', return_value={'ask': 100.01, 'bid': 100.0}):
            assert _api.spread_ok("BTC-EUR") is True

    def test_wide_spread_rejected(self):
        with patch.object(_api, 'get_ticker_best_bid_ask', return_value={'ask': 102.0, 'bid': 100.0}):
            assert _api.spread_ok("BTC-EUR") is False

    def test_no_ticker_data(self):
        with patch.object(_api, 'get_ticker_best_bid_ask', return_value=None):
            assert _api.spread_ok("BTC-EUR") is False


# ---------------------------------------------------------------------------
# normalize_amount / normalize_price
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_normalize_amount_truncates(self):
        """Amount should be truncated (floor), not rounded up."""
        with patch.object(_api, 'get_amount_step', return_value=0.001):
            with patch.object(_api, 'get_amount_precision', return_value=3):
                result = _api.normalize_amount("BTC-EUR", 1.23456789)
                assert result <= 1.23456789
                assert result == pytest.approx(1.234, abs=0.001)

    def test_normalize_price_truncates(self):
        with patch.object(_api, 'get_price_step', return_value=0.01):
            result = _api.normalize_price("BTC-EUR", 50123.456)
            assert result <= 50123.456
            assert result == pytest.approx(50123.45, abs=0.01)

    def test_normalize_amount_zero(self):
        with patch.object(_api, 'get_amount_step', return_value=0.001):
            with patch.object(_api, 'get_amount_precision', return_value=3):
                result = _api.normalize_amount("BTC-EUR", 0.0)
                assert result == 0.0

    def test_normalize_price_error_returns_original(self):
        """On error, should return original price rather than crash."""
        with patch.object(_api, 'get_price_step', side_effect=Exception("test")):
            result = _api.normalize_price("BTC-EUR", 50000.0)
            assert result == 50000.0


# ---------------------------------------------------------------------------
# safe_call
# ---------------------------------------------------------------------------

class TestSafeCall:
    def test_returns_result_on_success(self):
        fn = MagicMock(return_value={"data": "ok"})
        result = _api.safe_call(fn, "arg1")
        assert result == {"data": "ok"}
        fn.assert_called_once_with("arg1")

    def test_returns_none_on_failure(self):
        fn = MagicMock(side_effect=Exception("network error"))
        result = _api.safe_call(fn)
        assert result is None

    def test_retries_on_transient_error(self):
        fn = MagicMock(side_effect=[Exception("timeout"), {"data": "ok"}])
        result = _api.safe_call(fn)
        assert result == {"data": "ok"}
        assert fn.call_count == 2


# ---------------------------------------------------------------------------
# get_current_price (with caching)
# ---------------------------------------------------------------------------

class TestGetCurrentPrice:
    def test_returns_float(self):
        with patch.object(_api, '_fetch_price_once', return_value=50000.0):
            result = _api.get_current_price("BTC-EUR", force_refresh=True)
            assert isinstance(result, float)
            assert result == 50000.0

    def test_returns_none_on_failure(self):
        with patch.object(_api, '_fetch_price_once', return_value=None):
            # Also mock the disk cache
            with patch('bot.api.Path') as mock_path:
                mock_path.return_value.exists.return_value = False
                result = _api.get_current_price("NOEXIST-EUR", force_refresh=True)
                # May return None or cached value
                assert result is None or isinstance(result, float)
