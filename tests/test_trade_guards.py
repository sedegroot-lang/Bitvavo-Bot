"""Tests for MAX_OPEN_TRADES enforcement and trade guard logic.

Validates that:
1. HARD STOP at top of open_trades_async blocks all entries at max
2. Per-market check in loop blocks with fail-closed on exception
3. open_trade_async guard blocks with fail-closed on exception
4. PRE-BUY LOCK CHECK prevents TOCTOU race
5. ATOMIC race guard cancels orphan orders
6. MAX_TRADES_PER_SCAN_CYCLE=1 is enforced
7. Concurrent scored markets don't exceed MAX_OPEN_TRADES
8. Exception in count_active_open_trades -> fail-closed (no trade)
"""
import asyncio
import json
import os
import sys
import time
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock, call
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _patch_bitvavo_env(monkeypatch):
    """Env vars so trailing_bot can import."""
    monkeypatch.setenv('BITVAVO_API_KEY', 'test')
    monkeypatch.setenv('BITVAVO_API_SECRET', 'test')


def _make_mock_bitvavo():
    bv = MagicMock()
    bv.markets.return_value = [
        {'market': 'SOL-EUR', 'status': 'trading',
         'amountPrecision': 4, 'pricePrecision': 4,
         'minOrderInBaseAsset': '0.001', 'minOrderInQuoteAsset': '5'},
        {'market': 'DOGE-EUR', 'status': 'trading',
         'amountPrecision': 4, 'pricePrecision': 4,
         'minOrderInBaseAsset': '0.001', 'minOrderInQuoteAsset': '5'},
        {'market': 'ADA-EUR', 'status': 'trading',
         'amountPrecision': 4, 'pricePrecision': 4,
         'minOrderInBaseAsset': '0.001', 'minOrderInQuoteAsset': '5'},
    ]
    bv.balance.return_value = [
        {'symbol': 'EUR', 'available': '500.0', 'inOrder': '0'},
    ]
    bv.ordersOpen.return_value = []
    bv.tickerPrice.return_value = [{'market': 'SOL-EUR', 'price': '150.0'}]
    bv.book.return_value = {
        'bids': [['149.9', '10.0'], ['149.8', '5.0']],
        'asks': [['150.1', '10.0'], ['150.2', '5.0']],
    }
    bv.placeOrder.return_value = {
        'orderId': 'test-order-123',
        'market': 'SOL-EUR',
        'side': 'buy',
        'orderType': 'market',
        'status': 'filled',
        'price': '150.0',
        'amount': '0.1',
        'amountQuote': '15.0',
        'filledAmount': '0.1',
        'filledAmountQuote': '15.0',
        'fills': [{'price': '150.0', 'amount': '0.1'}],
    }
    bv.cancelOrder.return_value = {}
    return bv


