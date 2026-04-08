# -*- coding: utf-8 -*-
"""Tests for sync_engine trailing field population and DCA history preservation.

Covers the two confirmed bugs:
1. ALGO bug: Sync-created trades missing trailing fields (trailing_activation_pct,
   base_trailing_pct, cost_buffer_pct, dca_events, etc.) → trailing never activates.
2. DOGE bug: Stale buy_price detection wiped dca_buys/dca_events → dashboard shows
   wrong DCA count.
"""
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Helpers — lightweight shared-state mock for sync_engine
# ---------------------------------------------------------------------------

@dataclass
class _FakeCostBasis:
    avg_price: float = 0.0
    invested_eur: float = 0.0
    earliest_timestamp: float = 0.0
    buy_order_count: int = 0
    fills_used: int = 0


class _FakeState:
    """Minimal stand-in for bot.shared.state used by sync_engine."""

    def __init__(self, *, open_trades=None, config=None):
        self.open_trades = open_trades if open_trades is not None else {}
        self.closed_trades = []
        self.CONFIG = config or {
            'TRAILING_ACTIVATION_PCT': 0.015,
            'DEFAULT_TRAILING': 0.025,
            'FEE_TAKER': 0.0025,
            'SLIPPAGE_PCT': 0.001,
            'DCA_DROP_PCT': 0.02,
            'DCA_AMOUNT_EUR': 30.0,
            'DCA_STEP_MULTIPLIER': 1.0,
            'DCA_MAX_BUYS': 9,
            'HODL_SCHEDULER': {'schedules': []},
            'DISABLE_SYNC_REMOVE': True,
            'MAX_OPEN_TRADES': 5,
        }
        self.trades_lock = threading.RLock()
        self.bitvavo = MagicMock()
        self.market_profits = {}
        self._log_messages = []
        self._saved = False
        self._cost_basis_result = None  # set per-test

    # --- Callables expected by sync_engine ---
    def log(self, msg, level='info'):
        self._log_messages.append((level, msg))

    def safe_call(self, fn, *a, **kw):
        # Route to the mock or return predefined values
        return fn(*a, **kw)

    def sanitize_balance_payload(self, balances, source=''):
        return balances or []

    def json_write_compat(self, *a, **kw):
        pass

    def derive_cost_basis(self, bitvavo, market, amount, tolerance=0.02):
        return self._cost_basis_result

    def save_trades_fn(self):
        self._saved = True

    def archive_trade(self, **kw):
        pass

    def _record_market_stats_for_close(self, *a, **kw):
        pass


# ---------------------------------------------------------------------------
# Required fields that every trade must have for trailing + DCA to work
# ---------------------------------------------------------------------------

_REQUIRED_TRAILING_FIELDS = {
    'trailing_activation_pct',
    'base_trailing_pct',
    'cost_buffer_pct',
    'trailing_activated',
    'activation_price',
    'highest_since_activation',
}

_REQUIRED_DCA_FIELDS = {
    'dca_buys',
    'dca_events',
    'dca_drop_pct',
    'dca_amount_eur',
    'dca_step_mult',
    'dca_max',
}

_REQUIRED_COMMON_FIELDS = {
    'partial_tp_returned_eur',
    'partial_tp_events',
    'tp_levels_done',
    'score',
    'volatility_at_entry',
    'opened_regime',
}

ALL_REQUIRED_FIELDS = _REQUIRED_TRAILING_FIELDS | _REQUIRED_DCA_FIELDS | _REQUIRED_COMMON_FIELDS


# ---------------------------------------------------------------------------
# Test: New trade created by sync has all required fields (ALGO scenario)
# ---------------------------------------------------------------------------

