# -*- coding: utf-8 -*-
"""Tests for core.market_expectancy."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.market_expectancy import MarketExpectancy


@pytest.fixture
def estimator(tmp_path: Path) -> MarketExpectancy:
    return MarketExpectancy(data_file=tmp_path / "ev.json")


class TestRecordAndStats:
    def test_unseen_market_returns_zero_n(self, estimator: MarketExpectancy):
        ev, n = estimator.stats("XRP-EUR")
        assert n == 0
        assert ev == 0.0

    def test_record_updates_average(self, estimator: MarketExpectancy):
        estimator.record_trade("XRP-EUR", 2.0)
        estimator.record_trade("XRP-EUR", 4.0)
        ev, n = estimator.stats("XRP-EUR")
        assert n == 2
        assert ev == pytest.approx(3.0)


class TestShrinkage:
    def test_unseen_market_uses_global_prior(self, estimator: MarketExpectancy):
        # Seed global with a strong positive EV
        for _ in range(20):
            estimator.record_trade("ALGO-EUR", 5.0)
        # New market with no trades → shrunk_ev equals global EV (5.0)
        shrunk = estimator.shrunk_ev("BRAND-NEW-EUR")
        assert shrunk == pytest.approx(5.0)

    def test_loser_market_blacklisted(self, estimator: MarketExpectancy):
        # 30 losing trades on DOT → far below blacklist threshold (-0.5)
        for _ in range(30):
            estimator.record_trade("DOT-EUR", -3.0)
        assert estimator.size_multiplier("DOT-EUR") == 0.0

    def test_winner_market_boosted(self, estimator: MarketExpectancy):
        for _ in range(30):
            estimator.record_trade("WIF-EUR", 6.0)
        # Add a few low-performing markets so global EV is near zero (winner exception).
        for _ in range(30):
            estimator.record_trade("FILLER-EUR", 0.0)
        mult = estimator.size_multiplier("WIF-EUR")
        assert mult > 1.0
        assert mult <= MarketExpectancy.MAX_MULT

    def test_multiplier_bounded(self, estimator: MarketExpectancy):
        # Mix a winner with low-EV filler so global EV stays modest, allowing
        # the per-market shrunken EV to dominate and hit the MAX_MULT cap.
        for _ in range(50):
            estimator.record_trade("M-EUR", 100.0)  # absurdly profitable
        for _ in range(200):
            estimator.record_trade("FILLER-EUR", 0.5)  # low-EV global anchor
        mult = estimator.size_multiplier("M-EUR")
        assert mult == pytest.approx(MarketExpectancy.MAX_MULT)


class TestPersistence:
    def test_save_and_reload(self, tmp_path: Path):
        path = tmp_path / "ev.json"
        e1 = MarketExpectancy(data_file=path)
        for _ in range(5):
            e1.record_trade("XRP-EUR", 1.0)
        e1.force_save()
        assert path.exists()
        # Reload
        e2 = MarketExpectancy(data_file=path)
        ev, n = e2.stats("XRP-EUR")
        assert n == 5
        assert ev == pytest.approx(1.0)

    def test_snapshot_serializable(self, estimator: MarketExpectancy):
        estimator.record_trade("XRP-EUR", 2.0)
        snap = estimator.snapshot()
        # Must be JSON-serializable
        s = json.dumps(snap)
        assert "XRP-EUR" in s
        assert snap["per_market"]["XRP-EUR"]["n"] == 1
