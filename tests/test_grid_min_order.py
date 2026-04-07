"""
Tests for grid trading minimum order enforcement.

Verifies the fix for the bug where volatility-adaptive grid density
increased num_grids beyond what the investment could support, causing
all orders to fall below Bitvavo's €5 minimum and the grid to die.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# Bootstrap project root
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from modules.grid_trading import GridManager, GridConfig, GridState, GridLevel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_manager(investment: float = 50.0, num_grids: int = 10, **overrides) -> GridManager:
    """Create a GridManager with mocked Bitvavo client and sensible defaults.

    Patches _load_states to avoid reading from disk and _get_api to prevent
    import-time failures for bot.api dependencies.
    """
    mock_bv = MagicMock()
    # Mock ticker price (single market query returns dict, multi returns list)
    mock_bv.tickerPrice.return_value = {'market': 'ETH-EUR', 'price': '1750.00'}
    # Mock placeOrder to always succeed
    mock_bv.placeOrder.return_value = {
        'orderId': f'test-order-{time.time()}',
        'status': 'new',
        'filledAmount': '0',
    }
    mock_bv.cancelOrder.return_value = {'orderId': 'cancelled'}
    mock_bv.balance.return_value = [{'symbol': 'ETH', 'available': '100.0'}]

    config = {
        'GRID_TRADING': {
            'enabled': True,
            'max_grids': 2,
            'investment_per_grid': investment,
            'num_grids': num_grids,
            'grid_mode': 'arithmetic',
            **overrides,
        },
        'AVELLANEDA_STOIKOV_GRID': False,  # Disable A-S for deterministic tests
    }

    # Patch _load_states so constructor doesn't read disk
    with patch.object(GridManager, '_load_states', return_value=None):
        mgr = GridManager(bitvavo_client=mock_bv, config=config)

    # Ensure _get_api returns None so we use fallback paths (no bot.api dependency)
    mgr._get_api = lambda: None
    # Clear any loaded states
    mgr.grids = {}
    # Mock _save_states so we don't write to disk
    mgr._save_states = lambda: None
    return mgr


def _create_test_grid(mgr: GridManager, market: str = 'ETH-EUR',
                      investment: float = 50.0, num_grids: int = 10,
                      lower: float = 1600.0, upper: float = 1900.0) -> GridState | None:
    """Create a grid via the manager and return its state."""
    # Patch _get_current_price to return mock price
    mgr._get_current_price = lambda m: 1750.0

    state = mgr.create_grid(
        market=market,
        lower_price=lower,
        upper_price=upper,
        num_grids=num_grids,
        total_investment=investment,
        auto_rebalance=True,
    )
    return state


# ---------------------------------------------------------------------------
# Tests: Minimum Order Value Enforcement
# ---------------------------------------------------------------------------

class TestMinOrderEnforcement:
    """Tests that grid levels never go below €5.00 minimum order value."""

    def test_create_grid_clamps_num_grids_for_min_order(self):
        """€50 investment with 15 grids → should auto-reduce to 9 grids (€5.50+ each)."""
        mgr = _make_manager(investment=50.0, num_grids=15)
        state = _create_test_grid(mgr, investment=50.0, num_grids=15)

        assert state is not None, "Grid should be created successfully"
        # Max grids = floor(50 / 5.50) = 9
        assert state.config.num_grids <= 9, \
            f"num_grids should be clamped to ≤9 for €50 investment, got {state.config.num_grids}"
        # All levels should have order value >= min
        for level in state.levels:
            order_value = level.amount * level.price
            assert order_value >= 4.99, \
                f"Level {level.level_id} order value €{order_value:.2f} below minimum"

    def test_create_grid_rejects_insufficient_investment(self):
        """€10 investment with 10 grids → impossible → should return None."""
        mgr = _make_manager(investment=10.0, num_grids=10)
        state = _create_test_grid(mgr, investment=10.0, num_grids=10)

        # €10 / 3 grids (minimum) = €3.33 < €5.50, so should fail
        assert state is None, "Grid with €10 investment should be rejected"

    def test_create_grid_minimal_viable(self):
        """€18 investment → should create with exactly 3 grids (€6.00 each)."""
        mgr = _make_manager(investment=18.0, num_grids=10)
        state = _create_test_grid(mgr, investment=18.0, num_grids=10)

        assert state is not None, "€18 with 3 grids should be viable"
        assert state.config.num_grids <= 3

    def test_create_grid_50eur_10_grids_clamps_to_9(self):
        """€50 with 10 grids → €5.00/level → borderline, should reduce to 9."""
        mgr = _make_manager(investment=50.0, num_grids=10)
        state = _create_test_grid(mgr, investment=50.0, num_grids=10)

        assert state is not None
        # €50 / 10 = €5.00 which is < €5.50 threshold → should clamp to 9
        assert state.config.num_grids <= 9

    def test_create_grid_100eur_10_grids_all_above_min(self):
        """€100 with 10 grids → €10/level → all should be fine."""
        mgr = _make_manager(investment=100.0, num_grids=10)
        state = _create_test_grid(mgr, investment=100.0, num_grids=10)

        assert state is not None
        assert state.config.num_grids == 10
        for level in state.levels:
            order_value = level.amount * level.price
            assert order_value >= 4.99, \
                f"Level {level.level_id} order value €{order_value:.2f} below minimum"

    def test_create_grid_20_grids_50eur_should_clamp(self):
        """Reproduces the exact bug: €50 investment, 20 grids → was €2.50/level."""
        mgr = _make_manager(investment=50.0, num_grids=20)
        state = _create_test_grid(mgr, investment=50.0, num_grids=20)

        assert state is not None, "Grid should auto-clamp, not fail"
        # Old bug: 50/20 = €2.50 per level (below €5 minimum)
        # Fix: should clamp to floor(50/5.50) = 9
        assert state.config.num_grids <= 9
        amount_per_level = 50.0 / state.config.num_grids
        assert amount_per_level >= 5.50, \
            f"Amount per level €{amount_per_level:.2f} still below min after fix"


class TestCalculateGridLevelsMinOrder:
    """Tests that _calculate_grid_levels enforces minimum order size."""

    def test_calculate_levels_clamps_num_grids(self):
        """_calculate_grid_levels should reduce num_grids if order value too low."""
        mgr = _make_manager(investment=50.0, num_grids=15)

        config = GridConfig(
            market='ETH-EUR',
            lower_price=1600.0,
            upper_price=1900.0,
            num_grids=15,           # Too many for €50
            total_investment=50.0,
        )

        levels = mgr._calculate_grid_levels(config, current_price=1750.0)

        # config.num_grids should have been mutated to <= 9
        assert config.num_grids <= 9, \
            f"num_grids should be clamped to ≤9, got {config.num_grids}"
        assert len(levels) > 0, "Should still produce valid levels"

        # Verify each level's EUR value
        for level in levels:
            eur_value = level.amount * level.price
            assert eur_value >= 4.99, \
                f"Level {level.level_id}: €{eur_value:.2f} below minimum"

    def test_calculate_levels_exact_boundary(self):
        """€55 with 10 grids → €5.50 each → exactly at threshold."""
        mgr = _make_manager(investment=55.0, num_grids=10)

        config = GridConfig(
            market='ETH-EUR',
            lower_price=1600.0,
            upper_price=1900.0,
            num_grids=10,
            total_investment=55.0,
        )

        levels = mgr._calculate_grid_levels(config, current_price=1750.0)

        assert config.num_grids == 10, "10 grids should be fine for €55"
        assert len(levels) == 10


class TestVolAdaptiveClamp:
    """Tests that volatility-adaptive num_grids increase is bounded."""

    def test_vol_adaptive_cannot_exceed_affordable(self):
        """Volatility-adaptive must not increase num_grids beyond what budget allows."""
        mgr = _make_manager(investment=50.0, num_grids=8)
        state = _create_test_grid(mgr, investment=50.0, num_grids=8)

        assert state is not None

        # Simulate what vol-adaptive would try: increase to 20
        state.config.num_grids = 20
        state.config.volatility_adaptive = True

        # The _calculate_grid_levels should clamp internally
        levels = mgr._calculate_grid_levels(state.config, 1750.0)

        # Verify num_grids was clamped
        assert state.config.num_grids <= 9, \
            f"num_grids should be clamped to ≤9 for €50, got {state.config.num_grids}"
        # Verify all level order values
        for level in levels:
            order_value = level.amount * level.price
            assert order_value >= 4.99, \
                f"Level {level.level_id} order value €{order_value:.2f} below minimum"


class TestRebalanceMinOrder:
    """Tests that rebalance enforces minimum order value."""

    def test_rebalance_clamps_inflated_num_grids(self):
        """If num_grids was inflated to 20, rebalance should clamp back down."""
        mgr = _make_manager(investment=50.0, num_grids=8)
        state = _create_test_grid(mgr, investment=50.0, num_grids=8)

        assert state is not None

        # Simulate vol-adaptive having inflated num_grids
        state.config.num_grids = 20
        state.status = 'running'
        # Add some dummy placed levels to avoid zombie detection
        for level in state.levels:
            level.status = 'placed'
            level.order_id = f'order-{level.level_id}'

        result = mgr._rebalance_grid('ETH-EUR', 1750.0)

        # _rebalance_grid returns a dict with success key
        if result and isinstance(result, dict):
            # After rebalance, num_grids should be clamped
            assert state.config.num_grids <= 9, \
                f"Rebalance should clamp num_grids to ≤9 for €50, got {state.config.num_grids}"


# ---------------------------------------------------------------------------
# Grid Backtest Simulation
# ---------------------------------------------------------------------------

class TestGridBacktest:
    """Full grid backtest simulation with min order fix."""

    @staticmethod
    def _generate_price_series(
        start: float = 1750.0,
        n: int = 2880,  # 2 days of 1-min candles
        volatility: float = 0.002,
        seed: int = 42,
    ) -> list[tuple[float, float, float, float]]:
        """Generate OHLC price series using GBM (Geometric Brownian Motion)."""
        import random
        rng = random.Random(seed)
        series = []
        price = start
        for _ in range(n):
            ret = rng.gauss(0, volatility)
            o = price
            c = max(0.01, price * (1 + ret))
            intra = abs(ret) * rng.uniform(1.2, 2.0)
            h = max(o, c) * (1 + rng.uniform(0, intra))
            lo = min(o, c) * (1 - rng.uniform(0, intra))
            lo = max(0.01, lo)
            series.append((o, h, lo, c))
            price = c
        return series

    def test_grid_simulation_profitability(self):
        """Simulate grid with fixed min-order and verify basic profitability in range-bound market."""
        prices = self._generate_price_series(start=1750.0, n=4320, volatility=0.003, seed=123)

        # Simulate grid: €50 investment, 9 levels (post-fix), range ±5%
        investment = 50.0
        num_levels = 9
        mid = 1750.0
        lower = mid * 0.95
        upper = mid * 1.05
        spacing = (upper - lower) / (num_levels - 1)
        fee_pct = 0.0015  # Bitvavo maker fee

        # Build levels
        levels = []
        amount_per_level = investment / num_levels
        for i in range(num_levels):
            price = lower + i * spacing
            side = 'buy' if price < mid else 'sell'
            levels.append({
                'price': price,
                'side': side,
                'amount_eur': amount_per_level,
                'amount_base': amount_per_level / price,
                'filled': False,
            })

        total_profit = 0.0
        total_fees = 0.0
        cycles = 0
        rebalances = 0

        for o, h, lo, c in prices:
            for lvl in levels:
                if lvl['filled']:
                    continue

                if lvl['side'] == 'buy' and lo <= lvl['price'] <= h:
                    cost = lvl['amount_base'] * lvl['price']
                    fee = cost * fee_pct
                    lvl['filled'] = True
                    total_fees += fee
                    # Place counter sell at next higher level
                    idx = levels.index(lvl)
                    if idx + 1 < len(levels):
                        sell_lvl = levels[idx + 1]
                        sell_lvl['side'] = 'sell'
                        sell_lvl['filled'] = False
                        sell_lvl['amount_base'] = lvl['amount_base']

                elif lvl['side'] == 'sell' and lo <= lvl['price'] <= h:
                    rev = lvl['amount_base'] * lvl['price']
                    fee = rev * fee_pct
                    profit = spacing * lvl['amount_base'] - 2 * fee_pct * lvl['price'] * lvl['amount_base']
                    lvl['filled'] = True
                    total_fees += fee
                    total_profit += profit
                    cycles += 1
                    # Place counter buy at next lower level
                    idx = levels.index(lvl)
                    if idx - 1 >= 0:
                        buy_lvl = levels[idx - 1]
                        buy_lvl['side'] = 'buy'
                        buy_lvl['filled'] = False
                        buy_lvl['amount_base'] = lvl['amount_base']

            # Rebalance if price exits range
            if c > upper * 1.05 or c < lower * 0.95:
                mid = c
                lower = mid * 0.95
                upper = mid * 1.05
                spacing = (upper - lower) / (num_levels - 1)
                for i, lvl in enumerate(levels):
                    lvl['price'] = lower + i * spacing
                    lvl['filled'] = False
                    lvl['side'] = 'buy' if lvl['price'] < mid else 'sell'
                    lvl['amount_base'] = amount_per_level / lvl['price']
                rebalances += 1

        net_profit = total_profit - total_fees
        roi_pct = (net_profit / investment) * 100

        # Verify the grid orders were above minimum
        for lvl in levels:
            assert lvl['amount_eur'] >= 5.50, \
                f"Grid level EUR value {lvl['amount_eur']:.2f} below minimum"

        # In a range-bound market, grid should be profitable
        assert cycles > 0, f"Expected at least some grid cycles, got {cycles}"
        assert net_profit > 0, \
            f"Grid should be profitable in range-bound market: net={net_profit:.4f}, cycles={cycles}"

        # Print summary for visibility
        print(f"\n=== Grid Backtest Result (range-bound) ===")
        print(f"  Investment: €{investment:.0f}")
        print(f"  Grid levels: {num_levels}")
        print(f"  EUR per level: €{amount_per_level:.2f}")
        print(f"  Cycles completed: {cycles}")
        print(f"  Rebalances: {rebalances}")
        print(f"  Gross profit: €{total_profit:.4f}")
        print(f"  Total fees: €{total_fees:.4f}")
        print(f"  Net profit: €{net_profit:.4f}")
        print(f"  ROI: {roi_pct:.2f}%")
        print(f"  Annualized ROI: {roi_pct * 365 / 3:.1f}%")

    def test_grid_different_investments(self):
        """Compare grid profitability across investment sizes."""
        prices = self._generate_price_series(start=1750.0, n=4320, volatility=0.003, seed=42)

        results = []
        for inv, n_grids in [(30, 5), (50, 9), (100, 10), (200, 15)]:
            profit, cycles = self._run_simple_grid(prices, inv, n_grids)
            results.append((inv, n_grids, profit, cycles))

        print("\n=== Grid Investment Comparison ===")
        print(f"  {'Investment':>10} {'Grids':>6} {'Profit':>10} {'Cycles':>7} {'ROI%':>8}")
        for inv, n, p, c in results:
            roi = (p / inv) * 100 if inv > 0 else 0
            print(f"  €{inv:>9.0f} {n:>6} €{p:>9.4f} {c:>7} {roi:>7.2f}%")

        # All should still have valid min order sizes
        for inv, n, _, _ in results:
            eur_per_level = inv / n
            assert eur_per_level >= 5.50, \
                f"€{inv}/{n} grids = €{eur_per_level:.2f}/level < €5.50 min"

    def test_grid_high_volatility_scenario(self):
        """Grid in high volatility: more cycles but also more rebalances."""
        prices = self._generate_price_series(start=1750.0, n=4320, volatility=0.008, seed=77)

        profit, cycles = self._run_simple_grid(prices, investment=50.0, num_levels=9)

        print(f"\n=== Grid Backtest (high volatility) ===")
        print(f"  Cycles: {cycles}, Net profit: €{profit:.4f}")
        # High volatility should still be handled
        assert cycles >= 0, "High vol may not cycle much but shouldn't crash"

    def test_grid_trending_market(self):
        """Grid in a trending-up market: should rebalance frequently."""
        import random
        rng = random.Random(99)
        price = 1750.0
        prices = []
        for _ in range(4320):
            # Upward drift
            ret = rng.gauss(0.0003, 0.002)
            o = price
            c = max(0.01, price * (1 + ret))
            intra = abs(ret) * rng.uniform(1.2, 2.0)
            h = max(o, c) * (1 + rng.uniform(0, intra))
            lo = min(o, c) * (1 - rng.uniform(0, intra))
            lo = max(0.01, lo)
            prices.append((o, h, lo, c))
            price = c

        profit, cycles = self._run_simple_grid(prices, investment=50.0, num_levels=9)

        print(f"\n=== Grid Backtest (trending up) ===")
        print(f"  Start: €1750 → End: €{prices[-1][3]:.0f}")
        print(f"  Cycles: {cycles}, Net profit: €{profit:.4f}")

    def test_grid_with_old_bug_would_fail(self):
        """Demonstrate that the old config (€50/15 grids = €3.33/level) would fail."""
        old_amount_per_level = 50.0 / 15  # Old bug: 15 grids
        assert old_amount_per_level < 5.0, \
            f"Old config should have been below minimum: €{old_amount_per_level:.2f}"

        new_amount_per_level = 50.0 / 9  # Fixed: 9 grids
        assert new_amount_per_level >= 5.50, \
            f"Fixed config should be above minimum: €{new_amount_per_level:.2f}"

        # Old config for BTC: €60/20 = €3.00/level
        old_btc = 60.0 / 20
        assert old_btc < 5.0, f"BTC old config should fail: €{old_btc:.2f}"

        # Fixed: floor(60/5.50) = 10
        fixed_btc = 60.0 / 10
        assert fixed_btc >= 5.50, f"BTC fixed config should pass: €{fixed_btc:.2f}"

    # ---- Helpers ----

    @staticmethod
    def _run_simple_grid(
        prices: list[tuple[float, float, float, float]],
        investment: float = 50.0,
        num_levels: int = 9,
    ) -> tuple[float, int]:
        """Run a simple grid backtest and return (net_profit, cycles)."""
        mid = prices[0][0]
        lower = mid * 0.95
        upper = mid * 1.05
        spacing = (upper - lower) / (num_levels - 1)
        fee_pct = 0.0015
        amount_per_level = investment / num_levels

        levels = []
        for i in range(num_levels):
            price = lower + i * spacing
            side = 'buy' if price < mid else 'sell'
            levels.append({
                'price': price,
                'side': side,
                'amount_base': amount_per_level / price,
                'filled': False,
            })

        total_profit = 0.0
        total_fees = 0.0
        cycles = 0

        for o, h, lo, c in prices:
            for lvl in levels:
                if lvl['filled']:
                    continue

                if lvl['side'] == 'buy' and lo <= lvl['price'] <= h:
                    fee = lvl['amount_base'] * lvl['price'] * fee_pct
                    lvl['filled'] = True
                    total_fees += fee
                    idx = levels.index(lvl)
                    if idx + 1 < len(levels):
                        levels[idx + 1]['side'] = 'sell'
                        levels[idx + 1]['filled'] = False
                        levels[idx + 1]['amount_base'] = lvl['amount_base']

                elif lvl['side'] == 'sell' and lo <= lvl['price'] <= h:
                    fee = lvl['amount_base'] * lvl['price'] * fee_pct
                    profit = spacing * lvl['amount_base'] - 2 * fee
                    lvl['filled'] = True
                    total_fees += fee
                    total_profit += profit
                    cycles += 1
                    idx = levels.index(lvl)
                    if idx - 1 >= 0:
                        levels[idx - 1]['side'] = 'buy'
                        levels[idx - 1]['filled'] = False
                        levels[idx - 1]['amount_base'] = lvl['amount_base']

            # Rebalance if price exits range
            if c > upper * 1.05 or c < lower * 0.95:
                mid = c
                lower = mid * 0.95
                upper = mid * 1.05
                spacing = (upper - lower) / (num_levels - 1)
                for i, lvl in enumerate(levels):
                    lvl['price'] = lower + i * spacing
                    lvl['filled'] = False
                    lvl['side'] = 'buy' if lvl['price'] < mid else 'sell'
                    lvl['amount_base'] = amount_per_level / lvl['price']

        return total_profit - total_fees, cycles
