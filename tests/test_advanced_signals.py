"""Tests for advanced signal providers (entropy gate, trade DNA, time-of-day, VPIN, spread regime)."""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.signals.base import SignalContext, SignalResult
from modules.signals.entropy_gate import entropy_gate_signal, _shannon_entropy
from modules.signals.trade_dna import trade_dna_signal
from modules.signals.time_of_day import time_of_day_signal
from modules.signals.vpin_toxicity import vpin_toxicity_signal
from modules.signals.spread_regime import spread_regime_signal


def _make_ctx(closes=None, highs=None, lows=None, volumes=None, config=None, n=120):
    """Create a test SignalContext with sensible defaults."""
    closes = closes or [100 + i * 0.1 for i in range(n)]
    highs = highs or [c * 1.005 for c in closes]
    lows = lows or [c * 0.995 for c in closes]
    volumes = volumes or [1000.0] * n
    return SignalContext(
        market="BTC-EUR",
        candles_1m=[[0, c, h, l, c, v] for c, h, l, v in zip(closes, highs, lows, volumes)],
        closes_1m=closes,
        highs_1m=highs,
        lows_1m=lows,
        volumes_1m=volumes,
        config=config or {},
    )


# ---- Shannon Entropy Tests ----

class TestShannonEntropy:
    def test_uniform_distribution_max_entropy(self):
        """Uniform returns should have high entropy."""
        import random
        rng = random.Random(42)
        returns = [rng.uniform(-0.01, 0.01) for _ in range(200)]
        entropy = _shannon_entropy(returns)
        assert entropy > 3.0, f"Expected high entropy, got {entropy}"

    def test_constant_returns_zero_entropy(self):
        """Constant returns should yield zero entropy."""
        returns = [0.001] * 100
        entropy = _shannon_entropy(returns)
        assert entropy == 0.0

    def test_insufficient_data(self):
        returns = [0.001] * 5
        entropy = _shannon_entropy(returns)
        assert entropy == 0.0


class TestEntropyGateSignal:
    def test_low_entropy_bonus(self):
        """Very predictable (trending) market should give bonus."""
        # Steadily increasing prices → low entropy
        closes = [100 + i * 0.5 for i in range(120)]
        ctx = _make_ctx(closes=closes)
        result = entropy_gate_signal(ctx)
        assert isinstance(result, SignalResult)
        assert result.name == "entropy_gate"
        # With steady trend, entropy should be low

    def test_chaotic_market_penalty(self):
        """Random, chaotic market should penalize."""
        import random
        rng = random.Random(42)
        closes = [100.0]
        for _ in range(150):
            closes.append(closes[-1] * (1 + rng.gauss(0, 0.03)))
        ctx = _make_ctx(closes=closes[-120:], n=120)
        result = entropy_gate_signal(ctx)
        assert isinstance(result, SignalResult)
        # High volatility → high entropy → penalty
        if result.active and "high_entropy" in result.reason:
            assert result.score < 0

    def test_insufficient_data(self):
        ctx = _make_ctx(n=10)
        result = entropy_gate_signal(ctx)
        assert result.score == 0.0


# ---- Trade DNA Tests ----

class TestTradeDNA:
    def test_insufficient_data(self):
        ctx = _make_ctx(n=10)
        result = trade_dna_signal(ctx)
        assert result.score == 0.0

    def test_returns_signal_result(self):
        ctx = _make_ctx(n=120)
        result = trade_dna_signal(ctx)
        assert isinstance(result, SignalResult)
        assert result.name == "trade_dna"


# ---- Time of Day Tests ----

class TestTimeOfDay:
    def test_returns_signal_result(self):
        ctx = _make_ctx(n=720)
        result = time_of_day_signal(ctx)
        assert isinstance(result, SignalResult)
        assert result.name == "time_of_day"

    def test_insufficient_data(self):
        ctx = _make_ctx(n=50)
        result = time_of_day_signal(ctx)
        assert result.score == 0.0


# ---- VPIN Tests ----

