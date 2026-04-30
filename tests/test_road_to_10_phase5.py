"""Tests for Road-to-10 #064: decorrelation wiring + shadow trading."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from bot import shadow_trading
from bot.entry_pipeline import EntryDecision, apply_decorrelation_filter, decide_entry
from bot.shared import state


@pytest.fixture(autouse=True)
def _restore_state():
    snap = {'CONFIG': dict(state.CONFIG or {})}
    yield
    state.CONFIG = snap['CONFIG']


class TestDecorrelationWiring:
    def test_disabled_passes_through(self):
        d = decide_entry(market='BTC-EUR', score=10, min_score=7, eur_amount=25,
                        spread_pct=0.0001, config={'ORDER_TYPE': 'auto'})
        out = apply_decorrelation_filter(d, candidate_closes=[], open_market_closes={},
                                          config={'DECORRELATION_ENABLED': False})
        assert out is d  # passthrough

    def test_no_open_trades_passes(self):
        d = decide_entry(market='BTC-EUR', score=10, min_score=7, eur_amount=25,
                        spread_pct=0.0001, config={})
        out = apply_decorrelation_filter(
            d, candidate_closes=[100 + i for i in range(30)], open_market_closes={},
            config={'DECORRELATION_ENABLED': True})
        assert out.proceed is True

    def test_blocks_when_correlated(self):
        d = decide_entry(market='SOL-EUR', score=10, min_score=7, eur_amount=25, config={})
        cand = [100 + i for i in range(30)]
        # near perfect positive corr
        open_m = {'BTC-EUR': [200 + 2 * i for i in range(30)]}
        out = apply_decorrelation_filter(
            d, candidate_closes=cand, open_market_closes=open_m,
            config={'DECORRELATION_ENABLED': True, 'DECORRELATION_MAX_CORR': 0.7})
        assert out.proceed is False
        assert 'too_correlated_with_BTC-EUR' in out.reason

    def test_does_not_modify_already_blocked(self):
        d = EntryDecision(market='X', proceed=False, reason='regime_block', score=0)
        out = apply_decorrelation_filter(
            d, candidate_closes=[1, 2, 3], open_market_closes={'Y': [4, 5, 6]},
            config={'DECORRELATION_ENABLED': True})
        assert out is d


class TestShadowTrading:
    def test_disabled_returns_false(self, tmp_path, monkeypatch):
        state.CONFIG = {'SHADOW_TRADING_ENABLED': False}
        assert shadow_trading.log_shadow_entry('X-EUR', {'foo': 1}) is False

    def test_enabled_writes_jsonl(self, tmp_path, monkeypatch):
        state.CONFIG = {'SHADOW_TRADING_ENABLED': True}
        target = tmp_path / 'shadow.jsonl'
        monkeypatch.setattr(shadow_trading, '_SHADOW_PATH', target)
        ok = shadow_trading.log_shadow_entry('BTC-EUR', {'score': 9.5, 'confidence': 0.7})
        assert ok is True
        assert target.exists()
        records = [json.loads(l) for l in target.read_text(encoding='utf-8').splitlines()]
        assert len(records) == 1
        assert records[0]['market'] == 'BTC-EUR'
        assert records[0]['payload']['score'] == 9.5

    def test_enabled_multiple_appends(self, tmp_path, monkeypatch):
        state.CONFIG = {'SHADOW_TRADING_ENABLED': True}
        target = tmp_path / 'shadow.jsonl'
        monkeypatch.setattr(shadow_trading, '_SHADOW_PATH', target)
        for i in range(5):
            shadow_trading.log_shadow_entry(f'M{i}-EUR', {'i': i})
        records = [json.loads(l) for l in target.read_text(encoding='utf-8').splitlines()]
        assert len(records) == 5
