"""Tests for scripts/cold_tier_scanner.py — pure-logic tests (no API)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from scripts import cold_tier_scanner as cts  # noqa: E402


def _t(market: str, vol: float, change: float, price: float = 1.0):
    return {"market": market, "volume_eur": vol, "change_24h_pct": change, "price": price}


class TestScoring:
    def test_high_volume_high_momentum_scores_high(self):
        s_hi = cts.score_candidate(_t("A-EUR", 10_000_000, 10.0))
        s_lo = cts.score_candidate(_t("B-EUR", 1_000_000, 1.0))
        assert s_hi > s_lo

    def test_extreme_dump_penalised(self):
        # 10% move vs 50% dump: 50% should NOT score way higher despite |momentum|
        s_normal = cts.score_candidate(_t("X-EUR", 5_000_000, 10.0))
        s_dump = cts.score_candidate(_t("Y-EUR", 5_000_000, -50.0))
        # dump has much bigger raw momentum but heavy penalty, should not 2x normal
        assert s_dump < s_normal * 2

    def test_below_volume_floor_heavily_penalised(self):
        s_above = cts.score_candidate(_t("A-EUR", 800_000, 5.0))
        s_below = cts.score_candidate(_t("B-EUR", 100_000, 5.0))
        assert s_above > s_below + 4  # liq_pen of 5

    def test_zero_change_only_liquidity(self):
        s = cts.score_candidate(_t("A-EUR", 1_000_000, 0.0))
        # log10(1e6) = 6, no momentum, no penalty
        assert 5.5 <= s <= 6.5


class TestRanking:
    def test_excluded_filtered_out(self):
        tickers = [_t("A-EUR", 2_000_000, 10), _t("B-EUR", 2_000_000, 5)]
        ranked = cts.rank_candidates(tickers, excluded={"A-EUR"})
        assert [r["market"] for r in ranked] == ["B-EUR"]

    def test_volume_floor_applied(self):
        tickers = [_t("A-EUR", 100_000, 50), _t("B-EUR", 1_000_000, 1)]
        ranked = cts.rank_candidates(tickers, excluded=set())
        assert [r["market"] for r in ranked] == ["B-EUR"]

    def test_sorted_descending_by_score(self):
        tickers = [
            _t("LOW-EUR", 800_000, 1),
            _t("HI-EUR", 5_000_000, 15),
            _t("MID-EUR", 2_000_000, 5),
        ]
        ranked = cts.rank_candidates(tickers, excluded=set())
        scores = [r["score"] for r in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_empty_ticker_list(self):
        assert cts.rank_candidates([], excluded=set()) == []


class TestApplyTopN:
    def test_apply_appends_only_new(self, tmp_path, monkeypatch):
        local = tmp_path / "bot_config_local.json"
        local.write_text('{"WATCHLIST_MARKETS": ["EXISTING-EUR"]}', encoding="utf-8")
        monkeypatch.setattr(cts, "LOCAL_CONFIG", local)

        ranked = [
            _t("EXISTING-EUR", 5_000_000, 10),
            _t("NEW1-EUR", 5_000_000, 8),
            _t("NEW2-EUR", 5_000_000, 6),
        ]
        added = cts.apply_top_n(ranked, n=2)
        assert added == ["NEW1-EUR", "NEW2-EUR"]

        import json
        cfg = json.loads(local.read_text(encoding="utf-8"))
        assert cfg["WATCHLIST_MARKETS"] == ["EXISTING-EUR", "NEW1-EUR", "NEW2-EUR"]

    def test_apply_respects_n_cap(self, tmp_path, monkeypatch):
        local = tmp_path / "bot_config_local.json"
        local.write_text('{}', encoding="utf-8")
        monkeypatch.setattr(cts, "LOCAL_CONFIG", local)

        ranked = [_t(f"M{i}-EUR", 5_000_000, 5) for i in range(10)]
        added = cts.apply_top_n(ranked, n=3)
        assert len(added) == 3

    def test_apply_no_local_config_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cts, "LOCAL_CONFIG", tmp_path / "missing.json")
        added = cts.apply_top_n([_t("A-EUR", 5_000_000, 5)], n=2)
        assert added == []