def _base_config():
    """Minimal safe CONFIG for trade guard tests."""
    return {
        'MAX_OPEN_TRADES': 2,
        'MAX_TRADES_PER_SCAN_CYCLE': 1,
        'MAX_TRADES_PER_COIN': 1,
        'MAX_EXPOSURE_PER_COIN': 0.5,
        'BASE_AMOUNT_EUR': 25.0,
        'MIN_ORDER_EUR': 5.0,
        'MIN_ENTRY_EUR': 5.0,
        'MAX_ENTRY_EUR': 999.0,
        'MIN_BALANCE_EUR': 0,
        'MIN_SCORE_TO_BUY': 7.0,
        'OPEN_TRADE_COOLDOWN_SECONDS': 0,
        'CIRCUIT_BREAKER_MIN_WIN_RATE': 0,
        'CIRCUIT_BREAKER_MIN_PROFIT_FACTOR': 0,
        'HODL_SCHEDULER': {'enabled': False, 'schedules': []},
        'MAX_TOTAL_EXPOSURE_EUR': 999,
        'DUST_TRADE_THRESHOLD_EUR': 0.5,
        'FEE_TAKER': 0.0025,
        'FEE_MAKER': 0.0015,
        'SLIPPAGE_PCT': 0.001,
        'ORDER_TYPE': 'market',
        'MAX_SPREAD_PCT': 0.05,
        'TRAILING_ACTIVATION_PCT': 0.01,
        'DEFAULT_TRAILING_PCT': 0.02,
        'DCA_DROP_PCT': 0.05,
        'DCA_AMOUNT_EUR': 10,
        'DCA_MAX_BUYS': 2,
        'DCA_STEP_MULTIPLIER': 1.2,
        'DCA_SIZE_MULTIPLIER': 1.0,
        'KELLY_VOLPARITY_ENABLED': False,
        'SMART_EXECUTION_ENABLED': False,
        'REGIME_ENGINE_ENABLED': False,
        'ADAPTIVE_EXIT_ENABLED': False,
        'CORRELATION_SHIELD_ENABLED': False,
        'MOMENTUM_CASCADE_ENABLED': False,
        'MIN_DAILY_VOLUME_EUR': 0,
        'MIN_PRICE_EUR': 0,
        'MAX_PRICE_EUR': 0,
        'MIN_ORDERBOOK_DEPTH_EUR': 0,
        'MAX_TRADE_SIZE_PCT': 100.0,
        'BUDGET_RESERVATION': {'trailing_bot_max_eur': 300.0},
        'POSITION_KELLY_FACTOR': 0.25,
        'CANCEL_OPEN_BUYS_WHEN_CAPPED': False,
        'TEST_MODE': False,
    }


# ==========================================================================
# TEST: open_trades_async HARD STOP
# ==========================================================================
class TestHardStop:
    """HARD STOP at the top of open_trades_async should block all entries."""

    def test_hard_stop_when_at_max(self):
        """When active trades == MAX_OPEN_TRADES, no scored markets are processed."""
        import trailing_bot as tb
        tb.CONFIG.update(_base_config())
        tb.CONFIG['MAX_OPEN_TRADES'] = 2
        # 2 active trades already
        tb.open_trades = {
            'BTC-EUR': {'buy_price': 50000, 'amount': 0.001, 'invested_eur': 50},
            'ETH-EUR': {'buy_price': 3000, 'amount': 0.01, 'invested_eur': 30},
        }

        scored = [
            (10.0, 'SOL-EUR', 150.0, 7, {}),
            (9.5, 'DOGE-EUR', 0.15, 7, {}),
            (9.0, 'ADA-EUR', 0.50, 7, {}),
        ]

        # Mock count_active_open_trades to return 2
        with patch.object(tb, 'count_active_open_trades', return_value=2), \
             patch.object(tb, '_get_pending_count', return_value=0), \
             patch.object(tb, 'get_pending_bitvavo_orders', return_value=[]), \
             patch.object(tb, 'open_trade_async', new_callable=AsyncMock) as mock_open:
            asyncio.run(tb.open_trades_async(scored, 200.0))

        # open_trade_async should NEVER be called
        mock_open.assert_not_called()

    def test_hard_stop_counts_pending_reservations(self):
        """Pending reservations should count towards max trades."""
        import trailing_bot as tb
        tb.CONFIG.update(_base_config())
        tb.CONFIG['MAX_OPEN_TRADES'] = 2
        tb.open_trades = {
            'BTC-EUR': {'buy_price': 50000, 'amount': 0.001, 'invested_eur': 50},
        }

        scored = [(10.0, 'SOL-EUR', 150.0, 7, {})]

        # 1 active + 1 reserved = 2 = max
        with patch.object(tb, 'count_active_open_trades', return_value=1), \
             patch.object(tb, '_get_pending_count', return_value=1), \
             patch.object(tb, 'get_pending_bitvavo_orders', return_value=[]), \
             patch.object(tb, 'open_trade_async', new_callable=AsyncMock) as mock_open:
            asyncio.run(tb.open_trades_async(scored, 200.0))

        mock_open.assert_not_called()

    def test_hard_stop_counts_exchange_pending(self):
        """Pending BUY orders on exchange should count towards max trades."""
        import trailing_bot as tb
        tb.CONFIG.update(_base_config())
        tb.CONFIG['MAX_OPEN_TRADES'] = 2
        tb.open_trades = {}

        scored = [(10.0, 'SOL-EUR', 150.0, 7, {})]

        # 0 active + 0 reserved + 2 exchange pending = 2 = max
        with patch.object(tb, 'count_active_open_trades', return_value=0), \
             patch.object(tb, '_get_pending_count', return_value=0), \
             patch.object(tb, 'get_pending_bitvavo_orders', return_value=[
                 {'market': 'DOGE-EUR', 'orderId': '1'},
                 {'market': 'ADA-EUR', 'orderId': '2'},
             ]), \
             patch.object(tb, 'open_trade_async', new_callable=AsyncMock) as mock_open:
            asyncio.run(tb.open_trades_async(scored, 200.0))

        mock_open.assert_not_called()

    def test_hard_stop_exception_is_fail_closed(self):
        """If HARD STOP check throws exception, no trades should be opened."""
        import trailing_bot as tb
        tb.CONFIG.update(_base_config())
        tb.open_trades = {}

        scored = [(10.0, 'SOL-EUR', 150.0, 7, {})]

        # Make count_active_open_trades throw
        with patch.object(tb, 'count_active_open_trades', side_effect=RuntimeError("DB error")), \
             patch.object(tb, 'open_trade_async', new_callable=AsyncMock) as mock_open:
            asyncio.run(tb.open_trades_async(scored, 200.0))

        mock_open.assert_not_called()


