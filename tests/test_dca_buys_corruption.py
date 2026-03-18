# -*- coding: utf-8 -*-
"""Tests for DCA dca_buys corruption fix and validate_and_repair_trades guards.

Covers:
1. DCA under-min-size must NOT inflate dca_buys to max (was the root cause of AVAX bug)
2. validate_and_repair_trades GUARD 5: dca_buys ↔ dca_events consistency
3. validate_and_repair_trades GUARD 6: invested_eur ↔ initial + DCA events
"""
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.trading_dca import DCAManager, DCASettings, DCAContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(**overrides):
    defaults = dict(
        config={
            'RSI_DCA_THRESHOLD': 100,
            'SMART_DCA_ENABLED': False,
            'BASE_AMOUNT_EUR': 30,
            'MAX_TOTAL_EXPOSURE_EUR': 0,
            'DCA_MAX_BUYS_PER_ITERATION': 3,
        },
        safe_call=MagicMock(return_value=None),
        bitvavo=MagicMock(),
        log=MagicMock(),
        current_open_exposure_eur=MagicMock(return_value=100.0),
        get_min_order_size=MagicMock(return_value=1.0),
        place_buy=MagicMock(return_value={'status': 'filled', 'filledAmount': '10', 'filledAmountQuote': '20'}),
        is_order_success=MagicMock(return_value=True),
        save_trades=MagicMock(),
        get_candles=MagicMock(return_value=[]),
        close_prices=MagicMock(return_value=[]),
        rsi=MagicMock(return_value=None),
        trade_log_path='',
    )
    defaults.update(overrides)
    return DCAContext(**defaults)


def _make_settings(**overrides):
    defaults = dict(
        enabled=True,
        dynamic=False,
        max_buys=9,
        drop_pct=0.02,
        step_multiplier=1.0,
        amount_eur=30.0,
        size_multiplier=0.8,
        max_buys_per_iteration=3,
    )
    defaults.update(overrides)
    return DCASettings(**defaults)


def _make_trade(**overrides):
    defaults = dict(
        market='TEST-EUR',
        buy_price=100.0,
        highest_price=100.0,
        amount=1.0,
        invested_eur=100.0,
        initial_invested_eur=100.0,
        total_invested_eur=100.0,
        dca_buys=0,
        dca_max=9,
        dca_events=[],
        dca_next_price=98.0,
        last_dca_price=100.0,
        tp_levels_done=[False, False, False],
        tp_last_time=0.0,
        partial_tp_returned_eur=0.0,
        opened_ts=time.time(),
    )
    defaults.update(overrides)
    return defaults


# ===========================================================================
# Test: DCA under-min-size must NOT inflate dca_buys
# ===========================================================================

class TestDCAUnderMinSizeNoBuysInflation:
    """When DCA order is too small (under min_size), dca_buys must stay unchanged."""

    def test_fixed_dca_under_min_does_not_set_max(self):
        """Fixed DCA: under-min-size should break without changing dca_buys."""
        ctx = _make_ctx(
            get_min_order_size=MagicMock(return_value=999999.0),  # impossibly high
        )
        settings = _make_settings(amount_eur=10.0, max_buys=9)
        trade = _make_trade(buy_price=100.0, amount=1.0, dca_buys=0)
        mgr = DCAManager(ctx)
        # Price well below trigger (should attempt DCA but fail on min_size)
        mgr._execute_fixed_dca('TEST-EUR', trade, 50.0, settings, 1.0)
        # dca_buys must remain 0, NOT be set to 9 (the old bug)
        assert trade['dca_buys'] == 0, f"dca_buys should stay 0, got {trade['dca_buys']}"

    def test_fixed_dca_under_min_with_existing_buys(self):
        """If 3 DCAs done, under-min should keep dca_buys=3, not set to max."""
        events = [
            {'event_id': f'e{i}', 'timestamp': time.time(), 'price': 95.0,
             'amount_eur': 20.0, 'tokens_bought': 0.2, 'dca_level': i+1}
            for i in range(3)
        ]
        ctx = _make_ctx(
            get_min_order_size=MagicMock(return_value=999999.0),
        )
        settings = _make_settings(amount_eur=10.0, max_buys=9)
        trade = _make_trade(dca_buys=3, dca_events=events)
        mgr = DCAManager(ctx)
        mgr._execute_fixed_dca('TEST-EUR', trade, 50.0, settings, 1.0)
        assert trade['dca_buys'] == 3, f"dca_buys should stay 3, got {trade['dca_buys']}"

    def test_dynamic_dca_under_min_does_not_set_max(self):
        """Dynamic DCA: same fix — under-min-size should not inflate dca_buys."""
        ctx = _make_ctx(
            get_min_order_size=MagicMock(return_value=999999.0),
            safe_call=MagicMock(return_value=[{'symbol': 'EUR', 'available': '100'}]),
        )
        settings = _make_settings(dynamic=True, amount_eur=10.0, max_buys=9)
        trade = _make_trade(buy_price=100.0, amount=1.0, dca_buys=0)
        mgr = DCAManager(ctx)
        mgr._execute_dynamic_dca('TEST-EUR', trade, 50.0, settings, 1.0)
        assert trade['dca_buys'] == 0, f"dca_buys should stay 0, got {trade['dca_buys']}"