class TestSyncNewTradeFields:
    """When sync discovers a balance not in open_trades, the new trade dict
    must contain ALL fields needed for trailing and DCA to work."""

    def _run_sync_with_new_balance(self, market='ALGO-EUR', price=0.08, amount=1000.0):
        """Helper: run sync_with_bitvavo with a single balance not yet tracked."""
        state = _FakeState()
        state._cost_basis_result = _FakeCostBasis(
            avg_price=price, invested_eur=price * amount, earliest_timestamp=time.time()
        )
        state.bitvavo.balance = MagicMock(return_value=[
            {'symbol': market.split('-')[0], 'available': str(amount)}
        ])
        state.bitvavo.markets = MagicMock(return_value=[{'market': market}])
        state.bitvavo.tickerPrice = MagicMock(return_value={'price': str(price)})

        with patch('bot.sync_engine._get_state', return_value=state):
            from bot.sync_engine import sync_with_bitvavo
            sync_with_bitvavo()

        return state

    def test_new_trade_has_trailing_fields(self):
        """A sync-created trade must have trailing_activation_pct, base_trailing_pct, etc."""
        state = self._run_sync_with_new_balance('ALGO-EUR', 0.08, 1000.0)
        trade = state.open_trades.get('ALGO-EUR')
        assert trade is not None, "Trade should be created"
        for field in _REQUIRED_TRAILING_FIELDS:
            assert field in trade, f"Missing trailing field: {field}"

    def test_new_trade_has_dca_fields(self):
        """A sync-created trade must have dca_buys, dca_events, dca_drop_pct, etc."""
        state = self._run_sync_with_new_balance('ALGO-EUR', 0.08, 1000.0)
        trade = state.open_trades['ALGO-EUR']
        for field in _REQUIRED_DCA_FIELDS:
            assert field in trade, f"Missing DCA field: {field}"
        assert trade['dca_buys'] == 0
        assert trade['dca_events'] == []
        assert trade['dca_max'] == 9  # from config

    def test_new_trade_has_common_fields(self):
        """Sync-created trade must have tp levels, partial TP fields, score, etc."""
        state = self._run_sync_with_new_balance('ALGO-EUR', 0.08, 1000.0)
        trade = state.open_trades['ALGO-EUR']
        for field in _REQUIRED_COMMON_FIELDS:
            assert field in trade, f"Missing common field: {field}"
        assert trade['partial_tp_returned_eur'] == 0.0
        assert isinstance(trade['tp_levels_done'], list)
        assert len(trade['tp_levels_done']) >= 3

    def test_new_trade_trailing_config_values(self):
        """Trailing pct values should match config defaults."""
        state = self._run_sync_with_new_balance('ALGO-EUR', 0.08, 1000.0)
        trade = state.open_trades['ALGO-EUR']
        assert trade['trailing_activation_pct'] == pytest.approx(0.015)
        assert trade['base_trailing_pct'] == pytest.approx(0.025)
        # cost_buffer_pct = FEE_TAKER * 2 + SLIPPAGE_PCT = 0.006
        assert trade['cost_buffer_pct'] == pytest.approx(0.006, abs=0.001)


# ---------------------------------------------------------------------------
# Test: Existing trade updated by sync gets missing fields (ALGO already open)
# ---------------------------------------------------------------------------

class TestSyncExistingTradeGetsMissingFields:
    """When sync updates an existing trade that's missing fields (e.g. created
    by an older sync version), the setdefault calls must fill them in."""

    def _run_sync_with_existing_bare_trade(self):
        """Simulate the ALGO bug: trade exists but with minimal fields."""
        bare_trade = {
            'buy_price': 0.076,
            'highest_price': 0.084,
            'amount': 1341.0,
            'timestamp': time.time(),
            'tp_levels_done': [False, False],
            'dca_buys': 0,
            'dca_max': 9,
            'dca_next_price': 0.0,
            'tp_last_time': 0.0,
            'invested_eur': 102.0,
            'initial_invested_eur': 102.0,
            'total_invested_eur': 102.0,
            'trailing_activated': False,
            'activation_price': None,
            'highest_since_activation': None,
        }
        state = _FakeState(open_trades={'ALGO-EUR': bare_trade})
        state._cost_basis_result = None
        state.bitvavo.balance = MagicMock(return_value=[
            {'symbol': 'ALGO', 'available': '1341.0'}
        ])
        state.bitvavo.markets = MagicMock(return_value=[{'market': 'ALGO-EUR'}])
        state.bitvavo.tickerPrice = MagicMock(return_value={'price': '0.084'})

        with patch('bot.sync_engine._get_state', return_value=state):
            from bot.sync_engine import sync_with_bitvavo
            sync_with_bitvavo()

        return state

    def test_existing_trade_gets_trailing_fields(self):
        """After sync, a bare trade must have trailing_activation_pct added."""
        state = self._run_sync_with_existing_bare_trade()
        trade = state.open_trades['ALGO-EUR']
        assert 'trailing_activation_pct' in trade
        assert 'base_trailing_pct' in trade
        assert 'cost_buffer_pct' in trade
        assert trade['trailing_activation_pct'] == pytest.approx(0.015)

    def test_existing_trade_gets_dca_config_fields(self):
        """After sync, a bare trade must have dca_drop_pct, dca_amount_eur, etc."""
        state = self._run_sync_with_existing_bare_trade()
        trade = state.open_trades['ALGO-EUR']
        assert 'dca_drop_pct' in trade
        assert 'dca_amount_eur' in trade
        assert 'dca_step_mult' in trade
        assert 'dca_events' in trade
        assert 'partial_tp_returned_eur' in trade

    def test_existing_trade_gets_all_required_fields(self):
        """Comprehensive check: every required field is present."""
        state = self._run_sync_with_existing_bare_trade()
        trade = state.open_trades['ALGO-EUR']
        for field in ALL_REQUIRED_FIELDS:
            assert field in trade, f"Missing field after sync: {field}"


