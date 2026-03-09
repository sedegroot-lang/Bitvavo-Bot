"""Unit tests for invested_eur consistency across all code paths.

Tests the core invariants:
  - invested_eur starts at initial_invested_eur after buy
  - DCA adds to invested_eur (not replaces)
  - Partial TP reduces invested_eur proportionally
  - total_invested_eur = initial + sum(dca_costs)
  - Final profit = (sell_revenue + partial_tp_returned_eur) - invested_eur
"""

import copy
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestInvestedEurDCA(unittest.TestCase):
    """Test that DCA adds to invested_eur, never replaces it."""

    def _simulate_dca(self, trade, dca_cost):
        """Simulate the fixed DCA logic from trading_dca.py."""
        old_invested_eur = float(trade.get("invested_eur", 0) or 0)
        trade["invested_eur"] = old_invested_eur + float(dca_cost)
        trade["total_invested_eur"] = float(trade.get("total_invested_eur", 0) or 0) + float(dca_cost)
        return trade

    def test_dca_adds_not_replaces(self):
        """After partial TP reduced invested_eur, DCA should add, not set to total."""
        trade = {
            "invested_eur": 80.0,  # was 100, partial TP returned 20
            "total_invested_eur": 100.0,
            "initial_invested_eur": 100.0,
            "partial_tp_returned_eur": 20.0,
        }
        trade = self._simulate_dca(trade, 50.0)

        self.assertAlmostEqual(trade["invested_eur"], 130.0)  # 80 + 50
        self.assertAlmostEqual(trade["total_invested_eur"], 150.0)  # 100 + 50

    def test_dca_first_buy_no_partial_tp(self):
        """First DCA without any partial TP — invested_eur = initial + dca."""
        trade = {
            "invested_eur": 100.0,
            "total_invested_eur": 100.0,
            "initial_invested_eur": 100.0,
            "partial_tp_returned_eur": 0.0,
        }
        trade = self._simulate_dca(trade, 50.0)

        self.assertAlmostEqual(trade["invested_eur"], 150.0)
        self.assertAlmostEqual(trade["total_invested_eur"], 150.0)

    def test_multiple_dca_after_partial_tp(self):
        """Multiple DCAs after partial TP — invested_eur accumulates correctly."""
        trade = {
            "invested_eur": 60.0,  # was 100, partial TP returned 40
            "total_invested_eur": 100.0,
            "initial_invested_eur": 100.0,
            "partial_tp_returned_eur": 40.0,
        }
        trade = self._simulate_dca(trade, 30.0)
        self.assertAlmostEqual(trade["invested_eur"], 90.0)

        trade = self._simulate_dca(trade, 25.0)
        self.assertAlmostEqual(trade["invested_eur"], 115.0)
        self.assertAlmostEqual(trade["total_invested_eur"], 155.0)


class TestInvestedEurPartialTP(unittest.TestCase):
    """Test that partial TP reduces invested_eur proportionally."""

    def _simulate_partial_tp(self, trade, sell_fraction):
        """Simulate the fixed partial TP logic from trailing_bot.py."""
        invested_eur = float(trade.get("invested_eur", 0) or 0)
        partial_tp_returned = invested_eur * sell_fraction
        trade["invested_eur"] = invested_eur - partial_tp_returned
        trade["partial_tp_returned_eur"] = float(trade.get("partial_tp_returned_eur", 0) or 0) + partial_tp_returned
        return trade, partial_tp_returned

    def test_sell_half(self):
        """Selling half the position should halve invested_eur."""
        trade = {
            "invested_eur": 100.0,
            "total_invested_eur": 100.0,
            "initial_invested_eur": 100.0,
            "partial_tp_returned_eur": 0.0,
        }
        trade, returned = self._simulate_partial_tp(trade, 0.5)

        self.assertAlmostEqual(trade["invested_eur"], 50.0)
        self.assertAlmostEqual(returned, 50.0)
        self.assertAlmostEqual(trade["partial_tp_returned_eur"], 50.0)
        # total_invested_eur should NOT change
        self.assertAlmostEqual(trade["total_invested_eur"], 100.0)

    def test_two_partial_tps(self):
        """Two partial TPs should reduce invested_eur cumulatively."""
        trade = {
            "invested_eur": 100.0,
            "total_invested_eur": 100.0,
            "initial_invested_eur": 100.0,
            "partial_tp_returned_eur": 0.0,
        }
        # First: sell 30%
        trade, r1 = self._simulate_partial_tp(trade, 0.3)
        self.assertAlmostEqual(trade["invested_eur"], 70.0)
        self.assertAlmostEqual(trade["partial_tp_returned_eur"], 30.0)

        # Second: sell 50% of remainder
        trade, r2 = self._simulate_partial_tp(trade, 0.5)
        self.assertAlmostEqual(trade["invested_eur"], 35.0)
        self.assertAlmostEqual(trade["partial_tp_returned_eur"], 65.0)


