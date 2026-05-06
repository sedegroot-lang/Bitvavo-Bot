"""Tests for backtest.replay_engine, backtest.ab_runner and core.portfolio_optimizer."""
from __future__ import annotations

import math
import random

import pytest

from backtest.replay_engine import ReplayConfig, run_replay, _candle_ts
from backtest.ab_runner import run_ab
from core.portfolio_optimizer import (
    CandidateMarket,
    HeldPosition,
    compute_portfolio_weights,
)


# ---------- Synthetic data ----------

def _flat_candles(n: int = 200, price: float = 100.0) -> list[list[float]]:
    """Sideways market — should generate few or no trades depending on signals."""
    return [[i * 60_000, price, price, price, price, 1000.0] for i in range(n)]


def _trend_up_candles(n: int = 300, start: float = 100.0, step_pct: float = 0.002) -> list[list[float]]:
    """Steady uptrend; high/low pinned around close to keep trailing realistic."""
    out = []
    p = start
    for i in range(n):
        prev = p
        p = prev * (1 + step_pct)
        high = max(prev, p) * 1.001
        low = min(prev, p) * 0.999
        out.append([i * 60_000, prev, high, low, p, 1000.0])
    return out


def _spike_then_dump(n_up: int = 60, n_down: int = 60, start: float = 100.0) -> list[list[float]]:
    """Pump then crash — exercises trailing exit + stop-loss."""
    out = []
    p = start
    for i in range(n_up):
        prev = p
        p = prev * 1.01  # +1% per bar
        out.append([i * 60_000, prev, p * 1.002, prev * 0.998, p, 1000.0])
    base_idx = n_up
    for i in range(n_down):
        prev = p
        p = prev * 0.99  # -1% per bar
        out.append([(base_idx + i) * 60_000, prev, prev * 1.002, p * 0.998, p, 1000.0])
    return out


# ---------- replay_engine ----------

class TestReplayEngine:
    def test_returns_empty_result_for_short_input(self):
        r = run_replay("X-EUR", _flat_candles(10), ReplayConfig())
        assert r.n_trades == 0
        assert r.pnl_eur == 0.0
        assert r.equity_curve == []

    def test_no_trades_when_score_threshold_unreachable(self):
        # MIN_SCORE huge → no entries
        r = run_replay("X-EUR", _trend_up_candles(200), ReplayConfig(min_score=1e6))
        assert r.n_trades == 0
        assert r.pnl_eur == 0.0

    def test_trade_lifecycle_on_pump_dump(self):
        # MIN_SCORE 0 makes any candle trigger an entry — proves the
        # entry/exit/trailing/PnL plumbing works end-to-end.
        candles = _spike_then_dump(60, 60)
        cfg = ReplayConfig(
            min_score=0.0,
            base_invest_eur=100.0,
            warmup_candles=10,
            trailing_activation_pct=0.005,
            trailing_pct=0.01,
            stop_loss_pct=0.10,
            max_hold_bars=200,
        )
        r = run_replay("PUMPDUMP-EUR", candles, cfg)
        assert r.n_trades >= 1
        assert r.equity_curve, "equity curve must be populated"
        # First trade should have an exit reason recorded
        first = r.trades[0]
        assert first.exit_reason in {"trailing_stop", "stop_loss", "max_hold", "end_of_data"}
        # Sanity: PnL must equal sum of trade PnLs
        assert r.pnl_eur == pytest.approx(sum(t.pnl_eur for t in r.trades), abs=0.01)

    def test_summary_string_contains_market(self):
        r = run_replay("ABC-EUR", _flat_candles(200), ReplayConfig(min_score=1e6))
        s = r.summary()
        assert "ABC-EUR" in s
        assert "Trades" in s

    def test_candle_ts_normalises_ms(self):
        assert _candle_ts([1700000000000, 1, 1, 1, 1, 0]) == pytest.approx(1700000000.0)
        assert _candle_ts([1700000000.0, 1, 1, 1, 1, 0]) == pytest.approx(1700000000.0)


# ---------- ab_runner ----------

