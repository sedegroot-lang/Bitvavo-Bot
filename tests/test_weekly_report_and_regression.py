"""Tests for bot.weekly_report and bot.regression_alerter."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import bot.weekly_report as wr
import bot.regression_alerter as ra


def _trade(market: str, profit: float, ts: float, **extra) -> dict:
    return {
        "market": market,
        "profit": profit,
        "archived_at": ts,
        "buy_price": 1.0,
        "sell_price": 1.0 + profit / 100,
        "amount": 100.0,
        "reason": extra.pop("reason", "trailing_tp"),
        "profit_calculated": profit - 0.5,  # fee proxy
        **extra,
    }


# ---------- weekly_report ----------

class TestWeeklyReport:
    def test_empty_archive(self):
        r = wr.compute_report([])
        assert r["current"]["trades"] == 0
        assert r["current"]["pnl_eur"] == 0.0
        assert r["delta"]["pnl_eur"] == 0.0

    def test_window_filtering_and_aggregation(self):
        now = time.time()
        trades = [
            _trade("BTC-EUR", 10.0, now - 3 * 86400),       # current week win
            _trade("ETH-EUR", -2.0, now - 5 * 86400),        # current week loss
            _trade("ADA-EUR", 5.0, now - 9 * 86400),         # previous week
            _trade("SOL-EUR", 99.0, now - 30 * 86400),       # too old
        ]
        r = wr.compute_report(trades, end_ts=now)
        assert r["current"]["trades"] == 2
        assert r["current"]["pnl_eur"] == pytest.approx(8.0, rel=0, abs=0.01)
        assert r["current"]["wins"] == 1
        assert r["current"]["losses"] == 1
        assert r["current"]["win_rate"] == 50.0
        assert r["previous"]["trades"] == 1
        assert r["previous"]["pnl_eur"] == pytest.approx(5.0, abs=0.01)
        assert r["delta"]["pnl_eur"] == pytest.approx(3.0, abs=0.01)
        assert r["current"]["best"]["market"] == "BTC-EUR"
        assert r["current"]["worst"]["market"] == "ETH-EUR"

    def test_per_market_sorted(self):
        now = time.time()
        trades = [
            _trade("AAA-EUR", 1.0, now - 1 * 86400),
            _trade("BBB-EUR", 5.0, now - 1 * 86400),
            _trade("BBB-EUR", 2.0, now - 2 * 86400),
        ]
        r = wr.compute_report(trades, end_ts=now)
        assert r["per_market"][0]["market"] == "BBB-EUR"
        assert r["per_market"][0]["trades"] == 2
        assert r["per_market"][0]["pnl"] == pytest.approx(7.0, abs=0.01)

    def test_format_telegram_contains_pnl_and_period(self):
        now = time.time()
        trades = [_trade("BTC-EUR", 12.34, now - 1 * 86400)]
        r = wr.compute_report(trades, end_ts=now)
        msg = wr.format_telegram(r)
        assert "WEEKLY REPORT" in msg
        assert "+12.34" in msg
        assert "BTC-EUR" in msg

    def test_write_snapshot_atomic(self, tmp_path, monkeypatch):
        monkeypatch.setattr(wr, "REPORT_DIR", tmp_path)
        monkeypatch.setattr(wr, "LAST_SENT", tmp_path / ".last_sent")
        now = time.time()
        r = wr.compute_report([_trade("X-EUR", 1.0, now - 1 * 86400)], end_ts=now)
        path = wr.write_snapshot(r)
        assert path.exists()
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["period"]["iso_week"] == r["period"]["iso_week"]


# ---------- regression_alerter ----------

class TestRegressionAlerter:
    def _patch_archive(self, monkeypatch, trades):
        monkeypatch.setattr(ra, "_load_trades", lambda: list(trades))

    def test_skipped_when_too_few_trades(self, monkeypatch):
        self._patch_archive(monkeypatch, [_trade("X", 1.0, time.time() - i) for i in range(3)])
        r = ra.evaluate()
        assert r["skipped"] is True

    def test_healthy_when_all_wins(self, monkeypatch):
        now = time.time()
        trades = [_trade("X", 1.0, now - i) for i in range(20)]
        self._patch_archive(monkeypatch, trades)
        r = ra.evaluate()
        assert r["ok"] is True
        assert r["win_rate"] == 1.0
        assert r["loss_streak"] == 0
        assert r["breaches"] == []

    def test_breaches_low_winrate(self, monkeypatch):
        now = time.time()
        # 12 losses + 8 wins out of 20 = 40% win rate
        trades = [_trade("X", -1.0, now - 100 - i) for i in range(12)] + \
                 [_trade("X", 1.0, now - i) for i in range(8)]
        self._patch_archive(monkeypatch, trades)
        r = ra.evaluate()
        assert r["ok"] is False
        assert any("win_rate" in b for b in r["breaches"])

    def test_breaches_loss_streak(self, monkeypatch):
        now = time.time()
        wins = [_trade("X", 5.0, now - 100 - i) for i in range(15)]
        losses_tail = [_trade("X", -1.0, now - i) for i in range(5)]
        self._patch_archive(monkeypatch, wins + losses_tail)
        r = ra.evaluate()
        assert r["loss_streak"] == 5
        assert any("loss_streak" in b for b in r["breaches"])

    def test_throttle_blocks_repeat_alert(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ra, "STATE_FILE", tmp_path / "state.json")
        now = time.time()
        # Force a breach
        trades = [_trade("X", -5.0, now - i) for i in range(20)]
        self._patch_archive(monkeypatch, trades)
        sent_calls = []
        # Mock notifier import target
        import sys
        import types
        fake = types.ModuleType("notifier")
        fake.send_telegram = lambda msg: sent_calls.append(msg)  # type: ignore
        monkeypatch.setitem(sys.modules, "notifier", fake)

        r1, s1 = ra.run(force=False, dry=False)
        assert s1 is True
        assert len(sent_calls) == 1

        # Second call within throttle window — must be blocked
        r2, s2 = ra.run(force=False, dry=False)
        assert s2 is False
        assert r2.get("throttled") is True
        assert len(sent_calls) == 1
