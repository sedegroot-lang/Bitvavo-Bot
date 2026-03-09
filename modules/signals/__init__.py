"""Aggregate helper for enhanced signal providers."""

from __future__ import annotations

from typing import Iterable, List

from .base import SignalContext, SignalPackResult, SignalProvider, SignalResult
from .mean_reversion_intraday import mean_reversion_signal
from .mean_reversion_scalper import mean_reversion_scalper_signal
from .range_detector import range_signal
from .ta_filters import ta_confirmation_signal
from .volatility_breakout import volatility_breakout_signal


PROVIDERS: List[SignalProvider] = [
    range_signal,
    volatility_breakout_signal,
    mean_reversion_signal,
    mean_reversion_scalper_signal,
    ta_confirmation_signal,
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