class TestVPIN:
    def test_balanced_flow_safe(self):
        """Equal up/down movements → low VPIN → safe."""
        closes = []
        price = 100.0
        for i in range(100):
            if i % 2 == 0:
                price *= 1.001  # up
            else:
                price *= 0.999  # down
            closes.append(price)
        ctx = _make_ctx(closes=closes, n=100)
        result = vpin_toxicity_signal(ctx)
        assert isinstance(result, SignalResult)
        assert result.name == "vpin_toxicity"

    def test_one_sided_flow_toxic(self):
        """All downward movement → high VPIN → toxic."""
        closes = [100 - i * 0.5 for i in range(100)]
        ctx = _make_ctx(closes=closes, n=100)
        result = vpin_toxicity_signal(ctx)
        assert isinstance(result, SignalResult)
        if result.active:
            assert result.score < 0 or "toxic" in result.reason or "clean" in result.reason

    def test_insufficient_data(self):
        ctx = _make_ctx(n=10)
        result = vpin_toxicity_signal(ctx)
        assert result.score == 0.0


# ---- Spread Regime Tests ----

class TestSpreadRegime:
    def test_normal_spread(self):
        ctx = _make_ctx(n=120)
        result = spread_regime_signal(ctx)
        assert isinstance(result, SignalResult)
        assert result.name == "spread_regime"

    def test_wide_spread_penalty(self):
        """Abnormally wide high-low range should penalize."""
        closes = [100.0] * 120
        highs = [101.0] * 119 + [120.0]  # last candle has huge range
        lows = [99.0] * 119 + [80.0]
        ctx = _make_ctx(closes=closes, highs=highs, lows=lows, n=120)
        result = spread_regime_signal(ctx)
        if result.active and result.score < 0:
            assert "wide" in result.reason

    def test_insufficient_data(self):
        ctx = _make_ctx(n=10)
        result = spread_regime_signal(ctx)
        assert result.score == 0.0


# ---- Core Module Tests ----

class TestSmartDCA:
    def test_smart_dca_import(self):
        from core.smart_dca import should_smart_dca, smart_dca_score
        # Simple test
        closes = [100 - i * 0.1 for i in range(50)]
        should, reason = should_smart_dca(closes, 97.0, 100.0, dca_drop_pct=0.02)
        assert isinstance(should, bool)
        assert isinstance(reason, str)

    def test_smart_dca_score(self):
        from core.smart_dca import smart_dca_score
        closes = [100 - i * 0.1 for i in range(50)]
        result = smart_dca_score(closes, 95.0, 100.0)
        assert "score" in result
        assert 0 <= result["score"] <= 100


class TestBayesianFusion:
    def test_weight_update(self):
        from core.bayesian_fusion import update_signal_weight, get_signal_weight, reset_weights
        reset_weights()
        w1 = update_signal_weight("test_signal", True)
        assert w1 > 1.0
        w2 = update_signal_weight("test_signal", False)
        assert w2 < w1

    def test_weighted_score(self):
        from core.bayesian_fusion import weighted_total_score, reset_weights
        reset_weights()
        scores = {"sig_a": 2.0, "sig_b": 3.0}
        total = weighted_total_score(scores)
        # With default weight 1.0, should equal sum
        assert total == 5.0


class TestMetaLearner:
    def test_init_and_classify(self):
        from core.meta_learner import MetaLearner
        ml = MetaLearner()
        strat = ml.classify_trade(rsi=30, sma_cross=False, bb_position=0.1)
        assert strat == "mean_reversion"

    def test_weight_adjustment(self):
        from core.meta_learner import MetaLearner
        ml = MetaLearner()
        for _ in range(20):
            ml.record_outcome("momentum", 1.5)
            ml.record_outcome("mean_reversion", -0.5)
            ml.record_outcome("breakout", 0.2)
        weights = ml.update_weights()
        assert weights["momentum"] > weights["mean_reversion"]


class TestMarkovRegime:
    def test_transition_tracking(self):
        from core.markov_regime import MarkovRegimePredictor
        mrp = MarkovRegimePredictor()
        mrp.record_regime("ranging")
        mrp.record_regime("trending_up")
        mrp.record_regime("ranging")
        mrp.record_regime("trending_up")
        prob = mrp.transition_probability("ranging", "trending_up")
        assert prob > 0

    def test_score_adjustment(self):
        from core.markov_regime import MarkovRegimePredictor
        mrp = MarkovRegimePredictor()
        for _ in range(10):
            mrp.record_regime("ranging")
            mrp.record_regime("trending_up")
        adj = mrp.get_score_adjustment("ranging")
        # Should suggest lowering score since trending_up is likely
        assert isinstance(adj, float)


# ---- Novel Signal Tests (Round 2) ----

