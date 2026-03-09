import math

from modules.signals import SignalContext, evaluate_signal_pack
from modules.signals.mean_reversion_intraday import mean_reversion_signal
from modules.signals.range_detector import range_signal
from modules.signals.volatility_breakout import volatility_breakout_signal


def _build_ctx(prices, *, config=None, volumes=None):
    cfg = config or {}
    closes = [float(p) for p in prices]
    highs = [p * 1.01 for p in closes]
    lows = [p * 0.99 for p in closes]
    vols = volumes or [100 + idx for idx in range(len(closes))]
    candles = [[0, 0, highs[i], lows[i], closes[i], vols[i]] for i in range(len(closes))]
    return SignalContext(
        market="TEST-EUR",
        candles_1m=candles,
        closes_1m=closes,
        highs_1m=highs,
        lows_1m=lows,
        volumes_1m=vols,
        config=cfg,
    )


def test_range_signal_triggers_near_support():
    prices = [100 + math.sin(i / 3) for i in range(120)]
    prices[-1] = min(prices[-20:]) * 1.0005  # near support
    ctx = _build_ctx(
        prices,
        config={
            "SIGNALS_RANGE_ENABLED": True,
            "SIGNALS_RANGE_LOOKBACK": 20,
            "SIGNALS_RANGE_THRESHOLD": 0.3,
            "SIGNALS_RANGE_RSI_PERIOD": 5,
            "SIGNALS_RANGE_RSI_MAX": 80,
        },
    )
    result = range_signal(ctx)
    assert result.active is True
    assert result.score > 0


def test_volatility_breakout_needs_volume_confirmation():
    prices = [100 + i * 0.15 for i in range(80)]
    prices[-1] = prices[-2] + 5  # force breakout beyond ATR band
    volumes = [100 for _ in range(79)] + [1000]
    ctx = _build_ctx(
        prices,
        volumes=volumes,
        config={
            "SIGNALS_VOL_BREAKOUT_ENABLED": True,
            "SIGNALS_VOL_ATR_WINDOW": 5,
            "SIGNALS_VOL_ATR_MULT": 0.5,
            "SIGNALS_VOL_VOLUME_WINDOW": 10,
            "SIGNALS_VOL_VOLUME_SPIKE": 1.2,
        },
    )
    result = volatility_breakout_signal(ctx)
    assert result.active is True
    assert result.score > 0


def test_mean_reversion_detects_zscore_extreme():
    prices = [100 - i * 0.3 for i in range(60)]
    ctx = _build_ctx(
        prices,
        config={
            "SIGNALS_MEAN_REV_ENABLED": True,
            "SIGNALS_MEAN_REV_WINDOW": 30,
            "SIGNALS_MEAN_REV_Z": -0.5,
            "SIGNALS_MEAN_REV_RSI_MAX": 80,
        },
    )
    result = mean_reversion_signal(ctx)
    assert result.active is True
    assert result.score > 0


def test_signal_pack_accumulates_scores():
    prices = [100 + math.sin(i / 6) for i in range(150)]
    volumes = [150 + (i % 10) for i in range(150)]
    ctx = _build_ctx(
        prices,
        volumes=volumes,
        config={
            "SIGNALS_RANGE_ENABLED": True,
            "SIGNALS_RANGE_LOOKBACK": 30,
            "SIGNALS_RANGE_THRESHOLD": 0.6,
            "SIGNALS_VOL_BREAKOUT_ENABLED": True,
            "SIGNALS_VOL_ATR_WINDOW": 10,
            "SIGNALS_VOL_VOLUME_WINDOW": 15,
            "SIGNALS_MEAN_REV_ENABLED": True,
            "SIGNALS_MEAN_REV_WINDOW": 20,
            "SIGNALS_TA_ENABLED": True,
        },
    )
    pack = evaluate_signal_pack(ctx)
    assert pack.total_score >= 0
    # At least one provider should produce an entry confirmation in this synthetic setup
    assert any(result.active for result in pack.results)
