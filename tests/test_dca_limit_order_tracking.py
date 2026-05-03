# -*- coding: utf-8 -*-
"""FIX #073 — DCA limit-order tracking (placed vs filled).

Verifies:
  1. MAKER limit order (status='new', filled=0) does NOT mutate dca_buys/invested_eur
     and does NOT send "GEVULD" Telegram. Pending orderId is stashed.
  2. Pending limit order that has filled is detected on next iteration → DCA recorded
     with ACTUAL fill values, GEVULD Telegram sent, pending cleared.
  3. Pending limit order still resting → no second order is placed (no cascading).
  4. Pending limit order older than DCA_LIMIT_ORDER_TIMEOUT_SECONDS → cancelOrder
     called, pending cleared.
  5. MARKET order (status='filled', filledAmount>0) → existing flow, GEVULD sent
     immediately on placement.
  6. Pending limit order has been cancelled externally → cleared without re-placing.
  7. Partial fill on cancelled order → recorded as DCA event for the partial.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.trading_dca import DCAContext, DCAManager, DCASettings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(*, place_buy_resp=None, get_order_resp=None, **overrides):
    bv = MagicMock()
    if get_order_resp is not None:
        bv.getOrder = MagicMock(return_value=get_order_resp)
    else:
        bv.getOrder = MagicMock(return_value=None)
    bv.ordersOpen = MagicMock(return_value=[])
    bv.cancelOrder = MagicMock(return_value={'orderId': 'cancelled'})

    def _safe_call(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except Exception:
            return None

    defaults = dict(
        config={
            'RSI_DCA_THRESHOLD': 100,
            'SMART_DCA_ENABLED': False,
            'BASE_AMOUNT_EUR': 30,
            'MAX_TOTAL_EXPOSURE_EUR': 0,
            'DCA_LIMIT_ORDER_TIMEOUT_SECONDS': 600,
            'BITVAVO_OPERATOR_ID': '1',
        },
        safe_call=_safe_call,
        bitvavo=bv,
        log=MagicMock(),
        current_open_exposure_eur=MagicMock(return_value=100.0),
        get_min_order_size=MagicMock(return_value=0.001),
        place_buy=MagicMock(return_value=place_buy_resp or {
            'status': 'new', 'orderId': 'ORDER-LIMIT-1',
            'filledAmount': '0', 'filledAmountQuote': '0', 'price': '0.044',
        }),
        is_order_success=MagicMock(return_value=True),
        save_trades=MagicMock(),
        get_candles=MagicMock(return_value=[]),
        close_prices=MagicMock(return_value=[]),
        rsi=MagicMock(return_value=None),
        trade_log_path='',
        send_alert=MagicMock(),
    )
    defaults.update(overrides)
    return DCAContext(**defaults)


def _make_settings(**overrides):
    defaults = dict(
        enabled=True, dynamic=False, max_buys=3,
        drop_pct=0.03, step_multiplier=1.0,
        amount_eur=80.0, size_multiplier=1.0,
        max_buys_per_iteration=3,
    )
    defaults.update(overrides)
    return DCASettings(**defaults)


def _make_trade(**overrides):
    defaults = dict(
        market='ENJ-EUR',
        buy_price=0.05, highest_price=0.05,
        amount=5000.0, invested_eur=250.0,
        initial_invested_eur=250.0, total_invested_eur=250.0,
        dca_buys=0, dca_max=3, dca_events=[],
        dca_next_price=0.0485, last_dca_price=0.05,
        tp_levels_done=[False] * 3, tp_last_time=0.0,
        partial_tp_returned_eur=0.0, opened_ts=time.time(),
    )
    defaults.update(overrides)
    return defaults


# ===========================================================================
# Test 1: Unfilled MAKER limit order — no mutations, pending stashed
# ===========================================================================

class TestUnfilledLimitOrderStashes:
    def test_no_dca_buys_increment_when_limit_resting(self):
        ctx = _make_ctx()  # default place_buy returns status='new', filled=0
        mgr = DCAManager(ctx)
        trade = _make_trade(dca_buys=0, dca_events=[])
        before_invested = trade['invested_eur']
        before_amount = trade['amount']
        # current_price 0.044 < dca_next_price 0.0485 → triggers placement
        mgr._execute_fixed_dca('ENJ-EUR', trade, 0.044, _make_settings(), 1.0)
        assert trade['dca_buys'] == 0, 'dca_buys must NOT increment on resting limit'
        assert len(trade['dca_events']) == 0, 'no DCA event should be recorded'
        assert trade['invested_eur'] == pytest.approx(before_invested), 'invested_eur must NOT change'
        assert trade['amount'] == pytest.approx(before_amount), 'amount must NOT change'

    def test_pending_order_id_stashed(self):
        ctx = _make_ctx()
        mgr = DCAManager(ctx)
        trade = _make_trade()
        mgr._execute_fixed_dca('ENJ-EUR', trade, 0.044, _make_settings(), 1.0)
        assert trade.get('pending_dca_order_id') == 'ORDER-LIMIT-1'
        assert trade.get('pending_dca_order_market') == 'ENJ-EUR'
        assert float(trade.get('pending_dca_order_eur', 0)) == pytest.approx(80.0)
        assert trade.get('pending_dca_order_ts', 0) > 0

    def test_no_filled_telegram_when_limit_resting(self):
        ctx = _make_ctx()
        mgr = DCAManager(ctx)
        mgr._execute_fixed_dca('ENJ-EUR', _make_trade(), 0.044, _make_settings(), 1.0)
        # send_alert called once with PLACED, never with GEVULD
        assert ctx.send_alert.call_count == 1
        msg = ctx.send_alert.call_args[0][0]
        assert 'GEPLAATST' in msg
        assert 'GEVULD' not in msg
        assert '\u20ac0.00' not in msg, 'must not show €0.00 amount'


# ===========================================================================
# Test 2: Pending limit order fills on next iteration
# ===========================================================================

class TestPendingFillsRecorded:
    def test_pending_fill_records_dca_with_actual_amounts(self):
        ctx = _make_ctx(get_order_resp={
            'orderId': 'ORDER-LIMIT-1', 'status': 'filled',
            'filledAmount': '1818.18', 'filledAmountQuote': '80.00', 'price': '0.044',
        })
        mgr = DCAManager(ctx)
        trade = _make_trade()
        # Pre-stash pending state (as if previous iter placed it)
        trade['pending_dca_order_id'] = 'ORDER-LIMIT-1'
        trade['pending_dca_order_ts'] = time.time() - 30
        trade['pending_dca_order_eur'] = 80.0
        trade['pending_dca_order_price'] = 0.044
        trade['pending_dca_order_market'] = 'ENJ-EUR'
        before_invested = trade['invested_eur']

        # Use a price ABOVE dca_next_price so no NEW DCA is attempted —
        # this isolates the pending-check behaviour.
        trade['dca_next_price'] = 0.04
        mgr._execute_fixed_dca('ENJ-EUR', trade, 0.045, _make_settings(), 1.0)

        assert trade['dca_buys'] == 1
        assert len(trade['dca_events']) == 1
        assert trade['dca_events'][0]['amount_eur'] == pytest.approx(80.0)
        assert trade['invested_eur'] == pytest.approx(before_invested + 80.0)
        # Pending cleared
        assert 'pending_dca_order_id' not in trade
        # GEVULD Telegram sent
        assert any('GEVULD' in c.args[0] for c in ctx.send_alert.call_args_list)


# ===========================================================================
# Test 3: Pending still open — do NOT place a second order
# ===========================================================================

class TestNoCascadingWhilePending:
    def test_still_open_skips_placement(self):
        # getOrder returns the same order still resting on book
        ctx = _make_ctx(get_order_resp={
            'orderId': 'ORDER-LIMIT-1', 'status': 'new',
            'filledAmount': '0', 'filledAmountQuote': '0', 'price': '0.044',
        })
        mgr = DCAManager(ctx)
        trade = _make_trade()
        trade['pending_dca_order_id'] = 'ORDER-LIMIT-1'
        trade['pending_dca_order_ts'] = time.time() - 60
        trade['pending_dca_order_eur'] = 80.0
        trade['pending_dca_order_market'] = 'ENJ-EUR'

        # Price would normally trigger DCA
        mgr._execute_fixed_dca('ENJ-EUR', trade, 0.040, _make_settings(), 1.0)

        # No new place_buy call
        ctx.place_buy.assert_not_called()
        # No cancel either (still within timeout)
        ctx.bitvavo.cancelOrder.assert_not_called()
        # Pending still in place
        assert trade.get('pending_dca_order_id') == 'ORDER-LIMIT-1'


# ===========================================================================
# Test 4: Pending timed out → cancel + clear
# ===========================================================================

class TestPendingTimeoutCancelled:
    def test_timed_out_pending_is_cancelled(self):
        ctx = _make_ctx(get_order_resp={
            'orderId': 'ORDER-LIMIT-1', 'status': 'new',
            'filledAmount': '0', 'filledAmountQuote': '0', 'price': '0.044',
        })
        ctx.config['DCA_LIMIT_ORDER_TIMEOUT_SECONDS'] = 60
        mgr = DCAManager(ctx)
        trade = _make_trade()
        trade['pending_dca_order_id'] = 'ORDER-LIMIT-1'
        trade['pending_dca_order_ts'] = time.time() - 9999  # very old
        trade['pending_dca_order_eur'] = 80.0
        trade['pending_dca_order_market'] = 'ENJ-EUR'

        mgr._execute_fixed_dca('ENJ-EUR', trade, 0.040, _make_settings(), 1.0)

        # cancelOrder called (any signature variant)
        assert ctx.bitvavo.cancelOrder.called, 'cancelOrder must be called for stale order'
        cancel_args = ctx.bitvavo.cancelOrder.call_args.args
        assert cancel_args[0] == 'ENJ-EUR'
        assert cancel_args[1] == 'ORDER-LIMIT-1'
        # Pending cleared
        assert 'pending_dca_order_id' not in trade
        # No new order placed in same loop iter — wait for next loop
        ctx.place_buy.assert_not_called()
        # dca_buys NOT incremented (no fill)
        assert trade['dca_buys'] == 0


# ===========================================================================
# Test 5: MARKET order fills immediately — existing flow + GEVULD
# ===========================================================================

class TestMarketOrderImmediateFill:
    def test_market_fill_records_and_sends_gevuld(self):
        ctx = _make_ctx(place_buy_resp={
            'status': 'filled', 'orderId': 'ORDER-MKT-1',
            'filledAmount': '1818.18', 'filledAmountQuote': '80.00',
        })
        mgr = DCAManager(ctx)
        trade = _make_trade()
        before_invested = trade['invested_eur']
        mgr._execute_fixed_dca('ENJ-EUR', trade, 0.044, _make_settings(), 1.0)
        assert trade['dca_buys'] == 1
        assert trade['invested_eur'] == pytest.approx(before_invested + 80.0)
        # No pending stashed
        assert 'pending_dca_order_id' not in trade
        # GEVULD sent
        msgs = [c.args[0] for c in ctx.send_alert.call_args_list]
        assert any('GEVULD' in m for m in msgs), f'expected GEVULD in {msgs}'
        assert not any('GEPLAATST' in m for m in msgs)


# ===========================================================================
# Test 6: Pending was cancelled externally → clear, allow placement
# ===========================================================================

class TestExternallyCancelledPendingClears:
    def test_cancelled_pending_is_cleared(self):
        ctx = _make_ctx(get_order_resp={
            'orderId': 'ORDER-LIMIT-1', 'status': 'cancelled',
            'filledAmount': '0', 'filledAmountQuote': '0',
        })
        mgr = DCAManager(ctx)
        trade = _make_trade()
        trade['pending_dca_order_id'] = 'ORDER-LIMIT-1'
        trade['pending_dca_order_ts'] = time.time() - 30
        trade['pending_dca_order_eur'] = 80.0
        trade['pending_dca_order_market'] = 'ENJ-EUR'
        # Use a current_price ABOVE target so the inner ladder loop skips placement.
        # last_dca_price=0.05, drop_pct=0.03 -> target=0.0485. Use price=0.05.
        mgr._execute_fixed_dca('ENJ-EUR', trade, 0.05, _make_settings(), 1.0)
        assert 'pending_dca_order_id' not in trade
        assert trade['dca_buys'] == 0
        # No place_buy call (price above target after pending was cleared)
        ctx.place_buy.assert_not_called()


# ===========================================================================
# Test 7: Partial fill on cancelled order is recorded
# ===========================================================================

class TestPartialFillOnCancel:
    def test_partial_fill_recorded_when_status_cancelled(self):
        ctx = _make_ctx(get_order_resp={
            'orderId': 'ORDER-LIMIT-1', 'status': 'cancelled',
            'filledAmount': '900.0', 'filledAmountQuote': '40.00', 'price': '0.044',
        })
        mgr = DCAManager(ctx)
        trade = _make_trade()
        trade['pending_dca_order_id'] = 'ORDER-LIMIT-1'
        trade['pending_dca_order_ts'] = time.time() - 30
        trade['pending_dca_order_eur'] = 80.0
        trade['pending_dca_order_market'] = 'ENJ-EUR'
        before_invested = trade['invested_eur']
        # current_price 0.05 > target 0.0485 -> no new placement, isolates partial-fill record
        mgr._execute_fixed_dca('ENJ-EUR', trade, 0.05, _make_settings(), 1.0)
        # Partial 40 EUR recorded
        assert trade['dca_buys'] == 1
        assert trade['invested_eur'] == pytest.approx(before_invested + 40.0)
        assert 'pending_dca_order_id' not in trade
        ctx.place_buy.assert_not_called()