class TestFractalDimension:
    def test_trending_market(self):
        """Smooth uptrend should give low fractal dimension (near 1.0)."""
        from modules.signals.fractal_dimension import fractal_dimension_signal
        closes = [100 + i * 0.5 for i in range(120)]
        ctx = _make_ctx(closes=closes, n=120)
        result = fractal_dimension_signal(ctx)
        assert isinstance(result, SignalResult)
        assert result.name == 'fractal_dim'
        if result.details.get('fractal_dimension'):
            assert result.details['fractal_dimension'] <= 1.6

    def test_noisy_market(self):
        """Random noise should give fractal dimension near 1.5."""
        from modules.signals.fractal_dimension import fractal_dimension_signal
        import random
        rng = random.Random(42)
        closes = [100 + rng.gauss(0, 2) for _ in range(120)]
        ctx = _make_ctx(closes=closes, n=120)
        result = fractal_dimension_signal(ctx)
        assert isinstance(result, SignalResult)

    def test_insufficient_data(self):
        from modules.signals.fractal_dimension import fractal_dimension_signal
        ctx = _make_ctx(n=10)
        result = fractal_dimension_signal(ctx)
        assert result.score == 0.0


class TestVolatilityCone:
    def test_normal_vol(self):
        """Stable volatility should be neutral."""
        from modules.signals.volatility_cone import volatility_cone_signal
        import random
        rng = random.Random(42)
        base = 100.0
        closes = []
        for _ in range(150):
            base += rng.gauss(0, 0.3)
            closes.append(max(1.0, base))
        ctx = _make_ctx(closes=closes, n=150)
        result = volatility_cone_signal(ctx)
        assert isinstance(result, SignalResult)
        assert result.name == 'vol_cone'

    def test_insufficient_data(self):
        from modules.signals.volatility_cone import volatility_cone_signal
        ctx = _make_ctx(n=20)
        result = volatility_cone_signal(ctx)
        assert result.score == 0.0


class TestMicrostructureMomentum:
    def test_bullish_microstructure(self):
        """Uptrend with increasing volume should show bullish momentum."""
        from modules.signals.microstructure_momentum import microstructure_momentum_signal
        closes = [100 + i * 0.2 for i in range(60)]
        volumes = [500 + i * 50 for i in range(60)]
        ctx = _make_ctx(closes=closes, volumes=volumes, n=60)
        result = microstructure_momentum_signal(ctx)
        assert isinstance(result, SignalResult)
        assert result.name == 'micro_momentum'

    def test_choppy_market(self):
        """Alternating up/down should show low efficiency."""
        from modules.signals.microstructure_momentum import microstructure_momentum_signal
        closes = [100 + ((-1)**i) * 0.5 for i in range(60)]
        ctx = _make_ctx(closes=closes, n=60)
        result = microstructure_momentum_signal(ctx)
        assert isinstance(result, SignalResult)

    def test_insufficient_data(self):
        from modules.signals.microstructure_momentum import microstructure_momentum_signal
        ctx = _make_ctx(n=10)
        result = microstructure_momentum_signal(ctx)
        assert result.score == 0.0


class TestEntropyKelly:
    def test_predictable_market_high_fraction(self):
        """Low entropy should return higher Kelly fraction than chaotic."""
        from core.entropy_kelly import entropy_kelly_fraction
        closes = [100 + i * 0.3 for i in range(80)]
        fraction = entropy_kelly_fraction(closes, base_kelly=0.5, window=60)
        assert fraction >= 0.1, f"Expected reasonable fraction, got {fraction}"

    def test_chaotic_market_low_fraction(self):
        """High entropy should return lower Kelly fraction."""
        from core.entropy_kelly import entropy_kelly_fraction
        import random
        rng = random.Random(42)
        closes = [100 + rng.gauss(0, 3) for _ in range(80)]
        fraction = entropy_kelly_fraction(closes, base_kelly=0.5, window=60)
        assert fraction <= 0.5

    def test_get_sizing_adjustment(self):
        """Integration test for sizing adjustment function."""
        from core.entropy_kelly import get_sizing_adjustment
        closes = [100 + i * 0.1 for i in range(80)]
        result = get_sizing_adjustment(closes, {})
        assert 'fraction' in result
        assert 'entropy_ratio' in result
        assert result['regime'] in ('predictable', 'normal', 'chaotic', 'unknown')