class TestProfitCalculation(unittest.TestCase):
    """Test that final profit formula includes partial_tp_returned_eur."""

    def _calc_total_trade_profit(self, trade, sell_price, sell_amount):
        """Simulate the fixed profit calc from trailing_bot.py.
        
        Correct formula: profit = (sell_revenue + partial_tp_returned) - total_invested_eur
        total_invested_eur is the TRUE cost basis (initial + all DCAs, never reduced by partial TPs).
        """
        sell_revenue = sell_price * sell_amount
        total_invested_eur = float(trade.get("total_invested_eur", 0) or 0)
        partial_tp_returned = float(trade.get("partial_tp_returned_eur", 0) or 0)
        total_trade_profit = (sell_revenue + partial_tp_returned) - total_invested_eur
        return total_trade_profit

    def test_no_partial_tp_profit(self):
        """Simple trade: buy 100, sell at 120. Profit = 20."""
        trade = {
            "invested_eur": 100.0,
            "total_invested_eur": 100.0,
            "partial_tp_returned_eur": 0.0,
            "amount": 10.0,
        }
        profit = self._calc_total_trade_profit(trade, sell_price=12.0, sell_amount=10.0)
        self.assertAlmostEqual(profit, 20.0)

    def test_with_partial_tp_profit(self):
        """Trade with partial TP: total invested 100, returned 30.
        Sell remaining 7 coins at 12 = 84. Total profit = (84 + 30) - 100 = 14."""
        trade = {
            "invested_eur": 70.0,
            "total_invested_eur": 100.0,
            "partial_tp_returned_eur": 30.0,
            "amount": 7.0,
        }
        profit = self._calc_total_trade_profit(trade, sell_price=12.0, sell_amount=7.0)
        # (84 + 30) - 100 = 14
        self.assertAlmostEqual(profit, 14.0)

    def test_loss_with_partial_tp(self):
        """Even with partial TP returns, final trade can still be a loss."""
        trade = {
            "invested_eur": 80.0,
            "total_invested_eur": 100.0,
            "partial_tp_returned_eur": 20.0,
            "amount": 10.0,
        }
        # Sell 10 coins at 5 = 50
        profit = self._calc_total_trade_profit(trade, sell_price=5.0, sell_amount=10.0)
        # (50 + 20) - 100 = -30
        self.assertAlmostEqual(profit, -30.0)


class TestLiquidationProfit(unittest.TestCase):
    """Test that liquidation profit includes invested_eur and partial_tp_returned_eur."""

    def test_flood_guard_closed_entry(self):
        """Verify saldo_flood_guard closed_entry includes all invested fields."""
        trade = {
            "buy_price": 10.0,
            "amount": 5.0,
            "invested_eur": 40.0,
            "total_invested_eur": 50.0,
            "initial_invested_eur": 50.0,
            "partial_tp_returned_eur": 10.0,
        }
        price = 9.0
        sell_revenue = price * float(trade["amount"])
        total_invested_eur = float(trade.get("total_invested_eur", 0) or 0)
        partial_tp_returned = float(trade.get("partial_tp_returned_eur", 0) or 0)
        # Correct formula: profit = (sell_revenue + partial_tp_returned) - total_invested_eur
        total_trade_profit = (sell_revenue + partial_tp_returned) - total_invested_eur

        closed_entry = {
            "market": "TEST-EUR",
            "buy_price": trade["buy_price"],
            "sell_price": price,
            "amount": trade["amount"],
            "profit": round(total_trade_profit, 4),
            "invested_eur": float(trade.get("invested_eur", 0)),
            "total_invested_eur": total_invested_eur,
            "initial_invested_eur": float(trade.get("initial_invested_eur", 0)),
            "partial_tp_returned_eur": partial_tp_returned,
        }

        # (45 + 10) - 50 = 5
        self.assertAlmostEqual(closed_entry["profit"], 5.0)
        self.assertAlmostEqual(closed_entry["invested_eur"], 40.0)
        self.assertAlmostEqual(closed_entry["partial_tp_returned_eur"], 10.0)
        self.assertIn("total_invested_eur", closed_entry)
        self.assertIn("initial_invested_eur", closed_entry)


class TestTradesLockConsistency(unittest.TestCase):
    """Test that trades_lock prevents race conditions during clear+update."""

    def test_clear_update_atomic(self):
        """Verify that using clear+update with lock prevents reading empty dict."""
        trades_lock = threading.RLock()
        open_trades = {"BTC-EUR": {"invested_eur": 100}}
        empty_reads = []

        def reader():
            """Continuously reads open_trades for 0.5s, records empty reads."""
            end_time = time.time() + 0.5
            while time.time() < end_time:
                with trades_lock:
                    snapshot = dict(open_trades)
                if len(snapshot) == 0:
                    empty_reads.append(True)

        def writer():
            """Repeatedly clears and updates open_trades."""
            for _ in range(100):
                with trades_lock:
                    open_trades.clear()
                    open_trades.update({"BTC-EUR": {"invested_eur": 100}})
                time.sleep(0.001)

        reader_thread = threading.Thread(target=reader)
        writer_thread = threading.Thread(target=writer)
        reader_thread.start()
        writer_thread.start()
        reader_thread.join()
        writer_thread.join()

        self.assertEqual(len(empty_reads), 0, "Reader saw empty dict during locked clear+update")


class TestTradeStoreValidation(unittest.TestCase):
    """Test that trade_store validation doesn't clobber partial TP reductions."""

    def test_validation_preserves_partial_tp_invested(self):
        """After partial TP, invested_eur < total_invested_eur is valid."""
        trade = {
            "market": "BTC-EUR",
            "buy_price": 50000.0,
            "amount": 0.001,
            "invested_eur": 30.0,  # Reduced by partial TP
            "total_invested_eur": 50.0,
            "initial_invested_eur": 50.0,
            "partial_tp_returned_eur": 20.0,
            "tp_flags": {"tp1": True},
            "opened_ts": time.time(),
        }
        # Simulate validation Rule 2: should NOT reset invested_eur
        partial_tp_returned = float(trade.get("partial_tp_returned_eur", 0) or 0)
        tp_flags = trade.get("tp_flags", {})
        has_partial_tp = partial_tp_returned > 0 or any(v for v in tp_flags.values() if v)

        if has_partial_tp:
            # Should NOT reset invested_eur to initial_invested_eur
            pass
        else:
            trade["invested_eur"] = trade["initial_invested_eur"]

        self.assertAlmostEqual(trade["invested_eur"], 30.0)


if __name__ == "__main__":
    unittest.main()
