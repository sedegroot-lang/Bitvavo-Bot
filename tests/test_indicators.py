"""Tests for core/indicators.py — pure TA functions."""

import pytest
import numpy as np

from core.indicators import (
    close_prices,
    highs,
    lows,
    volumes,
    sma,
    ema,
    ema_series,
    rsi,
    macd,
    atr,
    bollinger_bands,
    stochastic,
    calculate_momentum_score,
)


# ---------------------------------------------------------------------------
# Candle helpers
# ---------------------------------------------------------------------------

def _make_candles(closes, *, high_offset=1.0, low_offset=1.0, vol=100.0):
    """Build fake candle arrays: [ts, open, high, low, close, volume]."""
    return [
        [i * 60000, c, c + high_offset, c - low_offset, c, vol]
        for i, c in enumerate(closes)
    ]


class TestCandleHelpers:
    def test_close_prices(self):
        candles = _make_candles([10, 20, 30])
        assert close_prices(candles) == [10.0, 20.0, 30.0]

    def test_close_prices_empty(self):
        assert close_prices([]) == []
        assert close_prices(None) == []

    def test_highs(self):
        candles = _make_candles([10, 20])
        assert highs(candles) == [11.0, 21.0]

    def test_lows(self):
        candles = _make_candles([10, 20])
        assert lows(candles) == [9.0, 19.0]

    def test_volumes(self):
        candles = _make_candles([10, 20], vol=500.0)
        assert volumes(candles) == [500.0, 500.0]

    def test_malformed_candles_skipped(self):
        candles = [[1], [2, 3], [4, 5, 6, 7, 8, 9]]
        assert close_prices(candles) == [8.0]
        assert highs(candles) == [6.0]


# ---------------------------------------------------------------------------
# Moving averages
# ---------------------------------------------------------------------------

class TestSMA:
    def test_basic(self):
        vals = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert sma(vals, 3) == pytest.approx(4.0)  # mean([3,4,5])

    def test_too_short(self):
        assert sma([1.0, 2.0], 5) is None


class TestEMA:
    def test_basic(self):
        vals = list(range(1, 21))  # 1..20
        result = ema(vals, 10)
        assert result is not None
        assert isinstance(result, float)

    def test_too_short(self):
        assert ema([1.0, 2.0], 5) is None

    def test_single_value(self):
        # With window=1, EMA should converge to last value
        assert ema([5.0], 1) == pytest.approx(5.0)


class TestEMASeries:
    def test_length(self):
        vals = list(range(1, 11))
        series = ema_series(vals, 5)
        assert len(series) == len(vals)


# ---------------------------------------------------------------------------
# Oscillators
# ---------------------------------------------------------------------------

class TestRSI:
    def test_all_gains(self):
        vals = list(range(1, 20))  # strictly increasing
        r = rsi(vals, 14)
        assert r == 100.0

    def test_all_losses(self):
        vals = list(range(20, 0, -1))  # strictly decreasing
        r = rsi(vals, 14)
        assert r is not None
        assert r < 30  # heavily oversold

    def test_too_short(self):
        assert rsi([1, 2, 3], 14) is None

    def test_mixed(self):
        np.random.seed(42)
        vals = np.cumsum(np.random.randn(50)).tolist()
        r = rsi(vals, 14)
        assert 0 <= r <= 100


class TestStochastic:
    def test_basic(self):
        vals = [10, 12, 8, 14, 11]
        s = stochastic(vals, 5)
        # close=11, high=14, low=8 → 100*(11-8)/(14-8) = 50
        assert s == pytest.approx(50.0)

    def test_too_short(self):
        assert stochastic([1, 2], 5) is None

    def test_flat(self):
        # All same values → high==low → None
        assert stochastic([5, 5, 5, 5, 5], 5) is None


class TestMACD:
    def test_basic(self):
        vals = list(range(1, 50))  # uptrend
        m_line, sig, hist = macd(vals, 12, 26, 9)
        assert m_line is not None
        assert sig is not None
        assert hist is not None
        assert m_line > 0  # uptrend = positive MACD

    def test_too_short(self):
        assert macd([1, 2, 3], 12, 26, 9) == (None, None, None)


# ---------------------------------------------------------------------------
# Volatility
# ---------------------------------------------------------------------------

class TestBollingerBands:
    def test_basic(self):
        vals = [float(i) for i in range(1, 25)]
        upper, mid, lower = bollinger_bands(vals, 20, 2)
        assert upper > mid > lower
        assert mid == pytest.approx(float(np.mean(vals[-20:])))

    def test_too_short(self):
        assert bollinger_bands([1, 2, 3], 20, 2) == (None, None, None)


class TestATR:
    def test_basic(self):
        h = [float(i + 1) for i in range(20)]
        l = [float(i - 1) for i in range(20)]
        c = [float(i) for i in range(20)]
        result = atr(h, l, c, 14)
        assert result is not None
        assert result > 0

    def test_too_short(self):
        assert atr([1.0], [0.5], [0.8], 14) is None


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------

class TestMomentumScore:
    def test_uptrend(self):
        # Strong uptrend: prices increase 2% per candle
        base = 100.0
        closes = [base * (1.02 ** i) for i in range(25)]
        candles = _make_candles(closes, vol=200.0)
        score = calculate_momentum_score(candles)
        assert score > 0

    def test_downtrend(self):
        base = 100.0
        closes = [base * (0.98 ** i) for i in range(25)]
        candles = _make_candles(closes, vol=200.0)
        score = calculate_momentum_score(candles)
        assert score < 0

    def test_too_few_candles(self):
        candles = _make_candles([100, 101, 102])
        assert calculate_momentum_score(candles) == 0

    def test_empty(self):
        assert calculate_momentum_score([]) == 0
