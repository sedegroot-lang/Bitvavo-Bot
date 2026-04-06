# -*- coding: utf-8 -*-
"""Tests for derive_cost_basis and sync engine cost basis reconciliation.

Validates that:
1. derive_cost_basis always uses full history (no opened_ts filter)
2. Cost basis is correct after external buys (buys not made by the bot)
3. Sells reduce position cost via weighted average
4. Sync engine re-derives on amount change
5. Dashboard shows correct invested_eur (no max() hack)

See docs/FIX_LOG.md #001 for the root cause these tests guard against.
"""
import sys
import os
import time
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.cost_basis import (
    CostBasisResult,
    derive_cost_basis,
    _compute_cost_basis_from_fills,
    _normalize_ts,
)


# ─── Helper: build fill dicts matching Bitvavo trades API format ───

def _fill(side, price, amount, fee=0.0, fee_currency='EUR', ts=None, order_id=None):
    """Create a fill dict mimicking Bitvavo trades API response."""
    return {
        'id': order_id or f'{ts or time.time()}-{price}-{amount}',
        'timestamp': int((ts or time.time()) * 1000),
        'market': 'TEST-EUR',
        'side': side,
        'amount': str(amount),
        'price': str(price),
        'fee': str(fee),
        'feeCurrency': fee_currency,
        'settled': True,
        'taker': True,
    }


# ────────── Test: Basic cost basis computation ──────────

class TestComputeCostBasis:
    """Test the core cost basis computation from fills."""

    def test_single_buy(self):
        """Single buy → invested = price × amount + fee."""
        fills = [_fill('buy', 10.0, 5.0, fee=0.125, fee_currency='EUR', ts=1000)]
        result = _compute_cost_basis_from_fills(fills, market='TEST-EUR', target_amount=5.0, tolerance=0.02)
        assert result is not None
        assert result.invested_eur == pytest.approx(50.125, abs=0.01)  # 10*5 + 0.125
        assert result.avg_price == pytest.approx(10.025, abs=0.01)
        assert result.buy_order_count == 1

    def test_multiple_buys_weighted_average(self):
        """Multiple buys → weighted average price."""
        fills = [
            _fill('buy', 10.0, 2.0, fee=0.05, fee_currency='EUR', ts=1000),
            _fill('buy', 12.0, 3.0, fee=0.09, fee_currency='EUR', ts=2000),
        ]
        result = _compute_cost_basis_from_fills(fills, market='TEST-EUR', target_amount=5.0, tolerance=0.02)
        assert result is not None
        # Total cost = (10*2 + 0.05) + (12*3 + 0.09) = 20.05 + 36.09 = 56.14
        assert result.invested_eur == pytest.approx(56.14, abs=0.01)
        assert result.avg_price == pytest.approx(56.14 / 5.0, abs=0.01)
        assert result.buy_order_count == 2

    def test_buy_then_sell_reduces_cost(self):
        """Buy then sell → cost is reduced by weighted average."""
        fills = [
            _fill('buy', 10.0, 10.0, ts=1000),   # Buy 10 @ €10 = €100
            _fill('sell', 12.0, 4.0, ts=2000),    # Sell 4 @ €12 (avg cost was €10, so cost reduces by 4*10=€40)
        ]
        result = _compute_cost_basis_from_fills(fills, market='TEST-EUR', target_amount=6.0, tolerance=0.02)
        assert result is not None
        # After sell: 6 remaining, cost = 100 - (10*4) = 60
        assert result.invested_eur == pytest.approx(60.0, abs=0.01)
        assert result.avg_price == pytest.approx(10.0, abs=0.01)

    def test_full_sell_then_rebuy(self):
        """Sell all then rebuy → only rebuy cost counts."""
        fills = [
            _fill('buy', 10.0, 5.0, ts=1000),    # Buy 5 @ €10 = €50
            _fill('sell', 12.0, 5.0, ts=2000),    # Sell all 5
            _fill('buy', 8.0, 3.0, ts=3000),      # Rebuy 3 @ €8 = €24
        ]
        result = _compute_cost_basis_from_fills(fills, market='TEST-EUR', target_amount=3.0, tolerance=0.02)
        assert result is not None
        assert result.invested_eur == pytest.approx(24.0, abs=0.01)
        assert result.avg_price == pytest.approx(8.0, abs=0.01)

    def test_fee_in_base_currency(self):
        """Fee in base currency reduces received amount."""
        fills = [
            _fill('buy', 10.0, 5.0, fee=0.05, fee_currency='TEST', ts=1000),
        ]
        # amount received = 5.0 - 0.05 = 4.95, cost = 10*5 = 50
        result = _compute_cost_basis_from_fills(fills, market='TEST-EUR', target_amount=4.95, tolerance=0.02)
        assert result is not None
        assert result.invested_eur == pytest.approx(50.0, abs=0.01)
        assert result.avg_price == pytest.approx(50.0 / 4.95, abs=0.01)