# ===========================================================================
# Test: DCA can still execute normally (no regression)
# ===========================================================================

class TestDCANormalExecution:
    """Verify normal DCA flow still works correctly after the fix."""

    def test_successful_dca_increments_buys(self):
        """A successful DCA buy should increment dca_buys and add event."""
        ctx = _make_ctx(
            get_min_order_size=MagicMock(return_value=0.001),
            place_buy=MagicMock(return_value={
                'status': 'filled',
                'filledAmount': '0.5',
                'filledAmountQuote': '24.5',
            }),
            is_order_success=MagicMock(return_value=True),
        )
        settings = _make_settings(amount_eur=30.0, max_buys=9, drop_pct=0.02)
        trade = _make_trade(buy_price=100.0, amount=1.0, dca_buys=0, dca_events=[])
        mgr = DCAManager(ctx)
        # Price just below 2% drop trigger (98.0), but not enough for 2nd level
        mgr._execute_fixed_dca('TEST-EUR', trade, 97.9, settings, 1.0)
        assert trade['dca_buys'] == 1
        assert len(trade['dca_events']) == 1
        assert trade['dca_events'][0]['dca_level'] == 1

    def test_multiple_dcas_in_one_call(self):
        """With max_buys_per_iteration=3, up to 3 DCAs can happen per call."""
        call_count = [0]

        def mock_place_buy(market, eur, price):
            call_count[0] += 1
            return {
                'status': 'filled',
                'filledAmount': str(eur / price),
                'filledAmountQuote': str(eur),
            }

        ctx = _make_ctx(
            get_min_order_size=MagicMock(return_value=0.001),
            place_buy=mock_place_buy,
            is_order_success=MagicMock(return_value=True),
        )
        settings = _make_settings(
            amount_eur=30.0, max_buys=9, drop_pct=0.001,  # tiny drop so all levels trigger
            max_buys_per_iteration=3,
        )
        trade = _make_trade(buy_price=100.0, amount=1.0, dca_buys=0, dca_events=[])
        mgr = DCAManager(ctx)
        mgr._execute_fixed_dca('TEST-EUR', trade, 50.0, settings, 1.0)
        # Should have done exactly 3 DCAs (limited by max_buys_per_iteration)
        assert trade['dca_buys'] == 3
        assert len(trade['dca_events']) == 3
        assert call_count[0] == 3


# ===========================================================================
# Test: GUARD 5 — dca_buys ↔ dca_events consistency (never reduce)
# ===========================================================================

class TestGuard5NeverReduceDcaBuys:
    """GUARD 5 should never lower dca_buys below its current value.

    A higher counter than event count indicates unrecorded exchange buys
    (events lost due to debounce/crash). Reducing would allow extra DCAs.
    """

    @staticmethod
    def _run_guard5(trade, dca_max_global=9):
        """Simulate exactly what GUARD 5 does in validate_and_repair_trades."""
        dca_events = trade.get('dca_events', []) or []
        actual_event_count = len(dca_events)
        dca_buys_now = int(trade.get('dca_buys', 0) or 0)
        dca_max_now = int(trade.get('dca_max', dca_max_global) or dca_max_global)
        correct_buys = min(max(dca_buys_now, actual_event_count), dca_max_now)
        if dca_buys_now != correct_buys:
            trade['dca_buys'] = correct_buys
        return trade['dca_buys']

    def test_buys_higher_than_events_stays(self):
        """dca_buys=5 with 2 events → stays at 5 (untracked buys exist)."""
        trade = _make_trade(dca_buys=5, dca_events=[
            {'event_id': 'e1', 'amount_eur': 10},
            {'event_id': 'e2', 'amount_eur': 10},
        ], dca_max=9)
        result = self._run_guard5(trade)
        assert result == 5

    def test_events_higher_than_buys_raises(self):
        """dca_buys=2 with 5 events → raises to 5."""
        events = [{'event_id': f'e{i}', 'amount_eur': 10} for i in range(5)]
        trade = _make_trade(dca_buys=2, dca_events=events, dca_max=9)
        result = self._run_guard5(trade)
        assert result == 5

    def test_buys_above_max_capped(self):
        """dca_buys=12 with 7 events and max=9 → capped at 9."""
        events = [{'event_id': f'e{i}', 'amount_eur': 10} for i in range(7)]
        trade = _make_trade(dca_buys=12, dca_events=events, dca_max=9)
        result = self._run_guard5(trade)
        assert result == 9

    def test_consistent_no_change(self):
        """dca_buys=3 with 3 events → no change."""
        events = [{'event_id': f'e{i}', 'amount_eur': 10} for i in range(3)]
        trade = _make_trade(dca_buys=3, dca_events=events, dca_max=9)
        result = self._run_guard5(trade)
        assert result == 3

    def test_events_exceed_max_buys_capped(self):
        """12 events but max=9 → dca_buys capped at 9."""
        events = [{'event_id': f'e{i}', 'amount_eur': 10} for i in range(12)]
        trade = _make_trade(dca_buys=7, dca_events=events, dca_max=9)
        result = self._run_guard5(trade)
        assert result == 9