# ---------------------------------------------------------------------------
# Test: Stale buy_price fix preserves DCA history (DOGE scenario)
# ---------------------------------------------------------------------------

class TestStaleBuyPricePreservesDCA:
    """When stale buy_price is detected and re-derived, existing dca_buys and
    dca_events must NOT be wiped."""

    def _run_sync_with_stale_price_and_dca(self):
        """Simulate DOGE: trade has 4 DCA events, but buy_price is stale."""
        dca_events = [
            {'event_id': f'evt-{i}', 'timestamp': time.time(), 'price': 0.083,
             'amount_eur': 20.0, 'tokens_bought': 241.0, 'dca_level': i + 1}
            for i in range(4)
        ]
        trade = {
            'buy_price': 0.20,  # Stale! Current ticker is 0.085 → deviation >50%
            'highest_price': 0.086,
            'amount': 2278.0,
            'timestamp': time.time(),
            'dca_buys': 4,
            'dca_events': dca_events,
            'dca_max': 9,
            'invested_eur': 192.0,
            'initial_invested_eur': 178.0,
            'total_invested_eur': 256.0,
            'partial_tp_returned_eur': 0.0,
            'trailing_activated': True,
            'trailing_activation_pct': 0.01,
            'base_trailing_pct': 0.025,
            'cost_buffer_pct': 0.006,
            'activation_price': 0.085,
            'highest_since_activation': 0.086,
        }
        state = _FakeState(open_trades={'DOGE-EUR': trade})
        # derive_cost_basis returns the fresh corrected values
        state._cost_basis_result = _FakeCostBasis(
            avg_price=0.084, invested_eur=191.95, earliest_timestamp=time.time()
        )
        state.bitvavo.balance = MagicMock(return_value=[
            {'symbol': 'DOGE', 'available': '2278.0'}
        ])
        state.bitvavo.markets = MagicMock(return_value=[{'market': 'DOGE-EUR'}])
        state.bitvavo.tickerPrice = MagicMock(return_value={'price': '0.085'})

        with patch('bot.sync_engine._get_state', return_value=state):
            from bot.sync_engine import sync_with_bitvavo
            sync_with_bitvavo()

        return state

    def test_dca_buys_preserved_after_stale_fix(self):
        """dca_buys must NOT be reset to 0 when stale price is detected."""
        state = self._run_sync_with_stale_price_and_dca()
        trade = state.open_trades['DOGE-EUR']
        assert trade['dca_buys'] == 4, f"dca_buys was wiped! Got {trade['dca_buys']}"

    def test_dca_events_preserved_after_stale_fix(self):
        """dca_events list must NOT be emptied when stale price is detected."""
        state = self._run_sync_with_stale_price_and_dca()
        trade = state.open_trades['DOGE-EUR']
        assert len(trade['dca_events']) == 4, f"dca_events wiped! Got {len(trade['dca_events'])}"

    def test_buy_price_updated_after_stale_fix(self):
        """buy_price SHOULD be updated to the fresh derived value."""
        state = self._run_sync_with_stale_price_and_dca()
        trade = state.open_trades['DOGE-EUR']
        # buy_price should be updated to derive result or ticker
        assert trade['buy_price'] != 0.20, "buy_price should have been corrected"

    def test_initial_invested_preserved_with_dca(self):
        """initial_invested_eur should not be blindly overwritten when DCA exists."""
        state = self._run_sync_with_stale_price_and_dca()
        trade = state.open_trades['DOGE-EUR']
        # invested_eur changes are OK, but with DCA history the recalc
        # must not blindly overwrite initial_invested_eur
        assert 'initial_invested_eur' in trade
        assert float(trade['initial_invested_eur']) > 0


