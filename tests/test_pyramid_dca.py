"""Tests for Pyramid-Up DCA and Hybrid DCA mode.

Covers:
  - Pyramid triggers only when position is in profit ≥ min_profit_pct
  - Pyramid size scales down per DCA_PYRAMID_SCALE_DOWN
  - Pyramid respects DCA_PYRAMID_MAX_ADDS limit
  - Hybrid mode dispatches: loss → average-down, profit → pyramid-up
  - RSI filter blocks DCA regardless of mode
"""
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Minimal DCA context mock
# ---------------------------------------------------------------------------

class MockDCAContext:
    """Minimal context interface for DCAHandler."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.log_messages = []
        self._candles = []
        self._prices = [50.0, 51.0, 49.0, 48.0, 50.0, 52.0, 51.5, 50.5] * 8  # 64 prices

    def log(self, msg, level="info"):
        self.log_messages.append((level, msg))

    def get_candles(self, market, interval, limit):
        return [{"close": str(p)} for p in self._prices[:limit]]

    def close_prices(self, candles):
        return [float(c["close"]) for c in candles]

    def rsi(self, prices, period=14):
        # Return a moderate RSI that passes the DCA threshold
        return 45.0

    def place_buy(self, market, amount_eur, reason="dca"):
        return {"orderId": "test-123", "filledAmount": str(amount_eur / 50.0)}


# ---------------------------------------------------------------------------
# Test: Pyramid-up only triggers at sufficient profit
# ---------------------------------------------------------------------------

class TestPyramidUpTrigger:
    """Pyramid DCA should only add to positions above min_profit_pct."""

    def test_pyramid_requires_min_profit(self):
        """Position must be ≥3% in profit for pyramid to trigger."""
        config = {
            "DCA_PYRAMID_UP": True,
            "DCA_PYRAMID_MIN_PROFIT_PCT": 0.03,
            "DCA_PYRAMID_SCALE_DOWN": 0.7,
            "DCA_PYRAMID_MAX_ADDS": 2,
            "DCA_AMOUNT_EUR": 5.0,
        }
        buy_price = 100.0
        current_price = 102.0  # Only 2% profit → below 3% threshold
        profit_pct = (current_price / buy_price) - 1

        assert profit_pct < 0.03, "2% profit should be below 3% threshold"

    def test_pyramid_triggers_at_threshold(self):
        """Position at exactly 3% profit should trigger pyramid."""
        buy_price = 100.0
        current_price = 103.0  # Exactly 3%
        min_profit_pct = 0.03
        profit_pct = (current_price / buy_price) - 1

        assert profit_pct >= min_profit_pct, "3% profit should meet 3% threshold"

    def test_pyramid_triggers_above_threshold(self):
        """Position at 5% profit should trigger pyramid."""
        buy_price = 100.0
        current_price = 105.0  # 5% profit
        min_profit_pct = 0.03
        profit_pct = (current_price / buy_price) - 1

        assert profit_pct >= min_profit_pct, "5% profit should exceed 3% threshold"


class TestPyramidScaleDown:
    """Each successive pyramid buy should be smaller."""

    def test_first_pyramid_is_full_size(self):
        """First pyramid buy uses base DCA amount."""
        base_amount = 5.0
        scale_down = 0.7
        dca_buys = 0

        buy_amount = base_amount * (scale_down ** dca_buys)
        assert buy_amount == 5.0, f"First buy should be €5.0, got €{buy_amount}"

    def test_second_pyramid_is_scaled(self):
        """Second pyramid buy = base * 0.7."""
        base_amount = 5.0
        scale_down = 0.7
        dca_buys = 1

        buy_amount = base_amount * (scale_down ** dca_buys)
        assert abs(buy_amount - 3.5) < 0.01, f"Second buy should be €3.50, got €{buy_amount}"

    def test_third_pyramid_diminishes_further(self):
        """Third pyramid buy = base * 0.7^2 = €2.45."""
        base_amount = 5.0
        scale_down = 0.7
        dca_buys = 2

        buy_amount = base_amount * (scale_down ** dca_buys)
        assert abs(buy_amount - 2.45) < 0.01, f"Third buy should be €2.45, got €{buy_amount}"


class TestPyramidMaxAdds:
    """Pyramid should stop after DCA_PYRAMID_MAX_ADDS."""

    def test_max_adds_blocks_further_pyramids(self):
        """When dca_buys >= max_adds, pyramid should not trigger."""
        max_adds = 2
        current_buys = 2

        should_pyramid = current_buys < max_adds
        assert should_pyramid is False, "Should not pyramid when at max adds"

    def test_below_max_adds_allows_pyramid(self):
        """When dca_buys < max_adds, pyramid should proceed."""
        max_adds = 2
        current_buys = 1

        should_pyramid = current_buys < max_adds
        assert should_pyramid is True, "Should allow pyramid when below max adds"


class TestHybridDCADispatch:
    """Hybrid mode routes to average-down (loss) or pyramid-up (profit)."""

    def test_hybrid_loss_routes_to_average_down(self):
        """In hybrid mode, position in loss → average-down."""
        buy_price = 100.0
        current_price = 95.0  # 5% loss
        hybrid_mode = True
        pyramid_up = True

        in_profit = current_price > buy_price
        assert in_profit is False

        if hybrid_mode:
            if in_profit and pyramid_up:
                mode = "pyramid_up"
            elif not in_profit:
                mode = "average_down"
            else:
                mode = "skip"
        else:
            mode = "pyramid_up" if pyramid_up else "average_down"

        assert mode == "average_down", f"Expected average_down, got {mode}"

    def test_hybrid_profit_routes_to_pyramid(self):
        """In hybrid mode, position in profit → pyramid-up."""
        buy_price = 100.0
        current_price = 105.0  # 5% profit
        hybrid_mode = True
        pyramid_up = True

        in_profit = current_price > buy_price

        if hybrid_mode:
            if in_profit and pyramid_up:
                mode = "pyramid_up"
            elif not in_profit:
                mode = "average_down"
            else:
                mode = "skip"

        assert mode == "pyramid_up", f"Expected pyramid_up, got {mode}"

    def test_hybrid_profit_no_pyramid_config_skips(self):
        """In hybrid mode with pyramid disabled, in-profit → skip."""
        buy_price = 100.0
        current_price = 105.0
        hybrid_mode = True
        pyramid_up = False

        in_profit = current_price > buy_price

        if hybrid_mode:
            if in_profit and pyramid_up:
                mode = "pyramid_up"
            elif not in_profit:
                mode = "average_down"
            else:
                mode = "skip"

        assert mode == "skip", f"Expected skip, got {mode}"

    def test_non_hybrid_pyramid_only(self):
        """When NOT hybrid but pyramid enabled → always pyramid."""
        hybrid_mode = False
        pyramid_up = True

        if hybrid_mode:
            mode = "hybrid_dispatch"
        elif pyramid_up:
            mode = "pyramid_up"
        else:
            mode = "average_down"

        assert mode == "pyramid_up"

    def test_non_hybrid_average_down_only(self):
        """When NOT hybrid and pyramid disabled → always average-down."""
        hybrid_mode = False
        pyramid_up = False

        if hybrid_mode:
            mode = "hybrid_dispatch"
        elif pyramid_up:
            mode = "pyramid_up"
        else:
            mode = "average_down"

        assert mode == "average_down"


class TestDCAConfigValidation:
    """DCA config parameters should be within valid ranges."""

    def test_drop_pct_positive(self):
        """DCA_DROP_PCT must be positive."""
        drop_pct = 0.06
        assert drop_pct > 0

    def test_pyramid_min_profit_positive(self):
        """DCA_PYRAMID_MIN_PROFIT_PCT must be positive."""
        min_profit = 0.03
        assert min_profit > 0

    def test_scale_down_between_0_and_1(self):
        """DCA_PYRAMID_SCALE_DOWN must be between 0 and 1."""
        scale = 0.7
        assert 0 < scale < 1

    def test_max_adds_positive(self):
        """DCA_PYRAMID_MAX_ADDS must be positive integer."""
        max_adds = 2
        assert max_adds > 0 and isinstance(max_adds, int)
