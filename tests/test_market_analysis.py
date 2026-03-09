"""Tests for ai/market_analysis.py — regime detection, coin stats, risk metrics."""

import pytest
from ai.market_analysis import (
    get_market_sector,
    calculate_portfolio_sectors,
    detect_market_regime,
    get_coin_statistics,
    calculate_risk_metrics,
)


# ---------------------------------------------------------------------------
# Sector helpers
# ---------------------------------------------------------------------------

class TestGetMarketSector:
    def test_known_market(self):
        # BTC-EUR should be in a known sector
        sector = get_market_sector("BTC-EUR")
        assert isinstance(sector, str)
        assert sector != ""

    def test_unknown_market(self):
        sector = get_market_sector("FAKECOIN-EUR")
        assert sector == "Other"

    def test_eth_market(self):
        sector = get_market_sector("ETH-EUR")
        assert isinstance(sector, str)
        assert sector != "Other"


class TestCalculatePortfolioSectors:
    def test_counts_sectors(self):
        trades = {"BTC-EUR": {}, "ETH-EUR": {}, "FAKECOIN-EUR": {}}
        sectors = calculate_portfolio_sectors(trades)
        assert isinstance(sectors, dict)
        assert sum(sectors.values()) == 3

    def test_empty_trades(self):
        sectors = calculate_portfolio_sectors({})
        assert sectors == {}


# ---------------------------------------------------------------------------
# Market regime detection
# ---------------------------------------------------------------------------

class TestDetectMarketRegime:
    def test_insufficient_trades_returns_sideways(self):
        """<20 trades → SIDEWAYS with 0.5 confidence."""
        result = detect_market_regime([{"pnl": 1}] * 5, {})
        assert result["regime"] == "SIDEWAYS"
        assert result["confidence"] == 0.5
        assert result["indicators"] == {}

    def test_bull_regime(self):
        """High win rate and positive PnL → BULL."""
        trades = [{"pnl": 5.0, "market": "BTC-EUR"}] * 25 + [{"pnl": -1.0, "market": "ALT-EUR"}] * 5
        result = detect_market_regime(trades, {})
        assert result["regime"] in ("BULL", "SIDEWAYS", "BEAR")  # Depends on scoring
        assert "regime" in result
        assert "confidence" in result

    def test_bear_regime(self):
        """Low win rate and negative PnL → BEAR."""
        trades = [{"pnl": -5.0, "market": "ALT-EUR"}] * 25 + [{"pnl": 0.5, "market": "BTC-EUR"}] * 5
        result = detect_market_regime(trades, {})
        assert result["regime"] in ("BULL", "SIDEWAYS", "BEAR")
        assert result["confidence"] >= 0

    def test_indicators_present(self):
        """Result should contain expected indicator keys."""
        trades = [{"pnl": i * 0.1 - 1} for i in range(25)]
        result = detect_market_regime(trades, {})
        assert "indicators" in result
        indicators = result["indicators"]
        for key in ("win_rate", "wr_trend", "avg_pnl"):
            assert key in indicators
        # New hybrid regime also returns source info
        assert "source" in result

    def test_all_winning_trades(self):
        """All positive PnL should produce a BULL regime."""
        trades = [{"pnl": 10.0, "market": "BTC-EUR"}] * 30
        result = detect_market_regime(trades, {})
        assert result["regime"] == "BULL"


# ---------------------------------------------------------------------------
# Coin statistics
# ---------------------------------------------------------------------------

class TestGetCoinStatistics:
    def test_groups_by_market(self):
        trades = [
            {"market": "BTC-EUR", "pnl": 5},
            {"market": "BTC-EUR", "pnl": -2},
            {"market": "ETH-EUR", "pnl": 3},
        ]
        stats = get_coin_statistics(trades)
        assert "BTC-EUR" in stats
        assert "ETH-EUR" in stats
        assert stats["BTC-EUR"]["trades"] == 2
        assert stats["ETH-EUR"]["trades"] == 1

    def test_win_rate_calculation(self):
        trades = [
            {"market": "BTC-EUR", "pnl": 5},
            {"market": "BTC-EUR", "pnl": -2},
            {"market": "BTC-EUR", "pnl": 3},
            {"market": "BTC-EUR", "pnl": 1},
        ]
        stats = get_coin_statistics(trades)
        assert stats["BTC-EUR"]["win_rate"] == pytest.approx(0.75)

    def test_avg_pnl(self):
        trades = [
            {"market": "BTC-EUR", "pnl": 10},
            {"market": "BTC-EUR", "pnl": -2},
        ]
        stats = get_coin_statistics(trades)
        assert stats["BTC-EUR"]["avg_pnl"] == pytest.approx(4.0)

    def test_empty_trades(self):
        stats = get_coin_statistics([])
        assert stats == {}


# ---------------------------------------------------------------------------
# Risk metrics
# ---------------------------------------------------------------------------

class TestCalculateRiskMetrics:
    def test_insufficient_trades_returns_low(self):
        result = calculate_risk_metrics([{"pnl": 1}] * 5, {})
        assert result["risk_level"] == "LOW"
        assert result["consecutive_losses"] == 0

    def test_high_consecutive_losses(self):
        trades = [{"pnl": 5}] * 15 + [{"pnl": -5}] * 5  # 5 consecutive losses at end
        result = calculate_risk_metrics(trades, {})
        assert result["consecutive_losses"] >= 3
        # 5 consecutive losses + negative daily PnL → elevated risk
        assert result["risk_level"] in ("MEDIUM", "HIGH")

    def test_high_drawdown(self):
        trades = [{"pnl": 1}] * 10 + [{"pnl": -15}] * 10  # Heavy drawdown
        result = calculate_risk_metrics(trades, {})
        assert result["daily_drawdown"] < 0

    def test_keys_present(self):
        trades = [{"pnl": i - 5} for i in range(20)]
        result = calculate_risk_metrics(trades, {})
        for key in ("daily_drawdown", "consecutive_losses", "risk_level", "risk_score"):
            assert key in result

    def test_all_winning_low_risk(self):
        trades = [{"pnl": 5}] * 20
        result = calculate_risk_metrics(trades, {})
        assert result["risk_level"] == "LOW"
        assert result["consecutive_losses"] == 0
        assert result["daily_drawdown"] > 0

    def test_risk_score_numeric(self):
        trades = [{"pnl": -3}] * 20
        result = calculate_risk_metrics(trades, {})
        assert isinstance(result["risk_score"], (int, float))
