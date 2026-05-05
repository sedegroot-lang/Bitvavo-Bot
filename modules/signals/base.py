"""Shared dataclasses and helper utilities for advanced signal providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, MutableMapping, Protocol, Sequence


@dataclass(slots=True)
class SignalContext:
    """Current market data passed to each signal provider."""

    market: str
    candles_1m: Sequence[Sequence[Any]]
    closes_1m: Sequence[float]
    highs_1m: Sequence[float]
    lows_1m: Sequence[float]
    volumes_1m: Sequence[float]
    config: MutableMapping[str, Any]


@dataclass(slots=True)
class SignalResult:
    """Normalized output from a provider."""

    name: str
    score: float = 0.0
    active: bool = False
    reason: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


class SignalProvider(Protocol):
    """Callable contract every provider must implement."""

    def __call__(self, ctx: SignalContext) -> SignalResult:  # pragma: no cover - Protocol
        ...


@dataclass(slots=True)
class SignalPackResult:
    total_score: float
    results: List[SignalResult] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "total_score": self.total_score,
            "results": [
                {
                    "name": res.name,
                    "score": res.score,
                    "active": res.active,
                    "reason": res.reason,
                    "details": res.details,
                }
                for res in self.results
            ],
        }


def _safe_cfg_float(config: Mapping[str, Any], key: str, default: float) -> float:
    try:
        value = float(config.get(key, default))
    except Exception:
        return default
    return value


def _safe_cfg_int(config: Mapping[str, Any], key: str, default: int) -> int:
    try:
        value = int(config.get(key, default))
    except Exception:
        return default
    return value


def _safe_cfg_bool(config: Mapping[str, Any], key: str, default: bool) -> bool:
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    try:
        return bool(value)
    except Exception:
        return default


__all__ = [
    "SignalContext",
    "SignalProvider",
    "SignalResult",
    "SignalPackResult",
    "_safe_cfg_float",
    "_safe_cfg_int",
    "_safe_cfg_bool",
]
