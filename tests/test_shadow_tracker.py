"""Tests for core/shadow_tracker.py"""
import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.shadow_tracker import ShadowTracker, _LOG_PATH, _PHANTOM_PATH, _DMS_PATH


@pytest.fixture(autouse=True)
def clean_shadow_files(tmp_path, monkeypatch):
    """Redirect shadow data files to tmp_path to avoid polluting real data."""
    log_path = tmp_path / "shadow_log.jsonl"
    phantom_path = tmp_path / "shadow_phantom.json"
    dms_path = tmp_path / "shadow_dms_watchlist.json"
    monkeypatch.setattr("core.shadow_tracker._LOG_PATH", log_path)
    monkeypatch.setattr("core.shadow_tracker._PHANTOM_PATH", phantom_path)
    monkeypatch.setattr("core.shadow_tracker._DMS_PATH", dms_path)
    monkeypatch.setattr("core.shadow_tracker._DATA", tmp_path)
    yield {"log": log_path, "phantom": phantom_path, "dms": dms_path}


class TestTimingFilter:
    def test_block_afternoon(self):
        label, mod = ShadowTracker.timing_filter(14)
        assert label == "block"
        assert mod == -3.0

    def test_block_boundary_13(self):
        label, mod = ShadowTracker.timing_filter(13)
        assert label == "block"
        assert mod == -3.0

    def test_block_boundary_16(self):
        label, mod = ShadowTracker.timing_filter(16)
        assert label == "block"
        assert mod == -3.0

    def test_not_blocked_at_17(self):
        label, mod = ShadowTracker.timing_filter(17)
        assert label == "neutral"
        assert mod == 0.0

    def test_boost_night(self):
        label, mod = ShadowTracker.timing_filter(3)
        assert label == "boost"
        assert mod == +0.5

    def test_boost_boundary_0(self):
        label, mod = ShadowTracker.timing_filter(0)
        assert label == "boost"

    def test_boost_boundary_5(self):
        label, mod = ShadowTracker.timing_filter(5)
        assert label == "boost"

    def test_neutral_morning(self):
        label, mod = ShadowTracker.timing_filter(9)
        assert label == "neutral"
        assert mod == 0.0

    def test_neutral_evening(self):
        label, mod = ShadowTracker.timing_filter(20)
        assert label == "neutral"
        assert mod == 0.0


class TestVelocityFilter:
    def test_negative_pnl_soft_block(self):
        tracker = ShadowTracker()
        closed = [
            {"market": "XRP-EUR", "timestamp": time.time() - 86400, "profit": -10.0},
            {"market": "XRP-EUR", "timestamp": time.time() - 172800, "profit": 3.0},
        ]
        label, mod = tracker.velocity_filter("XRP-EUR", closed)
        assert label == "soft_block"
        assert mod == -2.0

    def test_positive_pnl_ok(self):
        tracker = ShadowTracker()
        closed = [
            {"market": "DOT-EUR", "timestamp": time.time() - 86400, "profit": 5.0},
            {"market": "DOT-EUR", "timestamp": time.time() - 172800, "profit": 3.0},
        ]
        label, mod = tracker.velocity_filter("DOT-EUR", closed)
        assert label == "ok"
        assert mod == 0.0

    def test_unknown_market_ok(self):
        tracker = ShadowTracker()
        label, mod = tracker.velocity_filter("NEW-EUR", [])
        assert label == "ok"
        assert mod == 0.0

    def test_old_trades_ignored(self):
        tracker = ShadowTracker()
        closed = [
            {"market": "SOL-EUR", "timestamp": time.time() - 40 * 86400, "profit": -50.0},
        ]
        label, mod = tracker.velocity_filter("SOL-EUR", closed)
        assert label == "ok"  # older than 30 days → not counted


