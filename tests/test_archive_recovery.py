"""Tests for recover_cost_from_archive — FIX #020."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch


FAKE_TRADES = [
    {
        "market": "SOL-EUR",
        "buy_price": 77.65,
        "sell_price": 82.89,
        "amount": 0.145,
        "profit": 0.74,
        "timestamp": 1773691011.0,
        "reason": "partial_tp_1",
        "invested_eur": 11.28,
        "phase": "production",
    },
    {
        "market": "SOL-EUR",
        "buy_price": 76.55,
        "sell_price": 77.66,
        "amount": 0.054,
        "profit": 0.06,
        "timestamp": 1773569841.0,
        "reason": "auto_free_slot",
        "invested_eur": 4.17,
        "phase": "production",
    },
    {
        "market": "LINK-EUR",
        "buy_price": 8.50,
        "sell_price": 9.00,
        "amount": 5.0,
        "profit": 2.50,
        "timestamp": 1773500000.0,
        "reason": "trailing_tp",
        "invested_eur": 42.50,
        "phase": "production",
    },
]


def _fake_get_all_trades(market=None, **kwargs):
    """Return filtered fake trades."""
    trades = FAKE_TRADES
    if market is not None:
        trades = [t for t in trades if t.get("market") == market]
    return trades


@pytest.fixture(autouse=True)
def mock_archive(monkeypatch):
    """Patch get_all_trades so recover_cost_from_archive uses fake data."""
    monkeypatch.setattr("modules.trade_archive.get_all_trades", _fake_get_all_trades)


class TestRecoverCostFromArchive:
    """Test archive-based cost recovery for orphaned positions."""

    def test_partial_tp_recovery_uses_archived_buy_price(self):
        from modules.trade_archive import recover_cost_from_archive

        result = recover_cost_from_archive("SOL-EUR", 0.17)
        assert result is not None
        assert result["buy_price"] == pytest.approx(77.65)
        # invested = amount × archived buy_price
        assert result["invested_eur"] == pytest.approx(0.17 * 77.65, abs=0.01)
        assert "partial_tp" in result["source"]

    def test_no_partial_tp_uses_last_trade(self):
        from modules.trade_archive import recover_cost_from_archive

        result = recover_cost_from_archive("LINK-EUR", 3.0)
        assert result is not None
        assert result["buy_price"] == pytest.approx(8.50)
        assert result["invested_eur"] == pytest.approx(3.0 * 8.50, abs=0.01)
        assert "archive_last_trade" in result["source"]

    def test_unknown_market_returns_none(self):
        from modules.trade_archive import recover_cost_from_archive

        result = recover_cost_from_archive("DOGE-EUR", 100.0)
        assert result is None

    def test_recovery_keys_complete(self):
        from modules.trade_archive import recover_cost_from_archive

        result = recover_cost_from_archive("SOL-EUR", 0.17)
        assert result is not None
        assert "buy_price" in result
        assert "invested_eur" in result
        assert "initial_invested_eur" in result
        assert "total_invested_eur" in result
        assert "source" in result

    def test_empty_archive_returns_none(self, monkeypatch):
        monkeypatch.setattr("modules.trade_archive.get_all_trades", lambda **kw: [])

        from modules.trade_archive import recover_cost_from_archive

        result = recover_cost_from_archive("SOL-EUR", 0.17)
        assert result is None

    def test_zero_buy_price_skipped(self, monkeypatch):
        """Trades with buy_price=0 should be skipped."""
        bad_trades = [
            {"market": "SOL-EUR", "buy_price": 0, "reason": "partial_tp_1", "timestamp": 1.0},
            {"market": "SOL-EUR", "buy_price": 0, "reason": "trailing_tp", "timestamp": 0.5},
        ]
        monkeypatch.setattr(
            "modules.trade_archive.get_all_trades",
            lambda **kw: [t for t in bad_trades if kw.get('market') is None or t['market'] == kw['market']],
        )

        from modules.trade_archive import recover_cost_from_archive

        result = recover_cost_from_archive("SOL-EUR", 0.17)
        assert result is None
