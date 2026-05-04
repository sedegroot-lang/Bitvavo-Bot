"""FIX #075 regression test.

The sync_validator's `add_missing_positions` previously OVERWROTE existing
trade entries with default state (dca_buys=0, dca_events=[],
trailing_activated=False, initial_invested_eur=invested_eur). When ENJ-EUR
was briefly seen as "missing" the validator wiped the reconciled DCA
history and trailing high-water mark every cycle.

This test guarantees the merge path: when an entry already exists with
non-empty DCA / trailing state, only `amount` and `synced_at` are touched.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from modules.sync_validator import SyncValidator


@pytest.fixture
def trade_log(tmp_path: Path) -> Path:
    log = {
        "open": {
            "ENJ-EUR": {
                "market": "ENJ-EUR",
                "buy_price": 0.04617522723082622,
                "amount": 26026.94284534,
                "invested_eur": 1201.80,
                "initial_invested_eur": 285.23,
                "total_invested_eur": 1201.80,
                "dca_buys": 4,
                "dca_max": 3,
                "dca_events": [
                    {"price": 0.05, "amount_eur": 285.23},
                    {"price": 0.048, "amount_eur": 288.0},
                    {"price": 0.046, "amount_eur": 288.0},
                    {"price": 0.044, "amount_eur": 340.0},
                ],
                "trailing_activated": True,
                "highest_since_activation": 0.04730,
                "highest_price": 0.04730,
            }
        },
        "closed": [],
    }
    p = tmp_path / "trade_log.json"
    p.write_text(json.dumps(log), encoding="utf-8")
    return p


def _make_validator(trade_log_path: Path) -> SyncValidator:
    bv = MagicMock()
    sv = SyncValidator(bv, Path(trade_log_path))
    return sv


def test_existing_entry_with_dca_history_is_preserved(trade_log: Path) -> None:
    sv = _make_validator(trade_log)
    additions = [{
        "symbol": "ENJ",
        "market": "ENJ-EUR",
        "amount": 26026.94284534,
        "price": 0.0462,
        "invested": 1201.80,
        "initial_invested_eur": 1201.80,  # WRONG value sync_validator would normally inject
        "total_invested_eur": 1201.80,
    }]
    n = sv._apply_additions(additions, dca_max_buys=3, dca_drop_pct=0.03)
    assert n == 1

    after = json.loads(trade_log.read_text(encoding="utf-8"))
    enj = after["open"]["ENJ-EUR"]

    # Reconciled state must NOT be wiped
    assert enj["dca_buys"] == 4
    assert len(enj["dca_events"]) == 4
    assert enj["trailing_activated"] is True
    assert enj["highest_since_activation"] == pytest.approx(0.04730)
    # initial must keep the reconciled (lower) value, not the bogus total cost
    assert enj["initial_invested_eur"] == pytest.approx(285.23)
    # synced_at must be refreshed
    assert enj.get("synced_at") is not None


def test_missing_entry_is_added_normally(trade_log: Path) -> None:
    sv = _make_validator(trade_log)
    additions = [{
        "symbol": "DOT",
        "market": "DOT-EUR",
        "amount": 10.0,
        "price": 5.0,
        "invested": 50.0,
        "initial_invested_eur": 50.0,
        "total_invested_eur": 50.0,
    }]
    n = sv._apply_additions(additions, dca_max_buys=3, dca_drop_pct=0.03)
    assert n == 1

    after = json.loads(trade_log.read_text(encoding="utf-8"))
    dot = after["open"]["DOT-EUR"]
    assert dot["dca_buys"] == 0
    assert dot.get("dca_events", []) in ([], None)
    assert dot["initial_invested_eur"] == pytest.approx(50.0)
