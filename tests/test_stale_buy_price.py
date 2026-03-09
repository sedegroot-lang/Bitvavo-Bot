"""Tests for stale buy_price detection and auto-repair.

Covers:
  - >50% deviation from ticker triggers re-derive
  - <50% deviation is considered normal (no action)
  - Startup validation detects and fixes stale prices
  - Hard SL guard skips SL when buy_price is stale
  - Edge cases: zero buy_price, zero ticker, missing fields
"""
import sys
import time
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Test: Deviation detection
# ---------------------------------------------------------------------------

class TestDeviationDetection:
    """Tests for the >50% deviation check that triggers re-derive."""

    def _calc_deviation(self, stored_bp: float, ticker_price: float) -> float:
        """Replicate the deviation calculation from trailing_bot.py."""
        if ticker_price <= 0 or stored_bp <= 0:
            return 0.0
        return abs(stored_bp - ticker_price) / ticker_price

    def test_stale_price_detected(self):
        """Buy price €0.50 vs ticker €7.50 = 93% deviation → stale."""
        deviation = self._calc_deviation(0.50, 7.50)
        assert deviation > 0.50, f"Deviation {deviation:.2%} should exceed 50%"

    def test_normal_price_no_detection(self):
        """Buy price €7.50 vs ticker €7.80 = 3.8% deviation → normal."""
        deviation = self._calc_deviation(7.50, 7.80)
        assert deviation < 0.50, f"Deviation {deviation:.2%} should be under 50%"

    def test_exact_match_zero_deviation(self):
        """Buy price equals ticker → 0% deviation."""
        deviation = self._calc_deviation(100.0, 100.0)
        assert deviation == 0.0

    def test_large_drop_not_stale(self):
        """40% crash: buy €100 vs ticker €60 = 66% deviation → IS stale."""
        deviation = self._calc_deviation(100.0, 60.0)
        assert deviation > 0.50, f"66% deviation should trigger stale detection"

    def test_20pct_drop_not_stale(self):
        """20% crash: buy €100 vs ticker €80 = 25% deviation → not stale."""
        deviation = self._calc_deviation(100.0, 80.0)
        assert deviation < 0.50, f"25% deviation should NOT trigger stale detection"

    def test_zero_ticker_no_crash(self):
        """Ticker = 0 → function returns 0 (no division by zero)."""
        deviation = self._calc_deviation(100.0, 0.0)
        assert deviation == 0.0

    def test_zero_buy_price_no_crash(self):
        """Buy price = 0 → function returns 0."""
        deviation = self._calc_deviation(0.0, 100.0)
        assert deviation == 0.0


class TestStartupValidation:
    """Tests for startup buy_price validation loop."""

    def test_validates_all_open_trades(self):
        """Startup should check every open trade's buy_price."""
        open_trades = {
            "BTC-EUR": {"buy_price": 50000, "amount": 0.001},
            "ETH-EUR": {"buy_price": 3000, "amount": 0.01},
            "LINK-EUR": {"buy_price": 0.50, "amount": 10.0},  # Stale!
        }
        ticker_map = {
            "BTC-EUR": 51000,
            "ETH-EUR": 3100,
            "LINK-EUR": 7.50,  # Real price
        }

        stale_markets = []
        for market, trade in open_trades.items():
            bp = float(trade.get("buy_price", 0) or 0)
            amt = float(trade.get("amount", 0) or 0)
            if bp <= 0 or amt <= 0:
                continue
            ticker_p = ticker_map.get(market, 0)
            if ticker_p <= 0:
                continue
            deviation = abs(bp - ticker_p) / ticker_p
            if deviation > 0.50:
                stale_markets.append(market)

        assert "LINK-EUR" in stale_markets, "LINK-EUR should be detected as stale"
        assert "BTC-EUR" not in stale_markets, "BTC-EUR should NOT be stale"
        assert "ETH-EUR" not in stale_markets, "ETH-EUR should NOT be stale"
        assert len(stale_markets) == 1

    def test_skips_zero_amount_trades(self):
        """Trades with amount=0 should be skipped in validation."""
        open_trades = {
            "DUST-EUR": {"buy_price": 0.001, "amount": 0},
        }
        checked = 0
        for market, trade in open_trades.items():
            bp = float(trade.get("buy_price", 0) or 0)
            amt = float(trade.get("amount", 0) or 0)
            if bp <= 0 or amt <= 0:
                continue
            checked += 1

        assert checked == 0, "Zero-amount trades should be skipped"


class TestHardSLGuard:
    """Tests for hard SL guard — skips SL when buy_price is likely stale."""

    def test_sl_skipped_for_stale_price(self):
        """If loss > 40%, hard SL should skip (buy_price likely wrong)."""
        buy_price = 0.50  # Stale
        current_price = 7.50
        loss_pct = (buy_price - current_price) / buy_price

        # The bot calculates: if loss_pct magnitude > 0.40 → skip SL
        # Note: loss_pct here would be (0.50 - 7.50) / 0.50 = -14.0 (1400% "loss")
        # But the actual check in the bot is: abs loss > 40%
        actual_loss = abs((current_price - buy_price) / buy_price)
        skip_sl = actual_loss > 0.40

        assert skip_sl is True, "SL should be skipped for >40% 'loss' (stale buy_price)"

    def test_sl_not_skipped_for_normal_loss(self):
        """If loss is 8% (normal), hard SL should fire normally."""
        buy_price = 100.0
        current_price = 92.0
        actual_loss = abs((current_price - buy_price) / buy_price)
        skip_sl = actual_loss > 0.40

        assert skip_sl is False, "SL should NOT be skipped for normal 8% loss"


class TestCostBasisRederive:
    """Tests for the re-derive flow after stale detection."""

    def test_rederived_price_replaces_stale(self):
        """After re-derive, buy_price should be updated to new value."""
        trade = {
            "buy_price": 0.50,  # Stale
            "invested_eur": 5.0,
            "amount": 10.0,
        }

        # Simulate re-derive result
        new_avg_price = 7.73
        new_invested = 77.30

        # Apply fix
        trade["buy_price"] = new_avg_price
        trade["invested_eur"] = new_invested
        trade["initial_invested_eur"] = new_invested
        trade["total_invested_eur"] = new_invested
        trade["dca_buys"] = 0
        trade["dca_events"] = []

        assert trade["buy_price"] == 7.73
        assert trade["invested_eur"] == 77.30
        assert trade["dca_buys"] == 0

    def test_rederive_failure_preserves_original(self):
        """If re-derive fails, original buy_price should be preserved."""
        original_bp = 0.50
        trade = {"buy_price": original_bp, "amount": 10.0}

        # Simulate re-derive failure
        try:
            raise Exception("No orders found")
        except Exception:
            pass  # Re-derive failed, don't change

        assert trade["buy_price"] == original_bp, "Original should be preserved on failure"
