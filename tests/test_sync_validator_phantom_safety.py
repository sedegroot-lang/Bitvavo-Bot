"""FIX #083 regression test.

`auto_fix_phantom_positions` historically called `get_bitvavo_balances()`
once and trusted the result. When the API returned empty/partial data due
to a transient hiccup, EVERY bot position appeared to be a phantom and the
validator deleted them. On 2026-05-05 this caused real ENJ + RENDER
positions to be wiped during startup sync.

Three safety gates now prevent mass deletion:
1. Empty balance fetch -> abort.
2. Verification fetch (second call) empty -> abort.
3. Would delete >= 50% of non-skipped positions -> abort.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from modules.sync_validator import SyncValidator


def _trade_log_with(symbols: list[str]) -> dict:
    return {
        "open": {
            f"{s}-EUR": {
                "market": f"{s}-EUR",
                "buy_price": 1.0,
                "amount": 100.0,
                "invested_eur": 100.0,
                "initial_invested_eur": 100.0,
            }
            for s in symbols
        },
        "closed": [],
        "profits": {},
    }


def _write(tmp_path: Path, log: dict) -> Path:
    p = tmp_path / "trade_log.json"
    p.write_text(json.dumps(log), encoding="utf-8")
    return p


class TestPhantomFixSafetyGates:
    def test_empty_balances_aborts(self, tmp_path: Path):
        """Gate 1: API returns no balances -> never delete anything."""
        bv = MagicMock()
        bv.balance.return_value = []  # API hiccup / empty response
        log_path = _write(tmp_path, _trade_log_with(["ENJ", "RENDER", "DOT"]))
        v = SyncValidator(bv, log_path)
        fixed = v.auto_fix_phantom_positions(dry_run=False)
        assert fixed == 0
        # Trade log untouched
        after = json.loads(log_path.read_text(encoding="utf-8"))
        assert set(after["open"].keys()) == {"ENJ-EUR", "RENDER-EUR", "DOT-EUR"}

    def test_majority_phantom_aborts(self, tmp_path: Path):
        """Gate 3: would-delete >=50% -> abort (smells like a sync bug)."""
        bv = MagicMock()
        # Bot has 3 positions; Bitvavo only reports 1 -> 2 candidates = 66%
        bv.balance.return_value = [
            {"symbol": "DOT", "available": "100.0", "inOrder": "0"},
            {"symbol": "EUR", "available": "50.0", "inOrder": "0"},
        ]
        log_path = _write(tmp_path, _trade_log_with(["ENJ", "RENDER", "DOT"]))
        v = SyncValidator(bv, log_path)
        fixed = v.auto_fix_phantom_positions(dry_run=False)
        assert fixed == 0
        after = json.loads(log_path.read_text(encoding="utf-8"))
        assert set(after["open"].keys()) == {"ENJ-EUR", "RENDER-EUR", "DOT-EUR"}

    def test_single_genuine_phantom_is_removed(self, tmp_path: Path):
        """Happy path: 1 of 4 positions truly missing on Bitvavo -> remove it."""
        bv = MagicMock()
        bv.balance.return_value = [
            {"symbol": "DOT", "available": "100.0", "inOrder": "0"},
            {"symbol": "ENJ", "available": "100.0", "inOrder": "0"},
            {"symbol": "RENDER", "available": "100.0", "inOrder": "0"},
            {"symbol": "EUR", "available": "50.0", "inOrder": "0"},
            # SOL missing -> genuine phantom
        ]
        log_path = _write(tmp_path, _trade_log_with(["ENJ", "RENDER", "DOT", "SOL"]))
        v = SyncValidator(bv, log_path)
        fixed = v.auto_fix_phantom_positions(dry_run=False)
        assert fixed == 1
        after = json.loads(log_path.read_text(encoding="utf-8"))
        assert "SOL-EUR" not in after["open"]
        assert set(after["open"].keys()) == {"ENJ-EUR", "RENDER-EUR", "DOT-EUR"}

    def test_partial_then_full_balance_unions(self, tmp_path: Path):
        """If two fetches disagree, union the symbols (don't delete on transient miss)."""
        bv = MagicMock()
        # First call: missing ENJ, second call: missing RENDER -> union has both
        bv.balance.side_effect = [
            [
                {"symbol": "RENDER", "available": "100.0", "inOrder": "0"},
                {"symbol": "DOT", "available": "100.0", "inOrder": "0"},
                {"symbol": "EUR", "available": "50.0", "inOrder": "0"},
            ],
            [
                {"symbol": "ENJ", "available": "100.0", "inOrder": "0"},
                {"symbol": "DOT", "available": "100.0", "inOrder": "0"},
                {"symbol": "EUR", "available": "50.0", "inOrder": "0"},
            ],
        ]
        log_path = _write(tmp_path, _trade_log_with(["ENJ", "RENDER", "DOT"]))
        v = SyncValidator(bv, log_path)
        fixed = v.auto_fix_phantom_positions(dry_run=False)
        # Union of fetches sees ENJ+RENDER+DOT -> nothing should be deleted
        assert fixed == 0
        after = json.loads(log_path.read_text(encoding="utf-8"))
        assert set(after["open"].keys()) == {"ENJ-EUR", "RENDER-EUR", "DOT-EUR"}
