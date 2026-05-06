# -*- coding: utf-8 -*-
"""FIX #087 — Per-trade DCA action cooldown stops placement spam loops.

Verifies:
  1. handle_trade returns early with "action_cooldown" audit when last_dca_action_ts
     is recent (within DCA_ACTION_COOLDOWN_SECONDS). place_buy is NOT called.
  2. handle_trade proceeds to placement when cooldown has expired.
  3. _stash_pending_dca, _clear_pending_dca, _record_filled_dca and order_failed
     paths each stamp last_dca_action_ts.
  4. Setting DCA_ACTION_COOLDOWN_SECONDS=0 disables the gate.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.trading_dca import DCAContext, DCAManager, DCASettings


def _make_ctx(tmp_path, *, place_buy_resp=None, **overrides):
    bv = MagicMock()
    bv.getOrder = MagicMock(return_value=None)
    bv.ordersOpen = MagicMock(return_value=[])
    bv.cancelOrder = MagicMock(return_value={'orderId': 'cancelled'})
    bv.balance = MagicMock(return_value=[{'symbol': 'EUR', 'available': '1000'}])

    def _safe_call(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except Exception:
            return None

    log_path = tmp_path / "trade_log.json"
    log_path.write_text("{}", encoding="utf-8")
    audit_dir = tmp_path / "logs"
    audit_dir.mkdir(exist_ok=True)

    defaults = dict(
        config={
            'RSI_DCA_THRESHOLD': 100,
            'SMART_DCA_ENABLED': False,
            'BASE_AMOUNT_EUR': 30,
            'MAX_TOTAL_EXPOSURE_EUR': 0,
            'DCA_LIMIT_ORDER_TIMEOUT_SECONDS': 600,
            'BITVAVO_OPERATOR_ID': '1',
            'DCA_ACTION_COOLDOWN_SECONDS': 300,
            'DCA_SYNC_COOLDOWN_SEC': 0,
            'DCA_MIN_SCORE': 0,
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
        trade_log_path=str(log_path),
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
        tp_levels_done=[False, False, False], tp_last_time=0.0,
        partial_tp_returned_eur=0.0, opened_ts=time.time(),
    )
    defaults.update(overrides)
    return defaults


def _last_audit_for(mgr, market):
    """Read the last DCA-audit JSONL line for a market from the manager's audit path."""
    audit_path = Path(mgr._audit_path)
    if not audit_path.exists():
        return None
    last = None
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if ev.get("market") == market:
            last = ev
    return last


def _new_mgr(ctx, tmp_path):
    mgr = DCAManager(ctx)
    mgr._audit_path = str(tmp_path / "dca_audit.log")
    return mgr


class TestActionCooldownGate:
    def test_recent_action_blocks_placement(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        mgr = _new_mgr(ctx, tmp_path)
        trade = _make_trade()
        trade["last_dca_action_ts"] = time.time() - 10  # 10s ago, well under 300s

        mgr.handle_trade('ENJ-EUR', trade, 0.044, _make_settings(), partial_tp_levels=[])

        # place_buy must NOT be called
        ctx.place_buy.assert_not_called()
        # No pending stashed
        assert "pending_dca_order_id" not in trade
        # Audit reason
        last = _last_audit_for(mgr, 'ENJ-EUR')
        assert last is not None
        assert last["reason"] == "action_cooldown"

    def test_expired_cooldown_allows_placement(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        mgr = _new_mgr(ctx, tmp_path)
        trade = _make_trade()
        # 400s ago > 300s cooldown
        trade["last_dca_action_ts"] = time.time() - 400

        mgr.handle_trade('ENJ-EUR', trade, 0.044, _make_settings(), partial_tp_levels=[])

        ctx.place_buy.assert_called_once()
        assert trade.get("pending_dca_order_id") == "ORDER-LIMIT-1"

    def test_cooldown_zero_disables_gate(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        ctx.config["DCA_ACTION_COOLDOWN_SECONDS"] = 0
        mgr = _new_mgr(ctx, tmp_path)
        trade = _make_trade()
        trade["last_dca_action_ts"] = time.time() - 1  # just placed

        mgr.handle_trade('ENJ-EUR', trade, 0.044, _make_settings(), partial_tp_levels=[])

        ctx.place_buy.assert_called_once()

    def test_no_prior_action_allows_placement(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        mgr = _new_mgr(ctx, tmp_path)
        trade = _make_trade()
        # last_dca_action_ts not set at all

        mgr.handle_trade('ENJ-EUR', trade, 0.044, _make_settings(), partial_tp_levels=[])

        ctx.place_buy.assert_called_once()


class TestActionTimestampStamping:
    def test_stash_pending_stamps_timestamp(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        mgr = _new_mgr(ctx, tmp_path)
        trade = _make_trade()
        before = time.time()
        mgr._stash_pending_dca(trade, 'ENJ-EUR', 'OID-1', 80.0, 0.044)
        after = time.time()
        assert before <= float(trade["last_dca_action_ts"]) <= after

    def test_clear_pending_stamps_timestamp(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        mgr = _new_mgr(ctx, tmp_path)
        trade = _make_trade()
        trade["pending_dca_order_id"] = "OID-1"
        trade["last_dca_action_ts"] = 0.0
        before = time.time()
        mgr._clear_pending_dca(trade)
        after = time.time()
        assert "pending_dca_order_id" not in trade
        assert before <= float(trade["last_dca_action_ts"]) <= after

    def test_order_failed_stamps_timestamp(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        ctx.is_order_success = MagicMock(return_value=False)
        mgr = _new_mgr(ctx, tmp_path)
        trade = _make_trade()
        before = time.time()
        mgr._execute_fixed_dca('ENJ-EUR', trade, 0.044, _make_settings(), 1.0)
        after = time.time()
        assert before <= float(trade.get("last_dca_action_ts", 0)) <= after
        last = _last_audit_for(mgr, 'ENJ-EUR')
        assert last is not None
        assert last["reason"] == "order_failed"
