"""Tests for bot.order_cleanup (extracted from trailing_bot.py monolith #061)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from bot import order_cleanup
from bot.shared import state


@pytest.fixture(autouse=True)
def _reset_state():
    """Snapshot + restore mutated state attrs around every test."""
    snapshot = {
        'CONFIG': dict(state.CONFIG or {}),
        'open_trades': dict(state.open_trades or {}),
        'bitvavo': state.bitvavo,
        'log': state.log,
        'safe_call': state.safe_call,
        'metrics_collector': state.metrics_collector,
        'OPERATOR_ID': state.OPERATOR_ID,
        'count_active_open_trades': state.count_active_open_trades,
        '_get_pending_count': state._get_pending_count,
        'count_pending_bitvavo_orders': state.count_pending_bitvavo_orders,
        'get_active_grid_markets': state.get_active_grid_markets,
    }
    yield
    for k, v in snapshot.items():
        setattr(state, k, v)


def _setup(orders, *, current=0, reserved=0, pending=0, max_trades=5, open_trades=None):
    bv = MagicMock()
    bv.ordersOpen = MagicMock(return_value=orders)
    bv.cancelOrder = MagicMock(return_value={'orderId': 'cancelled'})
    state.bitvavo = bv
    state.CONFIG = {'MAX_OPEN_TRADES': max_trades, 'LIMIT_ORDER_TIMEOUT_SECONDS': 60}
    state.open_trades = open_trades or {}
    state.log = MagicMock()
    state.safe_call = MagicMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))
    state.metrics_collector = SimpleNamespace(publish=MagicMock())
    state.OPERATOR_ID = ''
    state.count_active_open_trades = MagicMock(return_value=current)
    state._get_pending_count = MagicMock(return_value=reserved)
    state.count_pending_bitvavo_orders = MagicMock(return_value=pending)
    state.get_active_grid_markets = MagicMock(return_value=set())
    return bv


class TestCancelIfCapped:
    def test_skips_when_under_cap(self):
        bv = _setup([{'side': 'buy', 'market': 'BTC-EUR', 'orderId': '1', 'status': 'new'}],
                    current=1, max_trades=5)
        order_cleanup.cancel_open_buys_if_capped()
        bv.cancelOrder.assert_not_called()

    def test_cancels_when_capped(self):
        orders = [{'side': 'buy', 'market': 'XRP-EUR', 'orderId': 'a1', 'status': 'new'}]
        bv = _setup(orders, current=5, max_trades=5)
        order_cleanup.cancel_open_buys_if_capped()
        bv.cancelOrder.assert_called_once_with('XRP-EUR', 'a1')

    def test_skips_market_already_open(self):
        orders = [{'side': 'buy', 'market': 'ETH-EUR', 'orderId': 'b2', 'status': 'open'}]
        bv = _setup(orders, current=5, max_trades=5, open_trades={'ETH-EUR': {}})
        order_cleanup.cancel_open_buys_if_capped()
        bv.cancelOrder.assert_not_called()

    def test_skips_grid_orders(self):
        orders = [{'side': 'buy', 'market': 'SOL-EUR', 'orderId': 'g1', 'status': 'new'}]
        bv = _setup(orders, current=5, max_trades=5)
        state.get_active_grid_markets = MagicMock(return_value={'SOL-EUR'})
        order_cleanup.cancel_open_buys_if_capped()
        bv.cancelOrder.assert_not_called()

    def test_skips_sell_side(self):
        orders = [{'side': 'sell', 'market': 'XRP-EUR', 'orderId': 's1', 'status': 'new'}]
        bv = _setup(orders, current=5, max_trades=5)
        order_cleanup.cancel_open_buys_if_capped()
        bv.cancelOrder.assert_not_called()


class TestCancelByAge:
    def test_disabled_when_timeout_zero(self):
        bv = _setup([])
        state.CONFIG['LIMIT_ORDER_TIMEOUT_SECONDS'] = 0
        order_cleanup.cancel_open_buys_by_age()
        bv.ordersOpen.assert_not_called()

    def test_cancels_old_order(self):
        import time
        old_ms = int((time.time() - 600) * 1000)  # 10 min old
        orders = [{
            'side': 'buy', 'market': 'ARB-EUR', 'orderId': 'old1',
            'status': 'new', 'type': 'limit', 'created': old_ms,
        }]
        bv = _setup(orders)
        order_cleanup.cancel_open_buys_by_age()
        bv.cancelOrder.assert_called_once_with('ARB-EUR', 'old1')

    def test_keeps_fresh_order(self):
        import time
        recent_ms = int((time.time() - 5) * 1000)
        orders = [{
            'side': 'buy', 'market': 'OP-EUR', 'orderId': 'fresh',
            'status': 'new', 'type': 'limit', 'created': recent_ms,
        }]
        bv = _setup(orders)
        order_cleanup.cancel_open_buys_by_age()
        bv.cancelOrder.assert_not_called()

    def test_skips_market_orders(self):
        import time
        old_ms = int((time.time() - 600) * 1000)
        orders = [{
            'side': 'buy', 'market': 'AVAX-EUR', 'orderId': 'mkt1',
            'status': 'new', 'type': 'market', 'created': old_ms,
        }]
        bv = _setup(orders)
        order_cleanup.cancel_open_buys_by_age()
        bv.cancelOrder.assert_not_called()

    def test_skips_no_timestamp(self):
        orders = [{
            'side': 'buy', 'market': 'LINK-EUR', 'orderId': 'nots',
            'status': 'new', 'type': 'limit',
        }]
        bv = _setup(orders)
        order_cleanup.cancel_open_buys_by_age()
        bv.cancelOrder.assert_not_called()


class TestDcaMinScore:
    def _make_ctx(self, **overrides):
        from modules.trading_dca import DCAContext
        defaults = dict(
            config={'DCA_MIN_SCORE': 12.0},
            safe_call=lambda fn, *a, **kw: fn(*a, **kw),
            bitvavo=MagicMock(),
            log=MagicMock(),
            current_open_exposure_eur=lambda: 0.0,
            get_min_order_size=lambda m: 5.0,
            place_buy=MagicMock(),
            is_order_success=lambda r: True,
            save_trades=lambda: None,
            get_candles=MagicMock(return_value=[]),
            close_prices=lambda c: [],
            rsi=lambda p, w: None,
            trade_log_path='',
        )
        defaults.update(overrides)
        return DCAContext(**defaults)

    def test_dca_skipped_when_score_below_min(self):
        from modules.trading_dca import DCAManager, DCASettings
        ctx = self._make_ctx()
        mgr = DCAManager(ctx)
        trade = {'score': 8.0, 'buy_price': 1.0, 'amount': 1.0, 'highest_price': 1.0}
        settings = DCASettings(enabled=True, drop_pct=0.05, max_buys=3, amount_eur=10.0,
                               size_multiplier=1.0, dynamic=False, step_multiplier=1.0)
        mgr.handle_trade('TEST-EUR', trade, current_price=0.95, settings=settings, partial_tp_levels=[])
        ctx.place_buy.assert_not_called()
        log_calls = [c.args[0] for c in ctx.log.call_args_list if c.args]
        assert any('DCA_MIN_SCORE' in m for m in log_calls)

    def test_dca_proceeds_when_score_meets_min(self):
        from modules.trading_dca import DCAManager, DCASettings
        ctx = self._make_ctx()
        mgr = DCAManager(ctx)
        trade = {'score': 14.0, 'buy_price': 1.0, 'amount': 1.0, 'highest_price': 1.0}
        settings = DCASettings(enabled=True, drop_pct=0.05, max_buys=3, amount_eur=10.0,
                               size_multiplier=1.0, dynamic=False, step_multiplier=1.0)
        mgr.handle_trade('TEST-EUR', trade, current_price=0.95, settings=settings, partial_tp_levels=[])
        log_calls = [c.args[0] for c in ctx.log.call_args_list if c.args]
        assert not any('DCA_MIN_SCORE' in m for m in log_calls)

    def test_dca_disabled_when_min_score_zero(self):
        from modules.trading_dca import DCAManager, DCASettings
        ctx = self._make_ctx(config={'DCA_MIN_SCORE': 0.0})
        mgr = DCAManager(ctx)
        trade = {'score': 0.0, 'buy_price': 1.0, 'amount': 1.0, 'highest_price': 1.0}
        settings = DCASettings(enabled=True, drop_pct=0.05, max_buys=3, amount_eur=10.0,
                               size_multiplier=1.0, dynamic=False, step_multiplier=1.0)
        mgr.handle_trade('TEST-EUR', trade, current_price=0.95, settings=settings, partial_tp_levels=[])
        log_calls = [c.args[0] for c in ctx.log.call_args_list if c.args]
        assert not any('DCA_MIN_SCORE' in m for m in log_calls)
