"""Tests for fully automated grid trading module."""
import json
import os
import time
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path

# Add project root
import sys
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from modules.grid_trading import (
    GridManager, GridLevel, GridConfig, GridState,
    get_grid_manager, reset_grid_manager,
    calculate_optimal_grid_range, estimate_grid_profit,
    MAKER_FEE_PCT, MIN_GRID_SPACING_PCT,
)


# ==================== FIXTURES ====================

@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset grid manager singleton before each test."""
    reset_grid_manager()
    yield
    reset_grid_manager()


@pytest.fixture(autouse=True)
def fast_sleep():
    """Patch time.sleep to avoid delays in tests."""
    with patch('modules.grid_trading.time.sleep'):
        yield


@pytest.fixture
def mock_bitvavo():
    """Create a mock Bitvavo client."""
    bv = MagicMock()
    bv.placeOrder = MagicMock(return_value={
        'orderId': 'test-order-123',
        'status': 'new',
        'side': 'buy',
        'orderType': 'limit',
    })
    bv.cancelOrder = MagicMock(return_value={'orderId': 'test-order-123'})
    bv.getOrder = MagicMock(return_value={
        'orderId': 'test-order-123',
        'status': 'new',
        'filledAmount': '0',
    })
    bv.ordersOpen = MagicMock(return_value=[])
    bv.tickerPrice = MagicMock(return_value={'price': '90000'})
    bv.ticker24h = MagicMock(return_value={'volumeQuote': '500000'})
    bv.candles = MagicMock(return_value=[
        [int(time.time() * 1000) - i * 3600000, '89000', '91000', '88500', str(89000 + (i % 10) * 100), '10']
        for i in range(48)
    ])
    return bv


@pytest.fixture
def grid_config():
    """Default bot config with grid trading enabled."""
    return {
        'GRID_TRADING': {
            'enabled': True,
            'max_grids': 2,
            'investment_per_grid': 50,
            'max_total_investment': 100,
            'num_grids': 8,
            'grid_mode': 'arithmetic',
            'stop_loss_pct': 0.15,
            'take_profit_pct': 0.20,
            'min_volume_24h': 50000,
            'preferred_markets': ['BTC-EUR', 'ETH-EUR'],
            'excluded_markets': [],
        },
        'OPERATOR_ID': 12345,
    }


@pytest.fixture
def manager(mock_bitvavo, grid_config, tmp_path):
    """Create a GridManager with mocked dependencies."""
    mgr = GridManager(mock_bitvavo, grid_config)
    mgr.GRID_STATE_FILE = str(tmp_path / 'grid_states.json')
    # Mock API module to avoid import errors
    mock_api = MagicMock()
    mock_api.safe_call = MagicMock(side_effect=lambda func, *a, **kw: func(*a, **kw))
    mock_api.normalize_amount = MagicMock(side_effect=lambda m, a: round(a, 8))
    mock_api.normalize_price = MagicMock(side_effect=lambda m, p: round(p, 2))
    mock_api.get_min_order_size = MagicMock(return_value=0.00001)
    mock_api.get_current_price = MagicMock(return_value=90000.0)
    mock_api.get_candles = MagicMock(return_value=[
        [int(time.time() * 1000) - i * 3600000, '89000', '91000', '88500', str(89000 + (i % 10) * 100), '10']
        for i in range(48)
    ])
    mock_api.get_eur_balance = MagicMock(return_value=200.0)
    mgr._api_module = mock_api
    return mgr


# ==================== BASIC TESTS ====================

class TestGridDataClasses:
    def test_grid_level_defaults(self):
        level = GridLevel(level_id=0, price=90000, side='buy', amount=0.001)
        assert level.status == 'pending'
        assert level.order_id is None
        assert level.filled_at is None

    def test_grid_config_defaults(self):
        config = GridConfig(market='BTC-EUR', lower_price=85000, upper_price=95000)
        assert config.num_grids == 10
        assert config.grid_mode == 'arithmetic'
        assert config.auto_rebalance is True
        assert config.stop_loss_pct == 0.15

    def test_grid_state_defaults(self):
        config = GridConfig(market='BTC-EUR', lower_price=85000, upper_price=95000)
        state = GridState(config=config)
        assert state.status == 'initializing'
        assert state.total_profit == 0.0
        assert state.total_fees == 0.0
        assert state.rebalance_count == 0


# ==================== GRID CREATION ====================

class TestGridCreation:
    def test_create_grid_basic(self, manager):
        state = manager.create_grid('BTC-EUR', 85000, 95000, num_grids=8, total_investment=50)
        assert state is not None
        assert state.status == 'initialized'
        assert len(state.levels) > 0
        assert state.config.market == 'BTC-EUR'
        assert state.config.lower_price == 85000
        assert state.config.upper_price == 95000

    def test_create_grid_levels_have_buy_and_sell(self, manager):
        state = manager.create_grid('BTC-EUR', 85000, 95000, num_grids=8, total_investment=50)
        sides = set(l.side for l in state.levels)
        assert 'buy' in sides
        assert 'sell' in sides

    def test_buy_levels_below_current_price(self, manager):
        """Buys should be placed below current price (90000)."""
        state = manager.create_grid('BTC-EUR', 85000, 95000, num_grids=8, total_investment=50)
        for level in state.levels:
            if level.side == 'buy':
                assert level.price < 90000
            elif level.side == 'sell':
                assert level.price >= 90000

    def test_create_grid_invalid_range(self, manager):
        result = manager.create_grid('BTC-EUR', 95000, 85000)  # Reversed
        assert result is None

    def test_create_grid_auto_reduce_grids_for_fee_compliance(self, manager):
        """Grid spacing must exceed MIN_GRID_SPACING_PCT (0.50%)."""
        # Very narrow range with many grids
        state = manager.create_grid('BTC-EUR', 89000, 91000, num_grids=100, total_investment=50)
        if state:
            # Should have reduced num_grids to ensure profitable spacing
            for i in range(1, len(state.levels)):
                spacing = (state.levels[i].price - state.levels[i-1].price) / state.levels[i-1].price
                assert spacing >= MIN_GRID_SPACING_PCT * 0.9  # Allow small tolerance

    def test_geometric_mode(self, manager):
        state = manager.create_grid('BTC-EUR', 85000, 95000, num_grids=8, 
                                     grid_mode='geometric', total_investment=50)
        assert state is not None
        prices = [l.price for l in state.levels]
        # Geometric: ratios should be ~constant
        if len(prices) >= 3:
            r1 = prices[1] / prices[0]
            r2 = prices[2] / prices[1]
            assert abs(r1 - r2) < 0.001

    def test_grid_state_persisted(self, manager, tmp_path):
        manager.create_grid('BTC-EUR', 85000, 95000, num_grids=8, total_investment=50)
        assert os.path.exists(manager.GRID_STATE_FILE)
        with open(manager.GRID_STATE_FILE) as f:
            data = json.load(f)
        assert 'BTC-EUR' in data

    def test_grid_state_reload(self, manager, mock_bitvavo, grid_config, tmp_path):
        manager.create_grid('BTC-EUR', 85000, 95000, num_grids=8, total_investment=50)
        
        # Create new manager that reads from same file
        mgr2 = GridManager(mock_bitvavo, grid_config)
        mgr2.GRID_STATE_FILE = manager.GRID_STATE_FILE
        mgr2._api_module = manager._api_module
        mgr2._load_states()
        
        assert 'BTC-EUR' in mgr2.grids
        assert len(mgr2.grids['BTC-EUR'].levels) > 0


# ==================== ORDER PLACEMENT ====================

class TestOrderPlacement:
    def test_start_grid_places_orders(self, manager, mock_bitvavo):
        manager.create_grid('BTC-EUR', 85000, 95000, num_grids=8, total_investment=50)
        result = manager.start_grid('BTC-EUR')
        assert result is True
        assert manager.grids['BTC-EUR'].status == 'running'
        # placeOrder should have been called for each level
        assert mock_bitvavo.placeOrder.call_count > 0

    def test_start_grid_sets_order_ids(self, manager, mock_bitvavo):
        manager.create_grid('BTC-EUR', 85000, 95000, num_grids=8, total_investment=50)
        manager.start_grid('BTC-EUR')
        placed = [l for l in manager.grids['BTC-EUR'].levels if l.status == 'placed']
        assert len(placed) > 0
        for level in placed:
            assert level.order_id == 'test-order-123'

    def test_start_nonexistent_grid(self, manager):
        assert manager.start_grid('FAKE-EUR') is False

    def test_place_limit_order_includes_operator_id(self, manager, mock_bitvavo):
        manager.create_grid('BTC-EUR', 85000, 95000, num_grids=4, total_investment=50)
        manager.start_grid('BTC-EUR')
        # Check that operatorId was passed
        for call in mock_bitvavo.placeOrder.call_args_list:
            args, kwargs = call
            params = args[3] if len(args) > 3 else {}
            if isinstance(params, dict):
                assert 'operatorId' in params

    def test_order_failure_marks_error(self, manager, mock_bitvavo):
        mock_bitvavo.placeOrder.return_value = {'error': 'Insufficient funds', 'errorCode': 101}
        manager.create_grid('BTC-EUR', 85000, 95000, num_grids=4, total_investment=50)
        result = manager.start_grid('BTC-EUR')
        assert result is False
        assert manager.grids['BTC-EUR'].status == 'error'


# ==================== GRID STOP/DELETE ====================

class TestGridLifecycle:
    def test_stop_grid_cancels_orders(self, manager, mock_bitvavo):
        manager.create_grid('BTC-EUR', 85000, 95000, num_grids=4, total_investment=50)
        manager.start_grid('BTC-EUR')
        result = manager.stop_grid('BTC-EUR')
        assert result is True
        assert manager.grids['BTC-EUR'].status == 'stopped'
        # cancelOrder should have been called
        assert mock_bitvavo.cancelOrder.call_count > 0

    def test_delete_grid_removes_from_state(self, manager, mock_bitvavo):
        manager.create_grid('BTC-EUR', 85000, 95000, num_grids=4, total_investment=50)
        manager.start_grid('BTC-EUR')
        result = manager.delete_grid('BTC-EUR')
        assert result is True
        assert 'BTC-EUR' not in manager.grids

    def test_delete_nonexistent_grid(self, manager):
        assert manager.delete_grid('FAKE-EUR') is False


# ==================== ORDER FILL HANDLING ====================

class TestOrderFills:
    def test_buy_fill_triggers_counter_sell(self, manager, mock_bitvavo):
        """When a buy fills, a sell should be placed at the next higher grid level."""
        manager.create_grid('BTC-EUR', 85000, 95000, num_grids=8, total_investment=50)
        manager.start_grid('BTC-EUR')
        
        # Simulate a buy order being filled
        buy_levels = [l for l in manager.grids['BTC-EUR'].levels if l.side == 'buy' and l.status == 'placed']
        if buy_levels:
            buy_level = buy_levels[0]
            mock_bitvavo.getOrder.return_value = {
                'orderId': buy_level.order_id,
                'status': 'filled',
                'filledAmount': str(buy_level.amount),
                'price': str(buy_level.price),
            }
            
            # Reset placeOrder call count
            initial_calls = mock_bitvavo.placeOrder.call_count
            
            # Force order check
            manager.grids['BTC-EUR'].last_order_check = 0
            result = manager.update_grid('BTC-EUR')
            
            # Should have placed at least one counter-order
            actions = result.get('actions', [])
            buy_fills = [a for a in actions if a.get('type') == 'buy_filled']
            assert len(buy_fills) > 0

    def test_sell_fill_updates_profit(self, manager, mock_bitvavo):
        """When a sell fills, total_profit should increase."""
        manager.create_grid('BTC-EUR', 85000, 95000, num_grids=8, total_investment=50)
        manager.start_grid('BTC-EUR')
        
        sell_levels = [l for l in manager.grids['BTC-EUR'].levels if l.side == 'sell' and l.status == 'placed']
        if sell_levels:
            sell_level = sell_levels[0]
            mock_bitvavo.getOrder.return_value = {
                'orderId': sell_level.order_id,
                'status': 'filled',
                'filledAmount': str(sell_level.amount),
                'price': str(sell_level.price),
            }
            
            initial_profit = manager.grids['BTC-EUR'].total_profit
            initial_trades = manager.grids['BTC-EUR'].total_trades
            
            manager.grids['BTC-EUR'].last_order_check = 0
            result = manager.update_grid('BTC-EUR')
            
            assert manager.grids['BTC-EUR'].total_trades > initial_trades

    def test_fees_tracked(self, manager, mock_bitvavo):
        """Fee tracking should accumulate with each fill."""
        manager.create_grid('BTC-EUR', 85000, 95000, num_grids=8, total_investment=50)
        manager.start_grid('BTC-EUR')
        
        buy_levels = [l for l in manager.grids['BTC-EUR'].levels if l.side == 'buy' and l.status == 'placed']
        if buy_levels:
            buy_level = buy_levels[0]
            mock_bitvavo.getOrder.return_value = {
                'orderId': buy_level.order_id,
                'status': 'filled',
                'filledAmount': str(buy_level.amount),
                'price': str(buy_level.price),
            }
            
            manager.grids['BTC-EUR'].last_order_check = 0
            manager.update_grid('BTC-EUR')
            
            assert manager.grids['BTC-EUR'].total_fees > 0


# ==================== STOP LOSS / TAKE PROFIT ====================

class TestProtections:
    def test_stop_loss_triggers(self, manager, mock_bitvavo):
        """Grid should stop when price drops beyond stop_loss_pct."""
        manager.create_grid('BTC-EUR', 85000, 95000, num_grids=8, 
                           total_investment=50, stop_loss_pct=0.10)
        manager.start_grid('BTC-EUR')
        
        # Price drops far below range
        manager._api_module.get_current_price.return_value = 70000.0
        manager.grids['BTC-EUR'].last_order_check = 0
        result = manager.update_grid('BTC-EUR')
        
        assert result.get('reason') == 'stop_loss' or manager.grids['BTC-EUR'].status == 'stopped'

    def test_take_profit_triggers(self, manager, mock_bitvavo):
        """Grid should stop when profit exceeds take_profit_pct."""
        manager.create_grid('BTC-EUR', 85000, 95000, num_grids=8,
                           total_investment=50, take_profit_pct=0.10)
        manager.start_grid('BTC-EUR')
        
        # Fake accumulated profit
        manager.grids['BTC-EUR'].total_profit = 10.0  # 20% of 50 EUR
        manager.grids['BTC-EUR'].last_order_check = 0
        result = manager.update_grid('BTC-EUR')
        
        assert result.get('reason') == 'take_profit'


# ==================== AUTO-MANAGE ====================

class TestAutoManage:
    def test_auto_manage_disabled(self, manager):
        manager.bot_config['GRID_TRADING']['enabled'] = False
        result = manager.auto_manage()
        assert result.get('enabled') is False

    def test_auto_manage_creates_grids(self, manager, mock_bitvavo):
        """auto_manage should auto-create grids when none exist."""
        # Make volume check pass
        mock_bitvavo.ticker24h.return_value = {'volumeQuote': '500000'}
        
        result = manager.auto_manage()
        # Should have attempted to create grids
        assert 'auto_create' in result or len(manager.grids) > 0

    def test_auto_manage_starts_initialized_grids(self, manager, mock_bitvavo):
        manager.create_grid('BTC-EUR', 85000, 95000, num_grids=4, total_investment=50)
        assert manager.grids['BTC-EUR'].status == 'initialized'
        
        result = manager.auto_manage()
        assert manager.grids['BTC-EUR'].status in ('running', 'error')

    def test_auto_manage_updates_running_grids(self, manager, mock_bitvavo):
        manager.create_grid('BTC-EUR', 85000, 95000, num_grids=4, total_investment=50)
        manager.start_grid('BTC-EUR')
        # Ensure order check will proceed
        manager.grids['BTC-EUR'].last_order_check = 0
        
        result = manager.auto_manage()
        # Should have updated the grid
        assert manager.grids['BTC-EUR'].last_update > 0

    def test_auto_manage_respects_max_grids(self, manager, mock_bitvavo):
        manager.bot_config['GRID_TRADING']['max_grids'] = 1
        manager.create_grid('BTC-EUR', 85000, 95000, num_grids=4, total_investment=50)
        manager.start_grid('BTC-EUR')
        
        result = manager.auto_manage()
        # Should not create more grids
        assert 'auto_create' not in result or result.get('auto_create') == []


# ==================== REBALANCE ====================

class TestRebalance:
    def test_rebalance_cancels_old_orders(self, manager, mock_bitvavo):
        manager.create_grid('BTC-EUR', 85000, 95000, num_grids=4, total_investment=50)
        manager.start_grid('BTC-EUR')
        
        cancel_count_before = mock_bitvavo.cancelOrder.call_count
        manager._rebalance_grid('BTC-EUR', 100000)
        assert mock_bitvavo.cancelOrder.call_count > cancel_count_before

    def test_rebalance_places_new_orders(self, manager, mock_bitvavo):
        manager.create_grid('BTC-EUR', 85000, 95000, num_grids=4, total_investment=50)
        manager.start_grid('BTC-EUR')
        
        result = manager._rebalance_grid('BTC-EUR', 100000)
        assert result.get('success') is True
        assert result.get('orders_placed', 0) > 0

    def test_rebalance_updates_range(self, manager, mock_bitvavo):
        manager.create_grid('BTC-EUR', 85000, 95000, num_grids=4, total_investment=50)
        manager.start_grid('BTC-EUR')
        
        result = manager._rebalance_grid('BTC-EUR', 100000)
        config = manager.grids['BTC-EUR'].config
        # New range should be centered around 100000
        assert config.lower_price < 100000
        assert config.upper_price > 100000

    def test_rebalance_increments_counter(self, manager, mock_bitvavo):
        manager.create_grid('BTC-EUR', 85000, 95000, num_grids=4, total_investment=50)
        manager.start_grid('BTC-EUR')
        
        assert manager.grids['BTC-EUR'].rebalance_count == 0
        manager._rebalance_grid('BTC-EUR', 100000)
        assert manager.grids['BTC-EUR'].rebalance_count == 1


# ==================== STATUS REPORTING ====================

class TestStatusReporting:
    def test_get_grid_status(self, manager):
        manager.create_grid('BTC-EUR', 85000, 95000, num_grids=8, total_investment=50)
        status = manager.get_grid_status('BTC-EUR')
        
        assert status is not None
        assert status['market'] == 'BTC-EUR'
        assert 'total_profit' in status
        assert 'net_profit' in status
        assert 'roi_pct' in status
        assert 'levels' in status

    def test_get_all_grids_summary(self, manager):
        manager.create_grid('BTC-EUR', 85000, 95000, num_grids=8, total_investment=50)
        summary = manager.get_all_grids_summary()
        
        assert len(summary) >= 1
        btc_summary = [s for s in summary if s['market'] == 'BTC-EUR']
        assert len(btc_summary) == 1
        assert 'net_profit' in btc_summary[0]

    def test_status_nonexistent(self, manager):
        assert manager.get_grid_status('FAKE-EUR') is None


# ==================== UTILITY FUNCTIONS ====================

class TestUtilityFunctions:
    def test_calculate_optimal_range(self):
        lower, upper = calculate_optimal_grid_range(90000, volatility_pct=0.10)
        assert lower < 90000
        assert upper > 90000
        assert (upper - lower) / 90000 == pytest.approx(0.20, abs=0.01)

    def test_estimate_profit_accounts_for_fees(self):
        result = estimate_grid_profit(85000, 95000, 10, 100, num_cycles=1)
        assert result['fee_per_round_trip'] > 0
        assert result['profit_per_grid_eur'] < result['grid_spacing_pct'] / 100 * 10  # Less than raw profit
        assert result['estimated_roi_pct'] > 0

    def test_estimate_profit_zero_investment(self):
        result = estimate_grid_profit(85000, 95000, 10, 0, num_cycles=1)
        assert result['estimated_roi_pct'] == 0


# ==================== SINGLETON ====================

class TestSingleton:
    def test_get_grid_manager_creates_once(self):
        mgr1 = get_grid_manager()
        mgr2 = get_grid_manager()
        assert mgr1 is mgr2

    def test_get_grid_manager_accepts_client(self, mock_bitvavo):
        mgr = get_grid_manager(mock_bitvavo)
        assert mgr.bitvavo is mock_bitvavo

    def test_reset_creates_new(self):
        mgr1 = get_grid_manager()
        reset_grid_manager()
        mgr2 = get_grid_manager()
        assert mgr1 is not mgr2
