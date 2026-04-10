import json

import pytest

pytest.importorskip("flask", reason="flask not installed")
import tools.dashboard_flask.app as app


def test_get_total_deposited_prefers_entry_sum(monkeypatch):
    """Test that entry sum is preferred over stored total."""
    data = {
        "total_deposited_eur": 50.0,
        "deposits": [
            {"amount": 12.5},
            {"amount": 7.5},
        ],
        "last_synced": "2099-01-01T00:00:00+00:00",  # Future date to skip sync
    }
    # Mock load_deposits to return our test data
    monkeypatch.setattr(app, "load_deposits", lambda: data)
    # Mock sync to not call Bitvavo API
    monkeypatch.setattr(app, "sync_deposits_from_bitvavo", lambda: data)

    assert app.get_total_deposited() == 20.0


def test_get_total_deposited_falls_back_to_stored_total(monkeypatch):
    """Test fallback to stored total when no deposits exist."""
    data = {
        "total_deposited_eur": 15.25,
        "deposits": [],
        "last_synced": "2099-01-01T00:00:00+00:00",  # Future date to skip sync
    }
    # Mock load_deposits to return our test data
    monkeypatch.setattr(app, "load_deposits", lambda: data)
    # Mock sync to not call Bitvavo API
    monkeypatch.setattr(app, "sync_deposits_from_bitvavo", lambda: data)

    assert app.get_total_deposited() == 15.25


def test_calculate_portfolio_totals_uses_deposits_and_balance(monkeypatch):
    """Test portfolio totals use deposits and balance correctly."""
    monkeypatch.setattr(app, "get_total_deposited", lambda: 100.0)
    # Mock get_cached_balances to return controlled data
    monkeypatch.setattr(app, "get_cached_balances", lambda: [{"symbol": "EUR", "available": 25.0, "inOrder": 0}])
    cards = [
        {"invested": 40.0, "current_value": 50.0, "pnl": 10.0, "pnl_pct": 25.0},
    ]
    heartbeat = {"eur_balance": 25.0}

    totals = app.calculate_portfolio_totals(cards, heartbeat)

    assert totals["total_account_value"] == pytest.approx(75.0)
    assert totals["real_profit"] == pytest.approx(-25.0)
    assert totals["real_profit_pct"] == pytest.approx(-25.0)
