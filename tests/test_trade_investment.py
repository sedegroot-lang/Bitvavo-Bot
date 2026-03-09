"""Tests for core.trade_investment - single source of truth for invested_eur mutations."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.trade_investment import (
    set_initial,
    add_dca,
    reduce_partial_tp,
    repair_negative,
    get_invested,
    get_total_invested,
)


class TestSetInitial(unittest.TestCase):
    """set_initial: exactly once per trade, sets all 3 fields."""

    def test_sets_all_fields(self):
        trade = {}
        set_initial(trade, 50.0, source="test")
        self.assertAlmostEqual(trade["invested_eur"], 50.0, places=2)
        self.assertAlmostEqual(trade["initial_invested_eur"], 50.0, places=2)
        self.assertAlmostEqual(trade["total_invested_eur"], 50.0, places=2)

    def test_blocks_second_call(self):
        trade = {}
        set_initial(trade, 50.0)
        set_initial(trade, 999.0)  # should be blocked
        self.assertAlmostEqual(trade["invested_eur"], 50.0, places=2)

    def test_ignores_zero(self):
        trade = {}
        set_initial(trade, 0.0)
        self.assertNotIn("invested_eur", trade)

    def test_ignores_negative(self):
        trade = {}
        set_initial(trade, -10.0)
        self.assertNotIn("invested_eur", trade)


class TestAddDca(unittest.TestCase):
    """add_dca: adds to invested_eur and total_invested_eur, preserves partial TP reductions."""

    def test_basic_add(self):
        trade = {"invested_eur": 100.0, "total_invested_eur": 100.0, "initial_invested_eur": 100.0}
        add_dca(trade, 50.0, source="test")
        self.assertAlmostEqual(trade["invested_eur"], 150.0, places=2)
        self.assertAlmostEqual(trade["total_invested_eur"], 150.0, places=2)
        # initial_invested_eur must NOT change
        self.assertAlmostEqual(trade["initial_invested_eur"], 100.0, places=2)

    def test_preserves_partial_tp_reduction(self):
        """After partial TP reduced invested_eur from 100→80, DCA should add to 80, not reset to 100."""
        trade = {
            "invested_eur": 80.0,      # was 100, partial TP returned 20
            "total_invested_eur": 100.0,
            "initial_invested_eur": 100.0,
            "partial_tp_returned_eur": 20.0,
        }
        add_dca(trade, 50.0, source="test")
        self.assertAlmostEqual(trade["invested_eur"], 130.0, places=2)  # 80 + 50
        self.assertAlmostEqual(trade["total_invested_eur"], 150.0, places=2)  # 100 + 50

    def test_ignores_zero_cost(self):
        trade = {"invested_eur": 100.0, "total_invested_eur": 100.0}
        add_dca(trade, 0.0)
        self.assertAlmostEqual(trade["invested_eur"], 100.0, places=2)

    def test_sets_initial_if_missing(self):
        """Legacy trade without initial_invested_eur gets it set on first DCA."""
        trade = {"invested_eur": 50.0, "total_invested_eur": 50.0}
        add_dca(trade, 20.0, source="test")
        self.assertAlmostEqual(trade["initial_invested_eur"], 50.0, places=2)
        self.assertAlmostEqual(trade["invested_eur"], 70.0, places=2)


class TestReducePartialTp(unittest.TestCase):
    """reduce_partial_tp: proportional reduction, total_invested_eur unchanged."""

    def test_33pct_reduction(self):
        trade = {"invested_eur": 100.0, "total_invested_eur": 100.0}
        reduction = reduce_partial_tp(trade, 0.33, source="test")
        self.assertAlmostEqual(trade["invested_eur"], 67.0, places=0)
        self.assertAlmostEqual(trade["total_invested_eur"], 100.0, places=2)
        self.assertAlmostEqual(reduction, 33.0, places=0)

    def test_50pct_reduction(self):
        trade = {"invested_eur": 200.0, "total_invested_eur": 200.0}
        reduction = reduce_partial_tp(trade, 0.5, source="test")
        self.assertAlmostEqual(trade["invested_eur"], 100.0, places=2)
        self.assertAlmostEqual(reduction, 100.0, places=2)

    def test_100pct_full_exit(self):
        trade = {"invested_eur": 100.0, "total_invested_eur": 100.0}
        reduction = reduce_partial_tp(trade, 1.0)
        self.assertAlmostEqual(trade["invested_eur"], 0.0, places=2)
        self.assertAlmostEqual(reduction, 100.0, places=2)

    def test_invalid_portion_rejected(self):
        trade = {"invested_eur": 100.0}
        reduction = reduce_partial_tp(trade, 0.0)
        self.assertAlmostEqual(reduction, 0.0, places=2)
        self.assertAlmostEqual(trade["invested_eur"], 100.0, places=2)

    def test_negative_portion_rejected(self):
        trade = {"invested_eur": 100.0}
        reduction = reduce_partial_tp(trade, -0.5)
        self.assertAlmostEqual(reduction, 0.0, places=2)

    def test_zero_invested_noop(self):
        trade = {"invested_eur": 0.0}
        reduction = reduce_partial_tp(trade, 0.5)
        self.assertAlmostEqual(reduction, 0.0, places=2)


class TestRepairNegative(unittest.TestCase):
    """repair_negative: uses trade data, NOT config constants."""

    def test_repairs_from_initial(self):
        trade = {"invested_eur": -5.0, "initial_invested_eur": 50.0}
        result = repair_negative(trade, "TEST-EUR")
        self.assertTrue(result)
        self.assertAlmostEqual(trade["invested_eur"], 50.0, places=2)

    def test_repairs_from_total(self):
        trade = {"invested_eur": -5.0, "total_invested_eur": 80.0}
        result = repair_negative(trade, "TEST-EUR")
        self.assertTrue(result)
        self.assertAlmostEqual(trade["invested_eur"], 80.0, places=2)

    def test_repairs_from_buy_price(self):
        trade = {"invested_eur": -5.0, "buy_price": 10.0, "amount": 5.0}
        result = repair_negative(trade, "TEST-EUR")
        self.assertTrue(result)
        self.assertAlmostEqual(trade["invested_eur"], 50.0, places=2)

    def test_no_repair_needed(self):
        trade = {"invested_eur": 50.0}
        result = repair_negative(trade, "TEST-EUR")
        self.assertFalse(result)

    def test_no_data_available(self):
        trade = {"invested_eur": -5.0}
        result = repair_negative(trade)
        self.assertFalse(result)
        self.assertAlmostEqual(trade["invested_eur"], -5.0, places=2)  # unchanged


class TestGetters(unittest.TestCase):
    """get_invested / get_total_invested: safe reading."""

    def test_get_invested_normal(self):
        self.assertAlmostEqual(get_invested({"invested_eur": 42.0}), 42.0, places=2)

    def test_get_invested_missing(self):
        self.assertAlmostEqual(get_invested({}), 0.0, places=2)

    def test_get_invested_none(self):
        self.assertAlmostEqual(get_invested({"invested_eur": None}), 0.0, places=2)

    def test_get_total_normal(self):
        self.assertAlmostEqual(get_total_invested({"total_invested_eur": 100.0}), 100.0, places=2)

    def test_get_total_falls_back(self):
        self.assertAlmostEqual(get_total_invested({"invested_eur": 50.0}), 50.0, places=2)


class TestFullTradeLifecycle(unittest.TestCase):
    """End-to-end: buy → DCA → partial TP → DCA → close."""

    def test_lifecycle(self):
        trade = {}

        # 1. Initial buy: €100
        set_initial(trade, 100.0, source="buy")
        self.assertAlmostEqual(trade["invested_eur"], 100.0, places=2)
        self.assertAlmostEqual(trade["total_invested_eur"], 100.0, places=2)

        # 2. DCA: +€50
        add_dca(trade, 50.0, source="dca1")
        self.assertAlmostEqual(trade["invested_eur"], 150.0, places=2)
        self.assertAlmostEqual(trade["total_invested_eur"], 150.0, places=2)
        self.assertAlmostEqual(trade["initial_invested_eur"], 100.0, places=2)

        # 3. Partial TP: sell 33%
        reduction = reduce_partial_tp(trade, 0.33, source="tp1")
        self.assertAlmostEqual(trade["invested_eur"], 100.5, places=0)  # 150 * 0.67
        self.assertAlmostEqual(trade["total_invested_eur"], 150.0, places=2)  # unchanged

        # 4. Another DCA: +€30
        add_dca(trade, 30.0, source="dca2")
        self.assertAlmostEqual(trade["invested_eur"], 130.5, places=0)  # 100.5 + 30
        self.assertAlmostEqual(trade["total_invested_eur"], 180.0, places=2)  # 150 + 30

        # 5. Final close: sell 100%
        reduction = reduce_partial_tp(trade, 1.0, source="close")
        self.assertAlmostEqual(trade["invested_eur"], 0.0, places=2)
        self.assertAlmostEqual(trade["total_invested_eur"], 180.0, places=2)  # still unchanged


if __name__ == "__main__":
    unittest.main()
