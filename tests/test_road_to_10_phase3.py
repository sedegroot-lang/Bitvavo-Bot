"""Tests for Road-to-10 #062: scheduler facade, ws_price_feed, entry_pipeline."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from bot import scheduler, ws_price_feed
from bot.entry_pipeline import EntryDecision, decide_entry, decide_order_type
from bot.shared import state


@pytest.fixture(autouse=True)
def _restore_state():
    snap = {
        'CONFIG': dict(state.CONFIG or {}),
        'log': state.log,
        'monitoring_manager': getattr(state, 'monitoring_manager', None),
        'open_trades': dict(state.open_trades or {}),
        'send_alert': state.send_alert,
    }
    yield
    for k, v in snap.items():
        setattr(state, k, v)
    # also clear ws latest cache between tests
    with ws_price_feed._LOCK:
        ws_price_feed._LATEST.clear()


class TestScheduler:
    def test_no_op_when_manager_missing(self):
        state.monitoring_manager = None
        # all three are no-ops, should not raise
        scheduler.start_heartbeat_monitor()
        scheduler.start_heartbeat_writer()
        scheduler.start_reservation_watchdog()

    def test_invokes_manager_when_present(self):
        mgr = MagicMock()
        state.monitoring_manager = mgr
        state.send_alert = MagicMock()
        state.log = MagicMock()
        scheduler.start_heartbeat_monitor(interval=10)
        mgr.start_heartbeat_monitor.assert_called_once()

    def test_start_all_returns_status_dict(self):
        state.monitoring_manager = MagicMock()
        out = scheduler.start_all_schedulers()
        assert set(out.keys()) == {'heartbeat_monitor', 'heartbeat_writer', 'reservation_watchdog'}
        assert all(out.values())


class TestWSPriceFeed:
    def test_disabled_by_default(self):
        state.CONFIG = {}  # no WS_PRICE_FEED_ENABLED
        state.log = MagicMock()
        feed = ws_price_feed.WSPriceFeed(['BTC-EUR'])
        assert feed.start() is False

    def test_latest_price_returns_none_when_empty(self):
        assert ws_price_feed.latest_price('BTC-EUR') is None

    def test_on_ticker_caches_price(self):
        feed = ws_price_feed.WSPriceFeed(['ETH-EUR'])
        feed._on_ticker({'market': 'ETH-EUR', 'lastPrice': '3500.5', 'bestBid': '3500', 'bestAsk': '3501'})
        assert ws_price_feed.latest_price('ETH-EUR') == pytest.approx(3500.5)
        book = ws_price_feed.latest_book('ETH-EUR')
        assert book == {'bid': 3500.0, 'ask': 3501.0}

    def test_stale_price_returns_none(self):
        with ws_price_feed._LOCK:
            ws_price_feed._LATEST['SOL-EUR'] = {'price': 100.0, 'bid': 99, 'ask': 101, 'ts': time.time() - 60}
        assert ws_price_feed.latest_price('SOL-EUR', max_age_s=5) is None


class TestEntryPipeline:
    def test_blocks_when_score_low(self):
        d = decide_entry(market='BTC-EUR', score=4.0, min_score=7.0, eur_amount=25.0)
        assert d.proceed is False
        assert 'score_below_min' in d.reason

    def test_blocks_when_zero_eur(self):
        d = decide_entry(market='BTC-EUR', score=10.0, min_score=7.0, eur_amount=0.0)
        assert d.proceed is False
        assert d.reason == 'zero_eur'

    def test_passes_with_good_inputs(self):
        d = decide_entry(market='BTC-EUR', score=10.0, min_score=7.0, eur_amount=25.0,
                         spread_pct=0.0005, config={'ORDER_TYPE': 'auto'})
        assert d.proceed is True
        assert d.order_type == 'limit'  # tight spread → limit

    def test_block_reason_short_circuits(self):
        d = decide_entry(market='X', score=10, min_score=7, eur_amount=25,
                         block_reason='regime_bearish')
        assert d.proceed is False
        assert d.reason == 'regime_bearish'

    def test_decide_order_type_force_limit(self):
        assert decide_order_type({'LIMIT_ORDER_PREFER': True}, spread_pct=0.05) == 'limit'

    def test_decide_order_type_force_market(self):
        assert decide_order_type({'ORDER_TYPE': 'market'}, spread_pct=0.0001) == 'market'

    def test_decide_order_type_auto_wide_spread(self):
        assert decide_order_type({'ORDER_TYPE': 'auto'}, spread_pct=0.005) == 'market'

    def test_decide_order_type_auto_no_spread(self):
        assert decide_order_type({'ORDER_TYPE': 'auto'}, spread_pct=None) == 'market'