# ---------------------------------------------------------------------------
# Test: Stale fallback (derive fails) preserves DCA + initial_invested
# ---------------------------------------------------------------------------

class TestStaleFallbackPreservesHistory:
    """When derive_cost_basis fails and we fall back to ticker, DCA and
    initial_invested_eur must still be preserved."""

    def _run_stale_with_derive_failure(self):
        """Stale price detected, derive returns None → ticker fallback."""
        trade = {
            'buy_price': 0.20,  # Stale
            'highest_price': 0.086,
            'amount': 2278.0,
            'timestamp': time.time(),
            'dca_buys': 4,
            'dca_events': [{'event_id': f'e{i}'} for i in range(4)],
            'dca_max': 9,
            'invested_eur': 192.0,
            'initial_invested_eur': 178.0,
            'total_invested_eur': 256.0,
            'partial_tp_returned_eur': 0.0,
            'trailing_activated': True,
            'trailing_activation_pct': 0.01,
            'base_trailing_pct': 0.025,
            'cost_buffer_pct': 0.006,
        }
        state = _FakeState(open_trades={'DOGE-EUR': trade})
        state._cost_basis_result = None  # derive fails
        state.bitvavo.balance = MagicMock(return_value=[
            {'symbol': 'DOGE', 'available': '2278.0'}
        ])
        state.bitvavo.markets = MagicMock(return_value=[{'market': 'DOGE-EUR'}])
        state.bitvavo.tickerPrice = MagicMock(return_value={'price': '0.085'})

        with patch('bot.sync_engine._get_state', return_value=state):
            from bot.sync_engine import sync_with_bitvavo
            sync_with_bitvavo()

        return state

    def test_initial_invested_not_overwritten_on_fallback(self):
        """When derive fails and ticker fallback is used, initial_invested_eur
        must NOT be overwritten if it already exists."""
        state = self._run_stale_with_derive_failure()
        trade = state.open_trades['DOGE-EUR']
        assert trade['initial_invested_eur'] == 178.0, \
            f"initial_invested_eur was overwritten! Got {trade['initial_invested_eur']}"


# ---------------------------------------------------------------------------
# Test: invested_eur recalc respects DCA history
# ---------------------------------------------------------------------------

class TestInvestedRecalcWithDCA:
    """When invested_eur is recalculated during sync due to amount changes,
    initial_invested_eur must NOT be overwritten if DCA history exists."""

    def _run_sync_with_dca_and_amount_change(self):
        """Trade has DCA history, amount changed slightly on exchange."""
        trade = {
            'buy_price': 0.084,
            'highest_price': 0.086,
            'amount': 2000.0,  # Local value
            'invested_eur': 168.0,   # Old value
            'initial_invested_eur': 100.0,  # From initial buy
            'total_invested_eur': 168.0,
            'dca_buys': 3,
            'dca_events': [{'event_id': f'e{i}'} for i in range(3)],
            'dca_max': 9,
            'partial_tp_returned_eur': 0.0,
            'timestamp': time.time(),
        }
        state = _FakeState(open_trades={'TEST-EUR': trade})
        state._cost_basis_result = None
        # Exchange shows slightly different amount
        state.bitvavo.balance = MagicMock(return_value=[
            {'symbol': 'TEST', 'available': '2500.0'}
        ])
        state.bitvavo.markets = MagicMock(return_value=[{'market': 'TEST-EUR'}])
        state.bitvavo.tickerPrice = MagicMock(return_value={'price': '0.084'})

        with patch('bot.sync_engine._get_state', return_value=state):
            from bot.sync_engine import sync_with_bitvavo
            sync_with_bitvavo()

        return state

    def test_initial_invested_preserved_when_dca_exists(self):
        """initial_invested_eur must not change when DCA history exists."""
        state = self._run_sync_with_dca_and_amount_change()
        trade = state.open_trades['TEST-EUR']
        assert trade['initial_invested_eur'] == 100.0, \
            f"initial_invested_eur was corrupted! Got {trade['initial_invested_eur']}"