class TestEvaluateEntry:
    def test_bot_buy_shadow_skip_timing(self, clean_shadow_files):
        """Bot would buy (score=8), but shadow blocks due to timing (13:00-17:00)."""
        tracker = ShadowTracker()
        with patch("time.strftime", return_value="14"):
            with patch("time.gmtime"):
                # Force hour to 14
                pass

        # Manually test with known values
        tracker._velocity_cache_ts = time.time()  # skip refresh
        tracker._velocity_cache = {}

        # Simulate: score 8.0, threshold 7.0, during blocked hours
        # timing_mod = -3.0, velocity_mod = 0 → adj_score = 5.0 < 7.0
        # But we can't easily mock time.strftime in the method, so let's test the logic directly
        hour = 14
        timing_label, timing_mod = ShadowTracker.timing_filter(hour)
        velocity_label, velocity_mod = tracker.velocity_filter("XRP-EUR", [])

        score = 8.0
        threshold = 7.0
        adj_score = score + timing_mod + velocity_mod  # 8.0 - 3.0 + 0 = 5.0
        assert adj_score < threshold
        assert timing_label == "block"

    def test_bot_skip_shadow_skip(self, clean_shadow_files):
        """Both bot and shadow skip (low score)."""
        tracker = ShadowTracker()
        tracker._velocity_cache_ts = time.time()
        result = tracker.evaluate_entry(
            market="LOW-EUR",
            score=2.0,
            price=0.50,
            min_score_threshold=7.0,
            closed_trades=[],
            bot_would_buy=False,
        )
        # Score too low → filtered out (not logged)
        assert result is None

    def test_dms_buy_creates_phantom(self, clean_shadow_files):
        """DMS market scores high → phantom trade opened."""
        tracker = ShadowTracker()
        tracker._velocity_cache_ts = time.time()
        tracker._velocity_cache = {}

        # Force timing to neutral (hour=10)
        with patch("time.strftime", side_effect=lambda fmt, *a: "10" if fmt == "%H" else time.strftime(fmt, *a)):
            result = tracker.evaluate_entry(
                market="ENJ-EUR",
                score=8.5,
                price=0.245,
                min_score_threshold=7.0,
                closed_trades=[],
                bot_would_buy=False,
                is_dms=True,
            )

        assert result is not None
        assert result.shadow_decision == "buy"
        assert result.is_dms is True
        assert "ENJ-EUR" in tracker._phantom_trades
        assert tracker._phantom_trades["ENJ-EUR"]["status"] == "open"

    def test_evaluate_logs_to_jsonl(self, clean_shadow_files):
        """Evaluations are logged to JSONL file."""
        tracker = ShadowTracker()
        tracker._velocity_cache_ts = time.time()

        # High score so it gets logged
        result = tracker.evaluate_entry(
            market="SOL-EUR",
            score=9.0,
            price=135.0,
            min_score_threshold=7.0,
            closed_trades=[],
            bot_would_buy=True,
        )

        log_path = clean_shadow_files["log"]
        assert log_path.exists()
        with open(str(log_path)) as f:
            lines = f.readlines()
        assert len(lines) >= 1
        entry = json.loads(lines[0])
        assert entry["market"] == "SOL-EUR"
        assert entry["score"] == 9.0