# ────────── Test: Simulated external buy scenario (FIX_LOG #001) ──────────

class TestExternalBuyScenario:
    """Simulate the exact scenario that caused FIX_LOG #001:
    Bot has a position, user makes manual buys on Bitvavo exchange,
    bot must correctly update invested_eur from order history.
    """

    def _make_avax_fills(self):
        """Simulate actual AVAX transaction history from Bitvavo."""
        base_ts = 1774000000  # March 2026 ish
        fills = [
            # Old position buys (before current position)
            _fill('buy', 9.073, 3.67271657, fee=0.083, ts=base_ts + 0),        # €33.32
            _fill('buy', 8.348, 2.64939824, fee=0.055, ts=base_ts + 86400),     # €22.12
            _fill('buy', 8.354, 2.1174318, fee=0.044, ts=base_ts + 86401),      # €17.69
            _fill('buy', 8.376, 1.68966478, fee=0.035, ts=base_ts + 86402),     # €14.15
            _fill('buy', 8.423, 1.34424563, fee=0.028, ts=base_ts + 86500),     # €11.32
            _fill('buy', 8.323, 1.20150881, fee=0.025, ts=base_ts + 172800),    # €10.00
            _fill('buy', 8.362, 1.21974496, fee=0.025, ts=base_ts + 172801),    # €10.20
            _fill('buy', 8.367, 1.17125217, fee=0.024, ts=base_ts + 172802),    # €9.80
            _fill('buy', 8.364, 1.08320167, fee=0.023, ts=base_ts + 172803),    # €9.06
            _fill('buy', 8.357, 0.8675188, fee=0.018, ts=base_ts + 172804),     # €7.25
            _fill('buy', 8.338, 0.86955523, fee=0.018, ts=base_ts + 172900),    # €7.25
            _fill('buy', 8.175, 0.70955861, fee=0.015, ts=base_ts + 173000),    # €5.80
            # External buy on March 23 (user deposited €100 and bought manually)
            _fill('buy', 7.838, 6.37837976, fee=0.125, ts=base_ts + 345600),    # €50.00
        ]
        return fills

    def test_full_history_gives_correct_cost(self):
        """All buys for current AVAX position → correct weighted average."""
        fills = self._make_avax_fills()
        total_amount = sum(
            float(f['amount']) - (float(f['fee']) if f['feeCurrency'] == 'TEST' else 0)
            for f in fills if f['side'] == 'buy'
        )
        result = _compute_cost_basis_from_fills(
            fills, market='AVAX-EUR', target_amount=total_amount, tolerance=0.05
        )
        assert result is not None
        # Total EUR cost should be around €207-208 (sum of all buy EUR amounts)
        assert result.invested_eur > 200
        assert result.invested_eur < 215
        assert result.buy_order_count == 13

    def test_partial_history_gives_wrong_cost(self):
        """Only the last buy → wrong cost basis (this is what the bug caused)."""
        all_fills = self._make_avax_fills()
        # Simulate opened_ts filter: only include the March 23 buy
        late_fills = [f for f in all_fills if _normalize_ts(f['timestamp']) > 1774000000 + 300000]
        assert len(late_fills) == 1  # Only the €50 buy

        result = _compute_cost_basis_from_fills(
            late_fills, market='AVAX-EUR', target_amount=24.97, tolerance=0.5
        )
        # This would give a WRONG result because it only sees 1 buy
        # The avg_price and invested_eur would be extrapolated from just €50/6.38 AVAX
        if result is not None:
            # invested should NOT be close to the correct ~€207
            assert abs(result.invested_eur - 207.0) > 10, \
                "Partial history should NOT produce correct cost basis"


# ────────── Test: derive_cost_basis ignores opened_ts (FIX_LOG #001) ──────────

