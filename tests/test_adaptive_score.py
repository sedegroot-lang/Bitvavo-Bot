# -*- coding: utf-8 -*-
"""Tests for bot.adaptive_score."""
import pytest
from bot.adaptive_score import AdaptiveScoreThreshold


class TestAdaptiveScore:
    def test_warmup_returns_zero(self):
        a = AdaptiveScoreThreshold()
        a.record_close(1.0)
        delta, reason = a.adjustment(cfg={})
        assert delta == 0.0
        assert 'warmup' in reason

    def test_loss_streak_triggers_strongest_bump(self):
        a = AdaptiveScoreThreshold()
        for _ in range(5):
            a.record_close(1.0)  # baseline winners
        for _ in range(3):
            a.record_close(-1.0)  # 3-loss streak
        delta, reason = a.adjustment(cfg={})
        assert delta == 2.0
        assert 'loss_streak' in reason

    def test_low_wr_bumps_score(self):
        a = AdaptiveScoreThreshold()
        for _ in range(2):
            a.record_close(1.0)
        for _ in range(5):
            a.record_close(-1.0)
        # break the streak with a small win to isolate WR test
        a.record_close(0.1)
        # Still: WR = 3/8 = 37.5% < 50%
        delta, reason = a.adjustment(cfg={})
        # Lookback is 7, so latest 7: 1, -1*5, 0.1 -> wins=2/7=28%
        assert delta == 1.5
        assert 'low' in reason

    def test_high_wr_relaxes_score(self):
        a = AdaptiveScoreThreshold()
        for _ in range(7):
            a.record_close(1.0)
        delta, _ = a.adjustment(cfg={})
        assert delta == -0.5

    def test_normal_wr_no_change(self):
        a = AdaptiveScoreThreshold()
        # 5 wins, 2 losses = 71% (mid-high)
        for p in [1, 1, 1, 1, 1, -1, -1]:
            a.record_close(float(p))
        delta, _ = a.adjustment(cfg={})
        assert delta == 0.0  # 65-80% bracket → no change

    def test_disabled_via_config(self):
        a = AdaptiveScoreThreshold()
        for _ in range(5):
            a.record_close(-1.0)
        delta, _ = a.adjustment(cfg={'ADAPTIVE_SCORE_ENABLED': False})
        assert delta == 0.0

    def test_lookback_window(self):
        a = AdaptiveScoreThreshold(lookback=7)
        # Old losses outside window
        for _ in range(20):
            a.record_close(-1.0)
        # Now flood with wins to push out losses
        for _ in range(7):
            a.record_close(2.0)
        delta, _ = a.adjustment(cfg={})
        assert delta == -0.5  # WR=100% → relax

    def test_stats_populated(self):
        a = AdaptiveScoreThreshold()
        a.record_close(1.0)
        a.record_close(-1.0)
        s = a.stats()
        assert s['n'] == 2
        assert s['rolling_wr'] == 0.5
        assert s['loss_streak'] == 1