class TestAbRunner:
    def test_ab_runs_both_configs_and_reports_delta(self):
        candles = _trend_up_candles(200)
        base = ReplayConfig(min_score=1e6)        # never trade
        chal = ReplayConfig(min_score=0.0, warmup_candles=10)  # always trade
        ab = run_ab("X-EUR", candles, base, chal)
        assert ab.base.n_trades == 0
        assert ab.challenger.n_trades >= 1
        assert ab.trades_delta == ab.challenger.n_trades - ab.base.n_trades
        s = ab.summary()
        assert "BASE" in s and "CHALLENGER" in s


# ---------- portfolio_optimizer ----------

class TestPortfolioOptimizer:
    def test_empty_inputs_return_empty(self):
        out = compute_portfolio_weights([], budget_eur=1000.0)
        assert out.weights == {} and out.eur == {}

    def test_zero_budget_returns_empty(self):
        cands = [CandidateMarket("BTC-EUR", 0.5, 0.02)]
        out = compute_portfolio_weights(cands, budget_eur=0.0)
        assert out.weights == {} and out.eur == {}

    def test_split_two_uncorrelated(self):
        cands = [
            CandidateMarket("BTC-EUR", 0.4, 0.02),
            CandidateMarket("ETH-EUR", 0.4, 0.02),
        ]
        out = compute_portfolio_weights(cands, budget_eur=1000.0,
                                        risk_cap=1.0, max_weight_per_market=1.0)
        # Symmetric inputs → symmetric weights
        assert out.weights["BTC-EUR"] == pytest.approx(out.weights["ETH-EUR"], rel=1e-6)
        assert sum(out.weights.values()) == pytest.approx(1.0, abs=1e-6)
        assert sum(out.eur.values()) == pytest.approx(1000.0, abs=0.5)

    def test_correlation_aversion_redirects_to_uncorrelated(self):
        # AAA & BBB are highly correlated, CCC is independent.
        cands = [
            CandidateMarket("AAA-EUR", 0.4, 0.02),
            CandidateMarket("BBB-EUR", 0.4, 0.02),
            CandidateMarket("CCC-EUR", 0.4, 0.02),
        ]
        corr = {("AAA-EUR", "BBB-EUR"): 0.95}
        out = compute_portfolio_weights(
            cands, budget_eur=1000.0, correlation=corr,
            correlation_aversion=1.0, risk_cap=1.0, max_weight_per_market=1.0,
        )
        # CCC must end up with strictly more weight than AAA or BBB
        assert out.weights["CCC-EUR"] > out.weights["AAA-EUR"]
        assert out.weights["CCC-EUR"] > out.weights["BBB-EUR"]

    def test_risk_cap_constrains_allocation(self):
        cands = [CandidateMarket("HIGHVOL-EUR", 0.5, 0.10)]  # 10% vol
        out = compute_portfolio_weights(
            cands, budget_eur=1000.0, risk_cap=0.05,
            max_weight_per_market=1.0,
        )
        # Only enough budget can be deployed so that w·vol ≤ 0.05
        deployed = out.weights.get("HIGHVOL-EUR", 0.0)
        assert deployed * 0.10 <= 0.05 + 1e-9

    def test_held_position_eats_into_budget(self):
        cands = [CandidateMarket("BTC-EUR", 0.5, 0.10)]
        held = [HeldPosition("ETH-EUR", weight=0.4, volatility=0.10)]  # uses 0.04 risk
        out = compute_portfolio_weights(
            cands, held=held, budget_eur=1000.0,
            risk_cap=0.05, max_weight_per_market=1.0,
        )
        # Only ~0.01 risk headroom left → tiny weight
        deployed = out.weights.get("BTC-EUR", 0.0)
        assert deployed * 0.10 <= 0.011

    def test_min_position_filter_redistributes(self):
        # Two candidates, but per-market cap forces small slices.
        cands = [
            CandidateMarket("AAA-EUR", 0.5, 0.01),
            CandidateMarket("BBB-EUR", 0.5, 0.01),
        ]
        out = compute_portfolio_weights(
            cands, budget_eur=20.0,  # tiny budget
            risk_cap=1.0, max_weight_per_market=0.5, min_eur_per_position=15.0,
        )
        # Each market provisionally gets €10 — both below €15 floor
        # → both skipped, nothing left
        assert out.eur == {}
        assert len(out.skipped) == 2