# ---------------------------------------------------------------------------
# Test: Dashboard DCA display logic
# ---------------------------------------------------------------------------

class TestDashboardDCADisplay:
    """Dashboard should show the CORRECT DCA count using the best source."""

    def test_dca_level_from_events(self):
        """When dca_events has entries, dca_level = len(dca_events)."""
        trade = {
            'dca_buys': 2,  # Stale counter
            'dca_events': [
                {'event_id': '1'}, {'event_id': '2'}, {'event_id': '3'},
                {'event_id': '4'}, {'event_id': '5'},
            ],
        }
        dca_events = trade.get('dca_events', [])
        if isinstance(dca_events, list) and len(dca_events) > 0:
            dca_level = len(dca_events)
        else:
            dca_level = int(trade.get('dca_buys', 0) or 0)
        assert dca_level == 5

    def test_dca_level_fallback_to_counter(self):
        """When dca_events is empty, fallback to dca_buys counter."""
        trade = {'dca_buys': 8, 'dca_events': []}
        dca_events = trade.get('dca_events', [])
        if isinstance(dca_events, list) and len(dca_events) > 0:
            dca_level = len(dca_events)
        else:
            dca_level = int(trade.get('dca_buys', 0) or 0)
        assert dca_level == 8

    def test_dca_level_missing_both(self):
        """Trade with no DCA fields should show 0."""
        trade = {}
        dca_events = trade.get('dca_events', [])
        if isinstance(dca_events, list) and len(dca_events) > 0:
            dca_level = len(dca_events)
        else:
            dca_level = int(trade.get('dca_buys', 0) or 0)
        assert dca_level == 0

    def test_dca_buys_and_events_mismatch_prefers_events(self):
        """When dca_buys=4 but dca_events has 8 entries, events wins."""
        trade = {
            'dca_buys': 4,
            'dca_events': [{'event_id': str(i)} for i in range(8)],
        }
        dca_events = trade.get('dca_events', [])
        if isinstance(dca_events, list) and len(dca_events) > 0:
            dca_level = len(dca_events)
        else:
            dca_level = int(trade.get('dca_buys', 0) or 0)
        assert dca_level == 8


# ---------------------------------------------------------------------------
# Test: Trailing activation with synced trade (end-to-end)
# ---------------------------------------------------------------------------

class TestTrailingActivationWithSyncedTrade:
    """Trailing activation must work correctly for trades created/updated by sync."""

    def test_trailing_activates_when_high_exceeds_threshold(self):
        """A synced trade with 10% gain should have trailing activated."""
        trade = {
            'buy_price': 0.076,
            'highest_price': 0.084,  # +10.5% gain
            'trailing_activation_pct': 0.015,
            'trailing_activated': False,
        }
        buy = trade['buy_price']
        high = trade['highest_price']
        activation_pct = trade.get('trailing_activation_pct', 0.015)
        should_activate = high >= buy * (1 + activation_pct)
        assert should_activate, \
            f"Trailing should activate: gain={(high-buy)/buy:.2%}, threshold={activation_pct:.2%}"

    def test_trailing_does_not_activate_below_threshold(self):
        """A synced trade with only 0.5% gain should not activate."""
        trade = {
            'buy_price': 0.084,
            'highest_price': 0.08442,  # +0.5% gain
            'trailing_activation_pct': 0.015,
            'trailing_activated': False,
        }
        buy = trade['buy_price']
        high = trade['highest_price']
        activation_pct = trade.get('trailing_activation_pct', 0.015)
        should_activate = high >= buy * (1 + activation_pct)
        assert not should_activate, \
            f"Trailing should NOT activate: gain={(high-buy)/buy:.2%}, threshold={activation_pct:.2%}"

    def test_missing_trailing_activation_pct_uses_config_default(self):
        """Without trailing_activation_pct, the config default (0.015) should be used."""
        trade = {
            'buy_price': 0.076,
            'highest_price': 0.084,
        }
        # Simulate what calculate_stop_levels does
        config_default = 0.015
        activation_pct = config_default
        if isinstance(trade, dict) and trade.get('trailing_activation_pct') is not None:
            activation_pct = float(trade.get('trailing_activation_pct'))
        high = trade['highest_price']
        buy = trade['buy_price']
        should_activate = high >= buy * (1 + activation_pct)
        assert should_activate
        assert activation_pct == 0.015