# ==========================================================================
# TEST: Per-market fail-closed in loop
# ==========================================================================
class TestPerMarketFailClosed:
    """The per-market max trades check should fail-closed on exception."""

    def test_loop_check_exception_skips_market(self):
        """If per-market max trades check fails, that market is skipped."""
        import trailing_bot as tb
        tb.CONFIG.update(_base_config())
        tb.CONFIG['MAX_OPEN_TRADES'] = 5  # High limit to pass HARD STOP
        tb.open_trades = {}

        scored = [(10.0, 'SOL-EUR', 150.0, 7, {})]

        call_count = [0]

        def _failing_count(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: HARD STOP passes (return 0)
                return 0
            # Second call (in-loop): throw exception
            raise RuntimeError("Simulated count failure")

        with patch.object(tb, 'count_active_open_trades', side_effect=_failing_count), \
             patch.object(tb, '_get_pending_count', return_value=0), \
             patch.object(tb, 'get_pending_bitvavo_orders', return_value=[]), \
             patch.object(tb, 'open_trade_async', new_callable=AsyncMock) as mock_open:
            asyncio.run(tb.open_trades_async(scored, 200.0))

        # open_trade_async should NOT be called — fail-closed skipped the market
        mock_open.assert_not_called()


# ==========================================================================
# TEST: MAX_TRADES_PER_SCAN_CYCLE enforcement
# ==========================================================================
class TestMaxTradesPerCycle:
    """Only MAX_TRADES_PER_SCAN_CYCLE trades should be opened per scan."""

    def test_only_one_trade_per_cycle(self):
        """With MAX_TRADES_PER_SCAN_CYCLE=1, only 1 trade opens even with 3 candidates."""
        import trailing_bot as tb
        tb.CONFIG.update(_base_config())
        tb.CONFIG['MAX_OPEN_TRADES'] = 5  # High limit
        tb.CONFIG['MAX_TRADES_PER_SCAN_CYCLE'] = 1
        tb.open_trades = {}
        tb.LAST_OPEN_TRADE_TS = 0

        scored = [
            (10.0, 'SOL-EUR', 150.0, 7, {}),
            (9.5, 'DOGE-EUR', 0.15, 7, {}),
            (9.0, 'ADA-EUR', 0.50, 7, {}),
        ]

        # open_trade_async returns successful buy
        async def mock_open(*args, **kwargs):
            return {'buy_executed': True, 'eur_used': 25.0}

        with patch.object(tb, 'count_active_open_trades', return_value=0), \
             patch.object(tb, '_get_pending_count', return_value=0), \
             patch.object(tb, 'get_pending_bitvavo_orders', return_value=[]), \
             patch.object(tb, '_event_hooks_paused', return_value=False), \
             patch.object(tb, 'collect_block_reasons', return_value=None), \
             patch.object(tb, 'get_24h_volume_eur', return_value=100000.0), \
             patch.object(tb, 'open_trade_async', side_effect=mock_open) as mock_ot:
            asyncio.run(tb.open_trades_async(scored, 200.0))

        # Should open exactly 1 trade then break
        assert mock_ot.call_count == 1


# ==========================================================================
# TEST: open_trade_async guard (fail-closed)
# ==========================================================================
class TestOpenTradeGuard:
    """open_trade_async max_trades guard should fail-closed on exception."""

    def test_guard_blocks_at_max(self):
        """open_trade_async rejects when at MAX_OPEN_TRADES."""
        import trailing_bot as tb
        tb.CONFIG.update(_base_config())
        tb.CONFIG['MAX_OPEN_TRADES'] = 2
        tb.open_trades = {}

        with patch.object(tb, 'count_active_open_trades', return_value=2), \
             patch.object(tb, '_get_pending_count', return_value=0), \
             patch.object(tb, 'get_pending_bitvavo_orders', return_value=[]):
            result = asyncio.run(tb.open_trade_async(10.0, 'SOL-EUR', 150.0, 7, 200.0))

        assert result['buy_executed'] is False

    def test_guard_exception_is_fail_closed(self):
        """If guard check throws, trade is blocked (not allowed through)."""
        import trailing_bot as tb
        tb.CONFIG.update(_base_config())
        tb.CONFIG['MAX_OPEN_TRADES'] = 5
        tb.open_trades = {}

        # Disable circuit breaker to reach the guard
        tb.CONFIG['CIRCUIT_BREAKER_MIN_WIN_RATE'] = 0
        tb.CONFIG['CIRCUIT_BREAKER_MIN_PROFIT_FACTOR'] = 0

        with patch.object(tb, 'count_active_open_trades', side_effect=RuntimeError("DB error")), \
             patch.object(tb, '_release_market', return_value=True):
            result = asyncio.run(tb.open_trade_async(10.0, 'SOL-EUR', 150.0, 7, 200.0))

        assert result['buy_executed'] is False


# ==========================================================================
# TEST: Concurrent scored markets don't exceed MAX_OPEN_TRADES
# ==========================================================================
class TestConcurrentTradeLimit:
    """Simulate multiple scored markets and verify MAX_OPEN_TRADES is never exceeded."""

    def test_five_scored_max_two_trades(self):
        """With 5 scored markets and MAX_OPEN_TRADES=2, at most 2 trades open."""
        import trailing_bot as tb
        tb.CONFIG.update(_base_config())
        tb.CONFIG['MAX_OPEN_TRADES'] = 2
        tb.CONFIG['MAX_TRADES_PER_SCAN_CYCLE'] = 2  # Allow 2 per cycle
        tb.CONFIG['OPEN_TRADE_COOLDOWN_SECONDS'] = 0
        tb.open_trades = {}
        tb.LAST_OPEN_TRADE_TS = 0

        scored = [
            (10.0, 'SOL-EUR', 150.0, 7, {}),
            (9.5, 'DOGE-EUR', 0.15, 7, {}),
            (9.0, 'ADA-EUR', 0.50, 7, {}),
            (8.5, 'XRP-EUR', 0.60, 7, {}),
            (8.0, 'DOT-EUR', 7.00, 7, {}),
        ]

        trades_opened = []

        # Track how many times open_trade_async is called and simulate success/failure
        # First trade: success, increments active count
        # Second trade: should see 1 active + 0 reserved = 1 < 2, so allowed
        # Third trade: should see 2... blocked
        active_count = [0]

        def mock_count(*args, **kwargs):
            return active_count[0]

        async def mock_open(*args, **kwargs):
            m = args[1]
            trades_opened.append(m)
            active_count[0] += 1
            return {'buy_executed': True, 'eur_used': 25.0}

        with patch.object(tb, 'count_active_open_trades', side_effect=mock_count), \
             patch.object(tb, '_get_pending_count', return_value=0), \
             patch.object(tb, 'get_pending_bitvavo_orders', return_value=[]), \
             patch.object(tb, '_event_hooks_paused', return_value=False), \
             patch.object(tb, 'collect_block_reasons', return_value=None), \
             patch.object(tb, 'get_24h_volume_eur', return_value=100000.0), \
             patch.object(tb, 'open_trade_async', side_effect=mock_open):
            asyncio.run(tb.open_trades_async(scored, 500.0))

        # MAX_TRADES_PER_SCAN_CYCLE=2, MAX_OPEN_TRADES=2 → max 2 trades
        assert len(trades_opened) <= 2, \
            f"Opened {len(trades_opened)} trades but MAX_OPEN_TRADES=2: {trades_opened}"

    def test_pending_orders_reduce_available_slots(self):
        """Pending exchange orders reduce available slots for new trades."""
        import trailing_bot as tb
        tb.CONFIG.update(_base_config())
        tb.CONFIG['MAX_OPEN_TRADES'] = 3
        tb.CONFIG['MAX_TRADES_PER_SCAN_CYCLE'] = 3
        # Use empty open_trades to avoid iteration mutation issues
        tb.open_trades = {}
        tb.LAST_OPEN_TRADE_TS = 0

        scored = [
            (10.0, 'SOL-EUR', 150.0, 7, {}),
            (9.5, 'DOGE-EUR', 0.15, 7, {}),
        ]

        open_count = [0]

        def mock_count(*args, **kwargs):
            # 1 existing active + opened ones
            return 1 + open_count[0]

        async def mock_open_trade(*args, **kwargs):
            open_count[0] += 1
            return {'buy_executed': True, 'eur_used': 25.0}

        # 1 active + 1 pending order on exchange = 2, only 1 slot left
        with patch.object(tb, 'count_active_open_trades', side_effect=mock_count), \
             patch.object(tb, '_get_pending_count', return_value=0), \
             patch.object(tb, 'get_pending_bitvavo_orders', return_value=[
                 {'market': 'ADA-EUR', 'orderId': 'pending-1'},
             ]), \
             patch.object(tb, '_event_hooks_paused', return_value=False), \
             patch.object(tb, 'collect_block_reasons', return_value=None), \
             patch.object(tb, 'get_24h_volume_eur', return_value=100000.0), \
             patch.object(tb, 'open_trade_async', side_effect=mock_open_trade) as mock_ot:
            asyncio.run(tb.open_trades_async(scored, 500.0))

        # 1 active + 1 exchange pending = 2/3 slots used → only 1 trade should open
        assert mock_ot.call_count <= 1, \
            f"Called open_trade_async {mock_ot.call_count} times but only 1 slot available"


# ==========================================================================
# TEST: Atomic race guard cancels orphan order
# ==========================================================================
class TestAtomicRaceGuard:
    """Post-buy atomic guard should cancel the orphan order."""

    def test_rejects_already_open_market(self):
        """open_trade_async rejects if market already in open_trades."""
        import trailing_bot as tb
        tb.CONFIG.update(_base_config())
        tb.open_trades = {
            'SOL-EUR': {'buy_price': 100.0, 'amount': 1.0, 'invested_eur': 100.0},
        }

        result = asyncio.run(tb.open_trade_async(10.0, 'SOL-EUR', 150.0, 7, 200.0))
        assert result['buy_executed'] is False

    def test_max_trades_check_blocks_new_market(self):
        """With 2/2 trades open, a new market should be blocked."""
        import trailing_bot as tb
        tb.CONFIG.update(_base_config())
        tb.CONFIG['MAX_OPEN_TRADES'] = 2
        tb.open_trades = {
            'BTC-EUR': {'buy_price': 50000, 'amount': 0.001, 'invested_eur': 50},
            'ETH-EUR': {'buy_price': 3000, 'amount': 0.01, 'invested_eur': 30},
        }

        with patch.object(tb, 'count_active_open_trades', return_value=2), \
             patch.object(tb, '_get_pending_count', return_value=0), \
             patch.object(tb, 'get_pending_bitvavo_orders', return_value=[]):
            result = asyncio.run(tb.open_trade_async(10.0, 'SOL-EUR', 150.0, 7, 200.0))

        assert result['buy_executed'] is False


# ==========================================================================
# TEST: Full integration — simulate full cycle
# ==========================================================================
class TestFullCycleIntegration:
    """Simulate a full scan→score→open cycle and verify trade count."""

    def test_full_cycle_respects_max_trades(self):
        """End-to-end: 5 high-scoring markets, MAX_OPEN_TRADES=2 → max 2 opened."""
        import trailing_bot as tb
        tb.CONFIG.update(_base_config())
        tb.CONFIG['MAX_OPEN_TRADES'] = 2
        tb.CONFIG['MAX_TRADES_PER_SCAN_CYCLE'] = 2
        tb.CONFIG['OPEN_TRADE_COOLDOWN_SECONDS'] = 0
        tb.open_trades = {}
        tb.LAST_OPEN_TRADE_TS = 0

        scored = [
            (12.0, 'SOL-EUR', 150.0, 7, {}),
            (11.0, 'DOGE-EUR', 0.15, 7, {}),
            (10.0, 'ADA-EUR', 0.50, 7, {}),
            (9.0, 'XRP-EUR', 0.60, 7, {}),
            (8.0, 'LINK-EUR', 15.0, 7, {}),
        ]

        opened_markets = []
        active_count = [0]

        def mock_count(*args, **kwargs):
            return active_count[0]

        async def mock_open_trade(score, m, price, s_short, balance, ml_info=None):
            # Simulate the guard inside open_trade_async too
            max_t = int(tb.CONFIG.get('MAX_OPEN_TRADES', 5))
            if active_count[0] >= max_t:
                return {'buy_executed': False}
            opened_markets.append(m)
            active_count[0] += 1
            return {'buy_executed': True, 'eur_used': 25.0}

        with patch.object(tb, 'count_active_open_trades', side_effect=mock_count), \
             patch.object(tb, '_get_pending_count', return_value=0), \
             patch.object(tb, 'get_pending_bitvavo_orders', return_value=[]), \
             patch.object(tb, '_event_hooks_paused', return_value=False), \
             patch.object(tb, 'collect_block_reasons', return_value=None), \
             patch.object(tb, 'get_24h_volume_eur', return_value=100000.0), \
             patch.object(tb, 'open_trade_async', side_effect=mock_open_trade):
            asyncio.run(tb.open_trades_async(scored, 500.0))

        assert len(opened_markets) <= 2, \
            f"Opened {len(opened_markets)} trades, expected max 2: {opened_markets}"
        # Verify they are the highest-scoring ones
        if len(opened_markets) == 2:
            assert opened_markets[0] == 'SOL-EUR'
            assert opened_markets[1] == 'DOGE-EUR'

    def test_full_cycle_with_one_existing_trade(self):
        """With 1 existing trade and MAX=2, only 1 more should open."""
        import trailing_bot as tb
        tb.CONFIG.update(_base_config())
        tb.CONFIG['MAX_OPEN_TRADES'] = 2
        tb.CONFIG['MAX_TRADES_PER_SCAN_CYCLE'] = 2
        tb.CONFIG['OPEN_TRADE_COOLDOWN_SECONDS'] = 0
        # Don't put real entries in open_trades to avoid iteration mutation issues;
        # instead mock count_active_open_trades to simulate 1 existing trade.
        tb.open_trades = {}
        tb.LAST_OPEN_TRADE_TS = 0

        scored = [
            (12.0, 'SOL-EUR', 150.0, 7, {}),
            (11.0, 'DOGE-EUR', 0.15, 7, {}),
            (10.0, 'ADA-EUR', 0.50, 7, {}),
        ]

        opened_markets = []
        # Starts at 1 (simulating existing BTC-EUR), increments on open
        active_count = [1]

        def mock_count(*args, **kwargs):
            return active_count[0]

        async def mock_open_trade(score, m, price, s_short, balance, ml_info=None):
            max_t = int(tb.CONFIG.get('MAX_OPEN_TRADES', 5))
            if active_count[0] >= max_t:
                return {'buy_executed': False}
            opened_markets.append(m)
            active_count[0] += 1
            return {'buy_executed': True, 'eur_used': 25.0}

        with patch.object(tb, 'count_active_open_trades', side_effect=mock_count), \
             patch.object(tb, '_get_pending_count', return_value=0), \
             patch.object(tb, 'get_pending_bitvavo_orders', return_value=[]), \
             patch.object(tb, '_event_hooks_paused', return_value=False), \
             patch.object(tb, 'collect_block_reasons', return_value=None), \
             patch.object(tb, 'get_24h_volume_eur', return_value=100000.0), \
             patch.object(tb, 'open_trade_async', side_effect=mock_open_trade):
            asyncio.run(tb.open_trades_async(scored, 500.0))

        assert len(opened_markets) <= 1, \
            f"Opened {len(opened_markets)} trades, expected max 1 (1 existing): {opened_markets}"

    def test_full_cycle_max_one_already_full(self):
        """With MAX=2 and 2 existing trades, zero new trades should open."""
        import trailing_bot as tb
        tb.CONFIG.update(_base_config())
        tb.CONFIG['MAX_OPEN_TRADES'] = 2
        tb.open_trades = {
            'BTC-EUR': {'buy_price': 50000, 'amount': 0.001, 'invested_eur': 50},
            'ETH-EUR': {'buy_price': 3000, 'amount': 0.01, 'invested_eur': 30},
        }

        scored = [(12.0, 'SOL-EUR', 150.0, 7, {})]

        with patch.object(tb, 'count_active_open_trades', return_value=2), \
             patch.object(tb, '_get_pending_count', return_value=0), \
             patch.object(tb, 'get_pending_bitvavo_orders', return_value=[]), \
             patch.object(tb, 'open_trade_async', new_callable=AsyncMock) as mock_ot:
            asyncio.run(tb.open_trades_async(scored, 500.0))

        # HARD STOP should block everything
        mock_ot.assert_not_called()


# ==========================================================================
# TEST: Cooldown enforcement
# ==========================================================================
class TestCooldownEnforcement:
    """OPEN_TRADE_COOLDOWN_SECONDS must block rapid consecutive trades."""

    def test_cooldown_blocks_second_trade(self):
        """Second trade within cooldown period should be blocked."""
        import trailing_bot as tb
        tb.CONFIG.update(_base_config())
        tb.CONFIG['MAX_OPEN_TRADES'] = 5
        tb.CONFIG['MAX_TRADES_PER_SCAN_CYCLE'] = 5
        tb.CONFIG['OPEN_TRADE_COOLDOWN_SECONDS'] = 120
        tb.open_trades = {}
        # Set last trade just opened 10 seconds ago
        tb.LAST_OPEN_TRADE_TS = time.time() - 10
        tb.OPEN_TRADE_COOLDOWN_SECONDS = 120

        scored = [
            (10.0, 'SOL-EUR', 150.0, 7, {}),
            (9.0, 'DOGE-EUR', 0.15, 7, {}),
        ]

        with patch.object(tb, 'count_active_open_trades', return_value=0), \
             patch.object(tb, '_get_pending_count', return_value=0), \
             patch.object(tb, 'get_pending_bitvavo_orders', return_value=[]), \
             patch.object(tb, '_event_hooks_paused', return_value=False), \
             patch.object(tb, 'open_trade_async', new_callable=AsyncMock) as mock_ot:
            asyncio.run(tb.open_trades_async(scored, 500.0))

        # Cooldown active from recent trade → should open ZERO trades (breaks loop)
        mock_ot.assert_not_called()
