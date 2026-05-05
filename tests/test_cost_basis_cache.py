"""FIX #084 — persistent cost-basis cache regression tests.

The cache exists to survive sync_engine wiping cost basis for positions whose
true buy_price cannot be derived from `bv.trades()` (swaps, airdrops,
recoveries). Without it, NOT-EUR's invested_eur was reset to 0 on every sync.
"""
from __future__ import annotations

from pathlib import Path
import importlib

import pytest


@pytest.fixture
def cbc(tmp_path: Path, monkeypatch):
    """Reload module pointed at a temp cache file."""
    import core.cost_basis_cache as mod

    monkeypatch.setattr(mod, "_CACHE_PATH", tmp_path / "cost_basis_cache.json")
    importlib.reload(mod)  # noqa: PLW0603 - reload to pick up monkeypatched path
    monkeypatch.setattr(mod, "_CACHE_PATH", tmp_path / "cost_basis_cache.json")
    return mod


class TestCacheCRUD:
    def test_get_missing_returns_none(self, cbc):
        assert cbc.get("FOO-EUR") is None

    def test_set_then_get(self, cbc):
        cbc.set("NOT-EUR", buy_price=0.0004307, invested_eur=617.97, amount=1.4e6, source="swap")
        e = cbc.get("NOT-EUR")
        assert e is not None
        assert e["buy_price"] == pytest.approx(0.0004307)
        assert e["invested_eur"] == pytest.approx(617.97)
        assert e["source"] == "swap"

    def test_set_overwrites(self, cbc):
        cbc.set("NOT-EUR", buy_price=0.0004, invested_eur=600.0)
        cbc.set("NOT-EUR", buy_price=0.0005, invested_eur=700.0)
        assert cbc.get("NOT-EUR")["invested_eur"] == pytest.approx(700.0)

    def test_remove(self, cbc):
        cbc.set("X-EUR", buy_price=1.0, invested_eur=10.0)
        assert cbc.remove("X-EUR") is True
        assert cbc.get("X-EUR") is None
        assert cbc.remove("X-EUR") is False


class TestRestoreInto:
    def test_no_entry_no_op(self, cbc):
        trade = {"market": "FOO-EUR", "buy_price": 0, "invested_eur": 0}
        assert cbc.restore_into("FOO-EUR", trade) is False
        assert trade["buy_price"] == 0

    def test_restores_when_unset(self, cbc):
        cbc.set("NOT-EUR", buy_price=0.0004307, invested_eur=617.97)
        trade = {"market": "NOT-EUR", "buy_price": 0, "invested_eur": 0}
        assert cbc.restore_into("NOT-EUR", trade) is True
        assert trade["buy_price"] == pytest.approx(0.0004307)
        assert trade["invested_eur"] == pytest.approx(617.97)
        assert trade["initial_invested_eur"] == pytest.approx(617.97)
        assert trade["_cost_basis_restored_from_cache"] is True

    def test_does_not_overwrite_valid(self, cbc):
        """If the trade already has good cost basis, do NOT clobber it."""
        cbc.set("NOT-EUR", buy_price=0.0004307, invested_eur=617.97)
        trade = {
            "market": "NOT-EUR",
            "buy_price": 0.0005,
            "invested_eur": 800.0,
            "initial_invested_eur": 800.0,
        }
        assert cbc.restore_into("NOT-EUR", trade) is False
        assert trade["buy_price"] == pytest.approx(0.0005)
        assert trade["invested_eur"] == pytest.approx(800.0)

    def test_preserves_higher_highest_price(self, cbc):
        """Trailing high-water mark must not be lowered by cache restore."""
        cbc.set("RENDER-EUR", buy_price=1.5738, invested_eur=309.72)
        trade = {
            "market": "RENDER-EUR",
            "buy_price": 0,
            "invested_eur": 0,
            "highest_price": 1.6022,  # trailing high — must keep
        }
        cbc.restore_into("RENDER-EUR", trade)
        assert trade["highest_price"] == pytest.approx(1.6022)

    def test_zero_buy_price_in_cache_skipped(self, cbc):
        """Don't restore zero/garbage values."""
        cbc.set("BAD-EUR", buy_price=0, invested_eur=0)
        trade = {"market": "BAD-EUR", "buy_price": 0, "invested_eur": 0}
        assert cbc.restore_into("BAD-EUR", trade) is False
