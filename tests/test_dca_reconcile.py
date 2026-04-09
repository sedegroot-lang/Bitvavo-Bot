# -*- coding: utf-8 -*-
"""Tests for core.dca_reconcile — Bitvavo SSOT reconcile engine.

Tests cover:
  1. No fills → no changes
  2. All events already present → no changes
  3. Missing DCA event → added with source="reconcile"
  4. Missing multiple DCAs → all recovered
  5. Amount correction (>0.1% diff)
  6. invested_eur correction (>1% diff)
  7. Dry run mode → no mutations
  8. Error handling (API failure)
  9. Order ID enrichment on existing events
  10. reconcile_all_trades — batch processing
"""

import time
import uuid
from unittest.mock import MagicMock

import pytest

from core.dca_reconcile import (
    ReconcileResult,
    _fetch_filled_buys,
    _group_fills_by_order,
    reconcile_all_trades,
    reconcile_trade,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trade(**overrides) -> dict:
    """Minimal trade dict."""
    trade = {
        "buy_price": 2.5,
        "amount": 20.0,
        "invested_eur": 50.0,
        "initial_invested_eur": 50.0,
        "total_invested_eur": 50.0,
        "dca_buys": 0,
        "dca_events": [],
        "dca_max": 5,
        "partial_tp_returned_eur": 0.0,
        "opened_ts": 1700000000.0,
    }
    trade.update(overrides)
    return trade


def _make_fill(
    order_id: str = "ord-1",
    side: str = "buy",
    amount: float = 20.0,
    price: float = 2.5,
    fee: float = 0.25,
    timestamp: int = 1700000000000,
    fill_id: str | None = None,
) -> dict:
    return {
        "id": fill_id or str(uuid.uuid4()),
        "orderId": order_id,
        "side": side,
        "amount": str(amount),
        "price": str(price),
        "fee": str(fee),
        "timestamp": timestamp,
    }


def _mock_bitvavo(fills: list) -> MagicMock:
    """Create a mock Bitvavo client that returns the given fills."""
    bv = MagicMock()
    bv.trades = MagicMock(return_value=fills)
    return bv


# ---------------------------------------------------------------------------
# _group_fills_by_order
# ---------------------------------------------------------------------------
class TestGroupFillsByOrder:
    def test_single_fill(self):
        fills = [_make_fill(order_id="ord-1", amount=10, price=2.5, fee=0.1, timestamp=1000)]
        orders = _group_fills_by_order(fills)
        assert len(orders) == 1
        assert orders[0]["orderId"] == "ord-1"
        assert orders[0]["total_amount"] == pytest.approx(10.0)
        assert orders[0]["total_cost"] == pytest.approx(25.0)
        assert orders[0]["total_fee"] == pytest.approx(0.1)

    def test_multiple_fills_same_order(self):
        fills = [
            _make_fill(order_id="ord-1", amount=5, price=2.5, fee=0.05, timestamp=1000),
            _make_fill(order_id="ord-1", amount=5, price=2.6, fee=0.05, timestamp=1001),
        ]
        orders = _group_fills_by_order(fills)
        assert len(orders) == 1
        assert orders[0]["total_amount"] == pytest.approx(10.0)
        assert orders[0]["total_cost"] == pytest.approx(5 * 2.5 + 5 * 2.6)
        assert orders[0]["total_fee"] == pytest.approx(0.10)

    def test_multiple_orders(self):
        fills = [
            _make_fill(order_id="ord-1", amount=20, price=2.5, fee=0.2, timestamp=1000),
            _make_fill(order_id="ord-2", amount=15, price=2.3, fee=0.15, timestamp=2000),
        ]
        orders = _group_fills_by_order(fills)
        assert len(orders) == 2
        assert orders[0]["orderId"] == "ord-1"
        assert orders[1]["orderId"] == "ord-2"

    def test_sorted_by_timestamp(self):
        fills = [
            _make_fill(order_id="ord-2", amount=10, price=2.3, fee=0.1, timestamp=2000),
            _make_fill(order_id="ord-1", amount=20, price=2.5, fee=0.2, timestamp=1000),
        ]
        orders = _group_fills_by_order(fills)
        assert orders[0]["orderId"] == "ord-1"
        assert orders[1]["orderId"] == "ord-2"


# ---------------------------------------------------------------------------
# reconcile_trade — no fills
# ---------------------------------------------------------------------------
class TestReconcileNoFills:
    def test_no_fills_returns_empty_result(self):
        bv = _mock_bitvavo([])
        trade = _make_trade()
        result = reconcile_trade(bv, "UNI-EUR", trade)
        assert result.events_added == 0
        assert result.exchange_dca_count == 0
        assert not result.amount_corrected
        assert "No fills" in result.repairs[0]


# ---------------------------------------------------------------------------
# reconcile_trade — all events already present
# ---------------------------------------------------------------------------
class TestReconcileAlreadyPresent:
    def test_initial_only_no_dcas(self):
        fills = [_make_fill(order_id="ord-initial", amount=20, price=2.5, fee=0.25, timestamp=1700000000000)]
        bv = _mock_bitvavo(fills)
        trade = _make_trade(invested_eur=50.25, total_invested_eur=50.25)  # 20*2.5+0.25
        result = reconcile_trade(bv, "UNI-EUR", trade)
        assert result.events_added == 0
        assert result.exchange_dca_count == 0

    def test_existing_dca_matched_by_order_id(self):
        fills = [
            _make_fill(order_id="ord-initial", amount=20, price=2.5, fee=0.25, timestamp=1700000000000),
            _make_fill(order_id="ord-dca1", amount=15, price=2.3, fee=0.15, timestamp=1700001000000),
        ]
        bv = _mock_bitvavo(fills)
        trade = _make_trade(
            dca_buys=1,
            dca_events=[{
                "event_id": "ev-1",
                "timestamp": 1700001000.0,
                "price": 2.3,
                "amount_eur": 34.65,
                "tokens_bought": 15.0,
                "dca_level": 1,
                "source": "bot",
                "order_id": "ord-dca1",
            }],
        )
        result = reconcile_trade(bv, "UNI-EUR", trade)
        assert result.events_added == 0


# ---------------------------------------------------------------------------
# reconcile_trade — missing DCA events
# ---------------------------------------------------------------------------
class TestReconcileMissingDCA:
    def test_one_missing_dca(self):
        """DCA exists on Bitvavo but not in bot → should be recovered."""
        fills = [
            _make_fill(order_id="ord-initial", amount=20, price=2.5, fee=0.25, timestamp=1700000000000),
            _make_fill(order_id="ord-dca1", amount=15, price=2.3, fee=0.15, timestamp=1700001000000),
        ]
        bv = _mock_bitvavo(fills)
        trade = _make_trade(
            amount=35.0,  # 20+15
            invested_eur=84.90,  # realistic cost
            total_invested_eur=84.90,
        )
        result = reconcile_trade(bv, "UNI-EUR", trade)
        assert result.events_added == 1
        assert result.exchange_dca_count == 1
        assert len(trade["dca_events"]) == 1
        assert trade["dca_events"][0]["source"] == "reconcile"
        assert trade["dca_events"][0]["order_id"] == "ord-dca1"
        assert trade["dca_buys"] == 1

    def test_multiple_missing_dcas(self):
        """Multiple DCAs on Bitvavo but none in bot → all recovered."""
        fills = [
            _make_fill(order_id="ord-initial", amount=20, price=2.5, fee=0.25, timestamp=1700000000000),
            _make_fill(order_id="ord-dca1", amount=15, price=2.3, fee=0.15, timestamp=1700001000000),
            _make_fill(order_id="ord-dca2", amount=12, price=2.1, fee=0.12, timestamp=1700002000000),
            _make_fill(order_id="ord-dca3", amount=10, price=1.9, fee=0.10, timestamp=1700003000000),
        ]
        bv = _mock_bitvavo(fills)
        trade = _make_trade(amount=57.0, invested_eur=130.0, total_invested_eur=130.0)
        result = reconcile_trade(bv, "UNI-EUR", trade)
        assert result.events_added == 3
        assert trade["dca_buys"] == 3
        levels = [ev["dca_level"] for ev in trade["dca_events"]]
        assert levels == [1, 2, 3]

    def test_partial_missing_dcas(self):
        """2 DCAs on exchange, only 1 known to bot → 1 recovered."""
        fills = [
            _make_fill(order_id="ord-initial", amount=20, price=2.5, fee=0.25, timestamp=1700000000000),
            _make_fill(order_id="ord-dca1", amount=15, price=2.3, fee=0.15, timestamp=1700001000000),
            _make_fill(order_id="ord-dca2", amount=12, price=2.1, fee=0.12, timestamp=1700002000000),
        ]
        bv = _mock_bitvavo(fills)
        trade = _make_trade(
            dca_buys=1,
            dca_events=[{
                "event_id": "ev-1",
                "timestamp": 1700001000.0,
                "price": 2.3,
                "amount_eur": 34.65,
                "tokens_bought": 15.0,
                "dca_level": 1,
                "source": "bot",
                "order_id": "ord-dca1",
            }],
            amount=47.0,
            invested_eur=110.0,
            total_invested_eur=110.0,
        )
        result = reconcile_trade(bv, "UNI-EUR", trade)
        assert result.events_added == 1
        assert trade["dca_buys"] == 2
        assert trade["dca_events"][-1]["order_id"] == "ord-dca2"

    def test_fuzzy_match_by_timestamp(self):
        """Event without order_id but matching timestamp+amount → no duplicate."""
        fills = [
            _make_fill(order_id="ord-initial", amount=20, price=2.5, fee=0.25, timestamp=1700000000000),
            _make_fill(order_id="ord-dca1", amount=15, price=2.3, fee=0.15, timestamp=1700001000000),
        ]
        bv = _mock_bitvavo(fills)
        trade = _make_trade(
            dca_buys=1,
            dca_events=[{
                "event_id": "ev-1",
                "timestamp": 1700001000.0,  # matches exchange
                "price": 2.3,
                "amount_eur": 34.65,  # matches 15*2.3+0.15 = 34.65
                "tokens_bought": 15.0,
                "dca_level": 1,
                "source": "bot",
                # NO order_id
            }],
        )
        result = reconcile_trade(bv, "UNI-EUR", trade)
        assert result.events_added == 0  # fuzzy match prevents duplicate


# ---------------------------------------------------------------------------
# reconcile_trade — financial corrections
# ---------------------------------------------------------------------------
class TestReconcileFinancials:
    def test_amount_corrected(self):
        """Exchange shows different amount → corrected."""
        fills = [
            _make_fill(order_id="ord-initial", amount=20.5, price=2.5, fee=0.25, timestamp=1700000000000),
        ]
        bv = _mock_bitvavo(fills)
        trade = _make_trade(amount=20.0, invested_eur=51.50, total_invested_eur=51.50)  # off by 0.5
        result = reconcile_trade(bv, "UNI-EUR", trade)
        assert result.amount_corrected
        assert trade["amount"] == pytest.approx(20.5, abs=0.0001)

    def test_invested_corrected(self):
        """invested_eur significantly off → corrected from exchange data."""
        fills = [
            _make_fill(order_id="ord-initial", amount=20, price=2.5, fee=0.25, timestamp=1700000000000),
        ]
        bv = _mock_bitvavo(fills)
        # Exchange: 20*2.5 + 0.25 = 50.25 → invested should be 50.25
        trade = _make_trade(amount=20.0, invested_eur=45.0, total_invested_eur=45.0)
        result = reconcile_trade(bv, "UNI-EUR", trade)
        assert result.invested_corrected
        assert trade["invested_eur"] == pytest.approx(50.25, abs=0.01)

    def test_no_correction_when_close(self):
        """Amount within 0.1% → no correction."""
        fills = [
            _make_fill(order_id="ord-initial", amount=20.0, price=2.5, fee=0.25, timestamp=1700000000000),
        ]
        bv = _mock_bitvavo(fills)
        trade = _make_trade(amount=20.01, invested_eur=50.25, total_invested_eur=50.25)
        result = reconcile_trade(bv, "UNI-EUR", trade)
        assert not result.amount_corrected


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------
class TestReconcileDryRun:
    def test_dry_run_no_mutations(self):
        fills = [
            _make_fill(order_id="ord-initial", amount=20, price=2.5, fee=0.25, timestamp=1700000000000),
            _make_fill(order_id="ord-dca1", amount=15, price=2.3, fee=0.15, timestamp=1700001000000),
        ]
        bv = _mock_bitvavo(fills)
        trade = _make_trade()
        original_events = list(trade["dca_events"])
        original_amount = trade["amount"]
        result = reconcile_trade(bv, "UNI-EUR", trade, dry_run=True)
        assert result.events_added == 1
        assert trade["dca_events"] == original_events  # not mutated
        assert trade["amount"] == original_amount  # not mutated


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
class TestReconcileErrors:
    def test_api_error(self):
        bv = MagicMock()
        bv.trades = MagicMock(side_effect=Exception("API timeout"))
        trade = _make_trade()
        result = reconcile_trade(bv, "UNI-EUR", trade)
        assert result.events_added == 0
        assert "No fills" in result.repairs[0]


# ---------------------------------------------------------------------------
# Order ID enrichment
# ---------------------------------------------------------------------------
class TestOrderIdEnrichment:
    def test_existing_event_gets_order_id(self):
        fills = [
            _make_fill(order_id="ord-initial", amount=20, price=2.5, fee=0.25, timestamp=1700000000000),
            _make_fill(order_id="ord-dca1", amount=15, price=2.3, fee=0.15, timestamp=1700001000000),
        ]
        bv = _mock_bitvavo(fills)
        trade = _make_trade(
            dca_buys=1,
            dca_events=[{
                "event_id": "ev-1",
                "timestamp": 1700001000.0,
                "price": 2.3,
                "amount_eur": 34.65,
                "tokens_bought": 15.0,
                "dca_level": 1,
                "source": "bot",
                # no order_id
            }],
        )
        reconcile_trade(bv, "UNI-EUR", trade)
        assert trade["dca_events"][0].get("order_id") == "ord-dca1"


# ---------------------------------------------------------------------------
# reconcile_all_trades
# ---------------------------------------------------------------------------
class TestReconcileAll:
    def test_processes_multiple_markets(self):
        fills_uni = [
            _make_fill(order_id="ord-u1", amount=20, price=2.5, fee=0.25, timestamp=1700000000000),
        ]
        fills_xrp = [
            _make_fill(order_id="ord-x1", amount=50, price=1.2, fee=0.30, timestamp=1700000000000),
        ]
        bv = MagicMock()
        bv.trades = MagicMock(side_effect=[fills_uni, fills_xrp])

        trades = {
            "UNI-EUR": _make_trade(invested_eur=50.25, total_invested_eur=50.25),
            "XRP-EUR": _make_trade(amount=50, buy_price=1.2, invested_eur=60.30, total_invested_eur=60.30),
        }
        results = reconcile_all_trades(bv, trades)
        assert len(results) == 2
        markets = {r.market for r in results}
        assert "UNI-EUR" in markets
        assert "XRP-EUR" in markets

    def test_exclude_markets(self):
        bv = _mock_bitvavo([])
        trades = {
            "UNI-EUR": _make_trade(),
            "BTC-EUR": _make_trade(),
        }
        results = reconcile_all_trades(bv, trades, exclude_markets={"BTC-EUR"})
        assert len(results) == 1
        assert results[0].market == "UNI-EUR"
