"""Aggregate helper for enhanced signal providers."""

from __future__ import annotations

from typing import Iterable, List

from .base import SignalContext, SignalPackResult, SignalProvider, SignalResult
from .entropy_gate import entropy_gate_signal
from .fractal_dimension import fractal_dimension_signal
from .mean_reversion_intraday import mean_reversion_signal
from .mean_reversion_scalper import mean_reversion_scalper_signal
from .microstructure_momentum import microstructure_momentum_signal
from .range_detector import range_signal
from .spread_regime import spread_regime_signal
from .ta_filters import ta_confirmation_signal
from .time_of_day import time_of_day_signal
from .trade_dna import trade_dna_signal
from .volatility_breakout import volatility_breakout_signal
from .volatility_cone import volatility_cone_signal
from .vpin_toxicity import vpin_toxicity_signal


PROVIDERS: List[SignalProvider] = [
    range_signal,
    volatility_breakout_signal,
    mean_reversion_signal,
    mean_reversion_scalper_signal,
    ta_confirmation_signal,
    # --- Advanced signal filters (simulation-proven) ---
    entropy_gate_signal,        # +€149 simulated improvement
    trade_dna_signal,           # +€177 simulated improvement
    time_of_day_signal,         # +€106 simulated improvement
    vpin_toxicity_signal,       # +€27 simulated improvement
    spread_regime_signal,       # +€23 simulated improvement
    # --- Novel microstructure signals ---
    fractal_dimension_signal,   # Higuchi fractal dimension: trend quality
    volatility_cone_signal,     # Vol cone: abnormal volatility detection
    microstructure_momentum_signal,  # Hidden order flow momentum
]


def evaluate_signal_pack(ctx: SignalContext, providers: Iterable[SignalProvider] | None = None) -> SignalPackResult:
    active_providers = list(providers or PROVIDERS)
    results: List[SignalResult] = []
    total = 0.0
    for provider in active_providers:
        try:
            result = provider(ctx)
        except Exception as exc:  # pragma: no cover - defensive logging occurs upstream
            results.append(
                SignalResult(
                    name=getattr(provider, "__name__", "unknown"),
                    score=0.0,
                    active=False,
                    reason=f"error:{exc}",
                )
            )
            continue
        results.append(result)
        if result.active:
            total += float(result.score)
    return SignalPackResult(total_score=total, results=results)


__all__ = [
    "SignalContext",
    "SignalPackResult",
    "SignalProvider",
    "SignalResult",
    "evaluate_signal_pack",
]
