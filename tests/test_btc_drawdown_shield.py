# -*- coding: utf-8 -*-
"""Tests for bot.btc_drawdown_shield."""
from bot.btc_drawdown_shield import evaluate


def _candles(closes):
    """Build minimal Bitvavo-format candles from a list of closes."""
    return [[1000 + i * 300000, c, c, c, c, 100.0] for i, c in enumerate(closes)]


class TestBTCShield:
    def test_disabled_returns_pass(self):
        r = evaluate(_candles([100, 90]), cfg={'BTC_DRAWDOWN_SHIELD_ENABLED': False},
                     market='SOL-EUR')
        assert r.blocked is False

    def test_btc_market_exempt(self):
        r = evaluate(_candles([100, 80]), cfg={}, market='BTC-EUR')
        assert r.blocked is False
        assert r.reason == 'is_btc'

    def test_no_data(self):
        r = evaluate(None, cfg={}, market='SOL-EUR')
        assert r.blocked is False
        r = evaluate([], cfg={}, market='SOL-EUR')
        assert r.blocked is False

    def test_btc_falling_blocks(self):
        # 13 candles, drop from 100 to 97 = -3% over 1h
        candles = _candles([100] + [99] * 6 + [97] * 6)
        r = evaluate(candles, cfg={}, market='SOL-EUR')
        assert r.blocked is True
        assert r.btc_return_pct < -1.5

    def test_btc_stable_passes(self):
        candles = _candles([100] * 13)
        r = evaluate(candles, cfg={}, market='SOL-EUR')
        assert r.blocked is False

    def test_btc_rising_passes(self):
        candles = _candles([100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112])
        r = evaluate(candles, cfg={}, market='SOL-EUR')
        assert r.blocked is False
        assert r.btc_return_pct > 0

    def test_custom_threshold(self):
        # Drop -1.0%, default threshold -1.5% would not block, but -0.5% would
        candles = _candles([100] * 12 + [99])
        r1 = evaluate(candles, cfg={}, market='SOL-EUR')
        assert r1.blocked is False
        r2 = evaluate(candles, cfg={'BTC_DRAWDOWN_THRESHOLD_PCT': -0.5},
                      market='SOL-EUR')
        assert r2.blocked is True

    def test_custom_lookback(self):
        # Slow grind upward, then sharp drop at the very end
        candles = _candles([90, 92, 94, 96, 98, 100, 102, 104, 106, 108, 99, 98, 97])
        r_long = evaluate(candles, cfg={'BTC_DRAWDOWN_LOOKBACK_5M': 12},
                          market='SOL-EUR')
        r_short = evaluate(candles, cfg={'BTC_DRAWDOWN_LOOKBACK_5M': 3},
                           market='SOL-EUR')
        # Long window: 90 -> 97 = positive. Short: 108 -> 97 = strongly negative
        assert r_long.btc_return_pct > 0
        assert r_short.btc_return_pct < -5