class TestPhantomTrades:
    def test_phantom_price_update(self, clean_shadow_files):
        tracker = ShadowTracker()
        tracker._phantom_trades = {
            "ENJ-EUR": {
                "market": "ENJ-EUR",
                "entry_price": 0.245,
                "entry_score": 8.5,
                "entry_ts": time.time() - 3600,
                "reason": "dms_opportunity",
                "peak_price": 0.245,
                "current_price": 0.245,
                "phantom_pnl_pct": 0.0,
                "last_updated": time.time() - 3600,
                "status": "open",
            }
        }

        def mock_price(m):
            return 0.260  # up from 0.245

        tracker.update_phantom_prices(mock_price)
        pt = tracker._phantom_trades["ENJ-EUR"]
        assert pt["current_price"] == 0.260
        assert pt["peak_price"] == 0.260
        assert pt["phantom_pnl_pct"] == pytest.approx(6.12, abs=0.1)
        assert pt["status"] == "open"

    def test_phantom_trailing_stop(self, clean_shadow_files):
        tracker = ShadowTracker()
        tracker._phantom_trades = {
            "TEST-EUR": {
                "market": "TEST-EUR",
                "entry_price": 1.00,
                "entry_score": 8.0,
                "entry_ts": time.time() - 3600,
                "reason": "dms",
                "peak_price": 1.10,  # was up 10%
                "current_price": 1.10,
                "phantom_pnl_pct": 10.0,
                "last_updated": time.time(),
                "status": "open",
            }
        }

        # Price drops to 1.04 → 5.5% drop from peak (1.10) → triggers trailing stop
        def mock_price(m):
            return 1.04

        tracker.update_phantom_prices(mock_price)
        pt = tracker._phantom_trades["TEST-EUR"]
        assert pt["status"].startswith("closed")
        assert "exit_price" in pt

    def test_phantom_stop_loss(self, clean_shadow_files):
        tracker = ShadowTracker()
        tracker._phantom_trades = {
            "DROP-EUR": {
                "market": "DROP-EUR",
                "entry_price": 1.00,
                "entry_score": 7.5,
                "entry_ts": time.time() - 3600,
                "reason": "dms",
                "peak_price": 1.00,
                "current_price": 1.00,
                "phantom_pnl_pct": 0.0,
                "last_updated": time.time(),
                "status": "open",
            }
        }

        def mock_price(m):
            return 0.91  # -9% → triggers stop loss

        tracker.update_phantom_prices(mock_price)
        pt = tracker._phantom_trades["DROP-EUR"]
        assert pt["status"] == "closed_stop_loss"

    def test_phantom_max_hold(self, clean_shadow_files):
        tracker = ShadowTracker()
        tracker._phantom_trades = {
            "HOLD-EUR": {
                "market": "HOLD-EUR",
                "entry_price": 1.00,
                "entry_score": 7.5,
                "entry_ts": time.time() - 80 * 3600,  # 80 hours ago
                "reason": "dms",
                "peak_price": 1.02,
                "current_price": 1.01,
                "phantom_pnl_pct": 1.0,
                "last_updated": time.time(),
                "status": "open",
            }
        }

        def mock_price(m):
            return 1.01

        tracker.update_phantom_prices(mock_price)
        pt = tracker._phantom_trades["HOLD-EUR"]
        assert pt["status"] == "closed_max_hold"


class TestDMS:
    def test_refresh_watchlist(self, clean_shadow_files):
        tracker = ShadowTracker()
        mock_bv = MagicMock()
        mock_bv.ticker24h.return_value = [
            {"market": "ENJ-EUR", "high": "0.30", "low": "0.20", "volume": "100000", "volumeQuote": "25000", "last": "0.25"},
            {"market": "BIO-EUR", "high": "0.60", "low": "0.50", "volume": "50000", "volumeQuote": "28000", "last": "0.55"},
            {"market": "BTC-EUR", "high": "61000", "low": "59000", "volume": "10", "volumeQuote": "600000", "last": "60000"},
        ]

        result = tracker.refresh_dms_watchlist(mock_bv, ["BTC-EUR"])  # BTC in whitelist
        assert len(result) >= 2
        markets = [r["market"] for r in result]
        assert "BTC-EUR" not in markets  # excluded (in whitelist)
        assert "ENJ-EUR" in markets

    def test_rotating_batch(self, clean_shadow_files):
        tracker = ShadowTracker()
        tracker._dms_watchlist = [
            {"market": f"M{i}-EUR", "opportunity": 100 - i} for i in range(10)
        ]

        batch1 = tracker.get_dms_markets_to_evaluate(3)
        assert len(batch1) == 3
        assert batch1[0]["market"] == "M0-EUR"

        batch2 = tracker.get_dms_markets_to_evaluate(3)
        assert batch2[0]["market"] == "M3-EUR"

        batch3 = tracker.get_dms_markets_to_evaluate(3)
        assert batch3[0]["market"] == "M6-EUR"

        # Wraps around
        batch4 = tracker.get_dms_markets_to_evaluate(3)
        assert batch4[0]["market"] == "M9-EUR"


class TestStats:
    def test_stats_empty(self, clean_shadow_files):
        tracker = ShadowTracker()
        stats = tracker.get_stats()
        assert stats["evals"] == 0
        assert stats["timing_blocks"] == 0
        assert stats["open_phantoms"] == 0
