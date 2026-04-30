"""Tests for Road-to-10 #063: exit_pipeline + decorrelation."""
from __future__ import annotations

import pytest

from bot.exit_pipeline import (
    derive_unrealised_pct,
    should_lock_breakeven,
    should_partial_tp,
)
from bot.decorrelation import is_decorrelated, pearson_correlation


class TestExitPipeline:
    def test_unrealised_pct_basic(self):
        assert derive_unrealised_pct(100.0, 110.0) == pytest.approx(10.0)
        assert derive_unrealised_pct(100.0, 90.0) == pytest.approx(-10.0)
        assert derive_unrealised_pct(0, 100) == 0.0

    def test_lock_breakeven_holds_when_no_gain(self):
        d = should_lock_breakeven(market='X', buy_price=100, current_price=99, highest_price=100.5)
        assert d.action == 'hold'
        assert 'not_enough_profit_seen' in d.reason

    def test_lock_breakeven_triggers_after_retrace(self):
        # high was +3%, current dropped to +0.5% (retraced ≥50%)
        d = should_lock_breakeven(market='X', buy_price=100, current_price=100.5, highest_price=103,
                                  activation_pct=1.5, fee_buffer_pct=0.5)
        assert d.action == 'lock_breakeven'
        assert d.new_trailing_pct is not None and d.new_trailing_pct > 0

    def test_lock_breakeven_does_not_sell_at_loss(self):
        # current is below buy → we never recommend lock
        d = should_lock_breakeven(market='X', buy_price=100, current_price=95, highest_price=103)
        assert d.action == 'hold'  # FIX-LOG #003 compliance

    def test_partial_tp_holds_below_target(self):
        d = should_partial_tp(market='X', buy_price=100, current_price=103,
                              partial_already_taken_pct=0, target_pct=5)
        assert d.action == 'hold'

    def test_partial_tp_triggers_at_target(self):
        d = should_partial_tp(market='X', buy_price=100, current_price=106,
                              partial_already_taken_pct=0, target_pct=5, sell_fraction=0.5)
        assert d.action == 'partial_tp'
        assert d.sell_amount_pct == pytest.approx(50.0)

    def test_partial_tp_skips_when_already_taken(self):
        d = should_partial_tp(market='X', buy_price=100, current_price=110,
                              partial_already_taken_pct=50, target_pct=5)
        assert d.action == 'hold'


class TestDecorrelation:
    def test_pearson_perfect_positive(self):
        a = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        b = [2, 4, 6, 8, 10, 12, 14, 16, 18, 20]
        assert pearson_correlation(a, b) == pytest.approx(1.0, abs=1e-9)

    def test_pearson_perfect_negative(self):
        a = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        b = [10, 9, 8, 7, 6, 5, 4, 3, 2, 1]
        assert pearson_correlation(a, b) == pytest.approx(-1.0, abs=1e-9)

    def test_pearson_too_short_returns_none(self):
        assert pearson_correlation([1, 2, 3], [1, 2, 3]) is None

    def test_decorrelated_passes_when_no_open(self):
        ok, corrs = is_decorrelated([100 + i for i in range(20)], {})
        assert ok is True
        assert corrs == {}

    def test_decorrelated_blocks_high_corr(self):
        cand = [100 + i for i in range(30)]
        # near-perfect positive corr
        open_m = {'BTC-EUR': [200 + 2 * i for i in range(30)]}
        ok, corrs = is_decorrelated(cand, open_m, max_corr=0.7)
        assert ok is False
        assert 'BTC-EUR' in corrs
        assert abs(corrs['BTC-EUR']) > 0.7

    def test_decorrelated_passes_low_corr(self):
        import random
        random.seed(42)
        cand = [100 + random.gauss(0, 5) for _ in range(50)]
        other = [200 + random.gauss(0, 5) for _ in range(50)]
        ok, corrs = is_decorrelated(cand, {'X-EUR': other}, max_corr=0.7)
        # noisy random series should have low correlation
        assert ok is True