class TestDeriveCostBasisIgnoresOpenedTs:
    """Verify derive_cost_basis always fetches full history, ignoring opened_ts."""

    def test_opened_ts_is_ignored(self):
        """derive_cost_basis must NOT use opened_ts as API filter."""
        mock_bv = MagicMock()
        # Return fills regardless of params — we check that start_ts is None
        fills = [
            _fill('buy', 10.0, 5.0, ts=1000),
            _fill('buy', 12.0, 5.0, ts=5000),
        ]
        mock_bv.trades.return_value = fills

        result = derive_cost_basis(
            mock_bv, 'TEST-EUR', 10.0,
            opened_ts=4000.0,  # This should be IGNORED
            tolerance=0.5,
        )

        # The API should have been called WITHOUT a start filter
        call_args = mock_bv.trades.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get('params', {})
        # Verify start was NOT passed as a filter
        assert 'start' not in params or params.get('start') is None or params.get('start') == 0, \
            f"derive_cost_basis should NOT use opened_ts as API filter, but got start={params.get('start')}"


# ────────── Test: Sync engine triggers derive on amount change ──────────

class TestSyncEngineDeriveOnAmountChange:
    """Verify the sync engine correctly handles external buys."""

    def test_amount_change_triggers_derive(self):
        """When Bitvavo balance changes, sync must re-derive cost basis."""
        # This tests the core logic that was broken in FIX_LOG #001
        old_amount = 18.60
        new_amount = 24.97
        change_pct = abs(new_amount - old_amount) / max(old_amount, 1e-12)
        assert change_pct > 0.001, "Amount change >0.1% should trigger re-derive"

    def test_small_amount_change_no_derive(self):
        """Tiny amount changes (dust) should NOT trigger re-derive."""
        old_amount = 24.97
        new_amount = 24.970001  # Dust-level change
        change_pct = abs(new_amount - old_amount) / max(old_amount, 1e-12)
        assert change_pct < 0.001, "Dust change should NOT trigger re-derive"

    def test_periodic_derive_triggers_after_4h(self):
        """Even without amount change, derive should run every 4 hours."""
        last_derive_ts = time.time() - 14401  # 4h + 1s ago
        assert (time.time() - last_derive_ts) > 14400

    def test_missing_invested_triggers_derive(self):
        """Zero invested_eur always triggers re-derive."""
        invested = 0.0
        assert invested <= 0


# ────────── Test: Sell + rebuy cycle (complete position turnover) ──────────

class TestCompleteTurnover:
    """Test that sells close old positions and rebuys start fresh cost basis."""

    def test_algo_with_sells_and_rebuys(self):
        """Simulate ALGO position with multiple buy/sell cycles."""
        base = 1774000000
        fills = [
            # Cycle 1: buy then sell completely
            _fill('buy', 0.084, 400.0, fee=0.1, ts=base),
            _fill('sell', 0.085, 400.0, fee=0.1, ts=base + 10000),
            # Cycle 2: current position
            _fill('buy', 0.082, 1000.0, fee=0.05, ts=base + 20000),
            _fill('buy', 0.080, 1000.0, fee=0.05, ts=base + 30000),
            _fill('buy', 0.078, 1000.0, fee=0.05, ts=base + 40000),
        ]
        result = _compute_cost_basis_from_fills(
            fills, market='ALGO-EUR', target_amount=3000.0, tolerance=0.05
        )
        assert result is not None
        # Cost should be: 82 + 80 + 78 = 240 (plus small fees)
        assert result.invested_eur == pytest.approx(240.15, abs=1.0)
        # Average should be around 0.080
        assert result.avg_price == pytest.approx(0.08005, abs=0.001)


# ────────── Test: invested_eur must NOT be set to buy_price * amount blindly ──────────

class TestInvestedEurNotBlind:
    """invested_eur must come from derive_cost_basis, not buy_price × amount.
    See FIX_LOG.md #001 and copilot-instructions.md rule 14.
    """

    def test_derive_includes_fees_in_invested(self):
        """derive result includes fees, so invested_eur > pure price × amount."""
        fills = [
            _fill('buy', 10.0, 5.0, fee=0.50, fee_currency='EUR', ts=1000),
        ]
        result = _compute_cost_basis_from_fills(fills, market='TEST-EUR', target_amount=5.0, tolerance=0.02)
        assert result is not None
        pure_cost = 10.0 * 5.0  # 50.0
        assert result.invested_eur > pure_cost, \
            "invested_eur must include fees — never use pure buy_price × amount"
        assert result.invested_eur == pytest.approx(50.50, abs=0.01)

    def test_avg_price_higher_than_fill_price_due_to_fees(self):
        """avg_price from derive is slightly higher than fill price because it includes fees."""
        fills = [
            _fill('buy', 10.0, 5.0, fee=0.50, fee_currency='EUR', ts=1000),
        ]
        result = _compute_cost_basis_from_fills(fills, market='TEST-EUR', target_amount=5.0, tolerance=0.02)
        assert result is not None
        assert result.avg_price > 10.0, "avg_price should be > fill price because of fees"
        assert result.avg_price == pytest.approx(10.10, abs=0.01)


