"""Tests for bot/trailing.py — trailing stops, stop-loss, partial TP, profit calc."""

import time
import pytest
import bot.trailing as _trail


@pytest.fixture(autouse=True)
def _init_trail():
    """Initialize trailing module with test config before each test, restore after."""
    # Save original state
    orig_cfg = _trail._cfg
    orig_trades = _trail._open_trades

    cfg = {
        "FEE_TAKER": 0.0025,
        "FEE_MAKER": 0.0015,
        "DEFAULT_TRAILING": 0.10,
        "TRAILING_ACTIVATION_PCT": 0.02,
        "ATR_MULTIPLIER": 2.0,
        "ATR_WINDOW_1M": 14,
        "HARD_SL_ALT_PCT": 0.10,
        "HARD_SL_BTCETH_PCT": 0.10,
        "PARTIAL_TP_HISTORY_FILE": "data/test_tp_events.jsonl",
        "PARTIAL_TP_STATS_FILE": "data/test_tp_stats.json",
        "TAKE_PROFIT_TARGETS": [0.025, 0.055, 0.10],
        "TAKE_PROFIT_PERCENTAGES": [0.30, 0.35, 0.35],
    }
    _trail.init(cfg, open_trades_ref={})
    yield
    # Restore original state
    _trail._cfg = orig_cfg
    _trail._open_trades = orig_trades


# ---------------------------------------------------------------------------
# realized_profit
# ---------------------------------------------------------------------------

class TestRealizedProfit:
    def test_basic_profit(self):
        """Buy at 100, sell at 110, 1 unit → positive profit minus fees."""
        profit = _trail.realized_profit(100.0, 110.0, 1.0)
        # gross = 110-100 = 10, fees ≈ 0.25+0.275 = 0.525
        assert profit > 0
        assert abs(profit - (10.0 - 100*0.0025 - 110*0.0025)) < 0.001

    def test_loss_scenario(self):
        """Sell below buy → negative profit."""
        profit = _trail.realized_profit(100.0, 90.0, 1.0)
        assert profit < 0

    def test_custom_fees(self):
        """Custom fee percentages override defaults."""
        profit = _trail.realized_profit(100.0, 110.0, 1.0, buy_fee_pct=0.001, sell_fee_pct=0.001)
        expected = (110 - 100) - (100 * 0.001) - (110 * 0.001)
        assert abs(profit - expected) < 0.001

    def test_zero_amount(self):
        """Zero amount → zero profit."""
        profit = _trail.realized_profit(100.0, 110.0, 0.0)
        assert profit == 0.0

    def test_large_amount_precision(self):
        """Large amounts don't lose precision."""
        profit = _trail.realized_profit(50000.0, 51000.0, 10.0)
        gross = (51000 - 50000) * 10  # 10000
        fees = 50000*10*0.0025 + 51000*10*0.0025  # 1250 + 1275 = 2525
        assert abs(profit - (gross - fees)) < 0.01


# ---------------------------------------------------------------------------
# check_stop_loss
# ---------------------------------------------------------------------------

class TestCheckStopLoss:
    def test_disabled_by_default(self):
        triggered, reason = _trail.check_stop_loss("BTC-EUR", {}, 100.0, enabled=False)
        assert triggered is False
        assert "disabled" in reason.lower()

    def test_triggers_at_15pct_loss(self):
        trade = {"invested_eur": 100.0, "amount": 1.0, "timestamp": time.time()}
        # Price dropped to 80 → 20% loss
        triggered, reason = _trail.check_stop_loss("BTC-EUR", trade, 80.0, enabled=True)
        assert triggered is True
        assert "hard_stop" in reason

    def test_no_trigger_small_loss(self):
        trade = {"invested_eur": 100.0, "amount": 1.0, "timestamp": time.time()}
        # Price at 95 → 5% loss (below 15% threshold)
        triggered, _ = _trail.check_stop_loss("BTC-EUR", trade, 95.0, enabled=True)
        assert triggered is False

    def test_time_based_7day_stop(self):
        trade = {
            "invested_eur": 100.0,
            "amount": 1.0,
            "timestamp": time.time() - (8 * 86400),  # 8 days ago
        }
        # 7% loss after 8 days
        triggered, reason = _trail.check_stop_loss("BTC-EUR", trade, 93.0, enabled=True)
        assert triggered is True
        assert "time_stop" in reason

    def test_invalid_invested_amount(self):
        trade = {"invested_eur": 0, "amount": 1.0}
        triggered, reason = _trail.check_stop_loss("BTC-EUR", trade, 100.0, enabled=True)
        assert triggered is False
        assert "invalid" in reason.lower()


# ---------------------------------------------------------------------------
# calculate_adaptive_tp
# ---------------------------------------------------------------------------

class TestCalculateAdaptiveTP:
    def test_low_volatility_conservative(self):
        levels = _trail.calculate_adaptive_tp("BTC-EUR", 50000, volatility=0.01)
        assert len(levels) == 3
        # Low vol → base_tp = 0.015
        assert all(lv["pct"] > 0 for lv in levels)
        assert levels[0]["pct"] < levels[1]["pct"] < levels[2]["pct"]

    def test_high_volatility_aggressive(self):
        levels = _trail.calculate_adaptive_tp("BTC-EUR", 50000, volatility=0.08)
        # High vol → base_tp = 0.06
        assert levels[1]["pct"] == pytest.approx(0.06, abs=0.001)

    def test_trend_boost(self):
        levels_no_trend = _trail.calculate_adaptive_tp("BTC-EUR", 50000, volatility=0.03)
        levels_trend = _trail.calculate_adaptive_tp("BTC-EUR", 50000, volatility=0.03, trend_strength=0.8)
        # With trend, TPs should be 1.5x higher
        assert levels_trend[1]["pct"] > levels_no_trend[1]["pct"]

    def test_amounts_sum_to_one(self):
        levels = _trail.calculate_adaptive_tp("BTC-EUR", 50000, volatility=0.03)
        total = sum(lv["amount"] for lv in levels)
        assert abs(total - 1.0) < 0.01

    def test_fallback_on_error(self):
        """Should return single-level fallback without crashing."""
        # Force an error by passing None volatility (triggers API call which would fail in tests)
        # but the function has try/except → returns fallback
        levels = _trail.calculate_adaptive_tp("INVALID", 0, volatility=0.03)
        assert isinstance(levels, list)
        assert len(levels) >= 1


# ---------------------------------------------------------------------------
# check_advanced_exit_strategies
# ---------------------------------------------------------------------------

class TestCheckAdvancedExit:
    def test_returns_tuple(self):
        trade = {
            "buy_price": 100.0,
            "amount": 1.0,
            "invested_eur": 100.0,
            "timestamp": time.time(),
        }
        result = _trail.check_advanced_exit_strategies(trade, 105.0)
        assert isinstance(result, tuple)
        assert len(result) == 3  # (should_exit, exit_portion, reason)


# ---------------------------------------------------------------------------
# get_partial_tp_stats
# ---------------------------------------------------------------------------

class TestPartialTPStats:
    def test_returns_dict(self):
        stats = _trail.get_partial_tp_stats()
        assert isinstance(stats, dict)
        assert "total_events" in stats
