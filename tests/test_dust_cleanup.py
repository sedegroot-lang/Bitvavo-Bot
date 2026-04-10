# -*- coding: utf-8 -*-
"""Tests for dust trade filtering and auto-cleanup."""
import sys
import os
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def _reset_shared():
    """Reset shared state before each test."""
    from bot.shared import state
    state.open_trades = {}
    state.closed_trades = []
    state.market_profits = {}
    state.CONFIG = {
        'DUST_TRADE_THRESHOLD_EUR': 5.0,
        'MIN_ORDER_EUR': 5.0,
    }
    state.DUST_TRADE_THRESHOLD_EUR = 5.0
    state.MIN_ORDER_EUR = 5.0
    state.log = MagicMock()
    state.safe_call = MagicMock(return_value=[])
    state.bitvavo = MagicMock()
    state.trades_lock = __import__('threading').RLock()
    state.get_current_price = MagicMock(side_effect=lambda m: {
        'UNI-EUR': 2.70,
        'XRP-EUR': 1.15,
        'TAO-EUR': 230.0,
        'ALGO-EUR': 0.095,
        'LTC-EUR': 47.0,
    }.get(m, 1.0))
    yield
    state.open_trades = {}
    state.closed_trades = []
    state.market_profits = {}


class TestCountActiveOpenTrades:
    """Tests that count_active_open_trades filters dust correctly."""

    def test_all_real_trades_counted(self):
        from bot.portfolio import count_active_open_trades
        from bot.shared import state
        state.open_trades = {
            'UNI-EUR': {'amount': 60, 'buy_price': 2.70, 'invested_eur': 162.0},
            'XRP-EUR': {'amount': 47, 'buy_price': 1.15, 'invested_eur': 54.0},
        }
        assert count_active_open_trades(threshold=5.0) == 2

    def test_dust_trades_excluded(self):
        from bot.portfolio import count_active_open_trades
        from bot.shared import state
        state.open_trades = {
            'UNI-EUR': {'amount': 60, 'buy_price': 2.70, 'invested_eur': 162.0},
            'XRP-EUR': {'amount': 47, 'buy_price': 1.15, 'invested_eur': 54.0},
            'TAO-EUR': {'amount': 0.009, 'buy_price': 230.0, 'invested_eur': 2.0},  # ~€2.07
            'ALGO-EUR': {'amount': 0.56, 'buy_price': 0.095, 'invested_eur': 0.05},  # ~€0.05
        }
        assert count_active_open_trades(threshold=5.0) == 2

    def test_dust_threshold_from_shared_state(self):
        from bot.portfolio import count_active_open_trades
        from bot.shared import state
        state.DUST_TRADE_THRESHOLD_EUR = 5.0
        state.open_trades = {
            'UNI-EUR': {'amount': 60, 'buy_price': 2.70, 'invested_eur': 162.0},
            'TAO-EUR': {'amount': 0.009, 'buy_price': 230.0, 'invested_eur': 2.0},
        }
        # No explicit threshold; should use state.DUST_TRADE_THRESHOLD_EUR = 5.0
        assert count_active_open_trades() == 1

    def test_low_threshold_counts_everything(self):
        from bot.portfolio import count_active_open_trades
        from bot.shared import state
        state.open_trades = {
            'UNI-EUR': {'amount': 60, 'buy_price': 2.70, 'invested_eur': 162.0},
            'TAO-EUR': {'amount': 0.009, 'buy_price': 230.0, 'invested_eur': 2.0},
        }
        # With threshold 0.5, TAO (~€2.07) is above threshold
        assert count_active_open_trades(threshold=0.5) == 2


class TestCountDustTrades:
    """Tests that count_dust_trades correctly identifies dust."""

    def test_two_dust_positions(self):
        from bot.portfolio import count_dust_trades
        from bot.shared import state
        state.open_trades = {
            'UNI-EUR': {'amount': 60, 'buy_price': 2.70, 'invested_eur': 162.0},
            'TAO-EUR': {'amount': 0.009, 'buy_price': 230.0, 'invested_eur': 2.0},
            'ALGO-EUR': {'amount': 0.56, 'buy_price': 0.095, 'invested_eur': 0.05},
        }
        assert count_dust_trades(threshold=5.0) == 2

    def test_no_dust(self):
        from bot.portfolio import count_dust_trades
        from bot.shared import state
        state.open_trades = {
            'UNI-EUR': {'amount': 60, 'buy_price': 2.70, 'invested_eur': 162.0},
        }
        assert count_dust_trades(threshold=5.0) == 0


class TestSharedStateDefault:
    """Verify the default DUST_TRADE_THRESHOLD_EUR in shared state."""

    def test_default_threshold_is_5(self):
        from bot.shared import _SharedState
        s = _SharedState()
        assert s.DUST_TRADE_THRESHOLD_EUR == 5.0
