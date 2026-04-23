# -*- coding: utf-8 -*-
"""Tests for bot.post_loss_cooldown."""
import pytest
from bot.post_loss_cooldown import PostLossCooldown


@pytest.fixture
def cd(tmp_path):
    return PostLossCooldown(persistence_path=tmp_path / "cd.json")


class TestPostLossCooldown:
    def test_no_history_not_blocked(self, cd):
        blocked, _ = cd.is_blocked("SOL-EUR", cfg={})
        assert blocked is False

    def test_after_win_not_blocked(self, cd):
        cd.record_close("SOL-EUR", profit=2.0, ts=1000)
        blocked, reason = cd.is_blocked("SOL-EUR", cfg={}, now=1100)
        assert blocked is False
        assert reason == 'last_was_win'

    def test_after_small_loss_blocked_within_4h(self, cd):
        cd.record_close("SOL-EUR", profit=-1.0, ts=1000)
        blocked, _ = cd.is_blocked("SOL-EUR", cfg={}, now=1000 + 3600)
        assert blocked is True

    def test_after_small_loss_unblocked_after_4h(self, cd):
        cd.record_close("SOL-EUR", profit=-1.0, ts=1000)
        blocked, _ = cd.is_blocked("SOL-EUR", cfg={}, now=1000 + 4 * 3600 + 1)
        assert blocked is False

    def test_after_big_loss_blocked_24h(self, cd):
        cd.record_close("SOL-EUR", profit=-10.0, ts=1000)
        # Past small-loss window but inside big-loss window
        blocked, reason = cd.is_blocked("SOL-EUR", cfg={}, now=1000 + 6 * 3600)
        assert blocked is True
        assert 'big_loss' in reason

    def test_disabled_via_config(self, cd):
        cd.record_close("SOL-EUR", profit=-5.0, ts=1000)
        blocked, _ = cd.is_blocked(
            "SOL-EUR", cfg={'POST_LOSS_COOLDOWN_ENABLED': False}, now=1100
        )
        assert blocked is False

    def test_per_market_isolation(self, cd):
        cd.record_close("SOL-EUR", profit=-2.0, ts=1000)
        blocked_sol, _ = cd.is_blocked("SOL-EUR", cfg={}, now=1100)
        blocked_xrp, _ = cd.is_blocked("XRP-EUR", cfg={}, now=1100)
        assert blocked_sol is True
        assert blocked_xrp is False

    def test_persistence_roundtrip(self, tmp_path):
        path = tmp_path / "p.json"
        a = PostLossCooldown(persistence_path=path)
        a.record_close("SOL-EUR", profit=-3.0, ts=1000)
        a.force_save()
        b = PostLossCooldown(persistence_path=path)
        blocked, _ = b.is_blocked("SOL-EUR", cfg={}, now=1100)
        assert blocked is True