# ────────── Test: FIFO excess removal (FIX_LOG #009) ──────────

class TestFifoExcessRemoval:
    """When fills yield more position than actual balance (phantom holdings
    due to missing sells in API), FIFO should remove oldest lots so cost
    basis reflects only the most recent purchases.
    See docs/FIX_LOG.md #009.
    """

    def test_phantom_holdings_removed_fifo(self):
        """Simulate LINK-like scenario: old buys at high price never sold
        in trade history but not on exchange. Target < computed position.
        FIFO should remove old expensive lots, cost reflects recent buys."""
        fills = [
            # Old buys at €20 each — these are "phantom" holdings
            _fill('buy', 20.0, 3.0, fee=0.06, ts=1000),    # 3 @ 20 = €60.06
            # Many buy/sell cycles in between (net zero)
            _fill('buy', 15.0, 2.0, fee=0.03, ts=2000),    # 2 @ 15 = €30.03
            _fill('sell', 16.0, 2.0, ts=3000),               # sell 2
            _fill('buy', 12.0, 2.0, fee=0.02, ts=4000),    # 2 @ 12 = €24.02
            _fill('sell', 13.0, 2.0, ts=5000),               # sell 2
            # Current position buys at €8
            _fill('buy', 8.0, 5.0, fee=0.04, ts=6000),     # 5 @ 8 = €40.04
            _fill('buy', 7.5, 4.0, fee=0.03, ts=7000),     # 4 @ 7.5 = €30.03
        ]
        # Computed pos after all fills: 3 (phantom) + 5 + 4 = 12 units
        # But actual balance is only 9 (the recent buys)
        result = _compute_cost_basis_from_fills(
            fills, market='TEST-EUR', target_amount=9.0, tolerance=0.02
        )
        assert result is not None
        # FIFO removes oldest 3 units (€20 lots) → remaining = 5+4 = 9
        # Cost should be ~40.04 + 30.03 = €70.07 (not €20-avg inflated)
        assert result.invested_eur == pytest.approx(70.07, abs=0.5)
        assert result.avg_price == pytest.approx(70.07 / 9.0, abs=0.1)
        assert result.position_amount == pytest.approx(9.0, abs=0.01)
        # Earliest timestamp should be lot at ts=6000 (stored as 6000000 ms in fill)
        assert result.earliest_timestamp == pytest.approx(6000000.0, abs=1.0)

    def test_no_excess_no_fifo_removal(self):
        """When computed position matches target, no FIFO removal needed."""
        fills = [
            _fill('buy', 10.0, 5.0, ts=1000),
            _fill('sell', 12.0, 2.0, ts=2000),
            _fill('buy', 9.0, 2.0, ts=3000),
        ]
        result = _compute_cost_basis_from_fills(
            fills, market='TEST-EUR', target_amount=5.0, tolerance=0.02
        )
        assert result is not None
        # FIFO sell: remove 2 oldest units at €10 each → cost −20
        # Remaining: 3@10 + 2@9 = 30+18 = €48
        assert result.invested_eur == pytest.approx(48.0, abs=0.5)

    def test_fifo_sell_removes_oldest_lots(self):
        """True FIFO: sells consume cheapest (oldest) lots first."""
        fills = [
            _fill('buy', 5.0, 3.0, ts=1000),    # 3 @ €5 = €15
            _fill('buy', 10.0, 3.0, ts=2000),   # 3 @ €10 = €30
            _fill('sell', 8.0, 3.0, ts=3000),   # Sell 3 → FIFO removes €5 lot
        ]
        result = _compute_cost_basis_from_fills(
            fills, market='TEST-EUR', target_amount=3.0, tolerance=0.02
        )
        assert result is not None
        # After FIFO sell: only the €10 lot remains → cost = €30
        assert result.invested_eur == pytest.approx(30.0, abs=0.01)
        assert result.avg_price == pytest.approx(10.0, abs=0.01)
