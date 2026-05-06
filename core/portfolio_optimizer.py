"""Portfolio-level Kelly + correlation-aware capital allocation.

Per-trade Kelly already lives in ``core/kelly_sizing.py``. This module sits
*above* it and answers a different question:

    "Given N candidate buy opportunities and the markets I already hold,
    how should I split a finite EUR budget across them?"

It combines three signals:

1. **Per-market Kelly fraction** — confidence per candidate (input).
2. **Correlation penalty** — if two candidates move together, allocating to
   both gives illusory diversification, so we down-weight them jointly.
3. **Volatility budget** — total target risk (sum of |weight| × volatility)
   capped at a configurable ceiling.

The function is **pure** (no I/O, no shared state) and trivially testable.
Bot integration (consume from ``bot/orders_impl.py``) is intentionally NOT
wired in this module — that requires a config-flag rollout and is tracked as
a separate sprint in the roadmap.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple


# ---------- Inputs ----------

@dataclass
class CandidateMarket:
    """One buy opportunity considered for allocation."""

    market: str
    kelly_fraction: float       # 0..1, half-Kelly recommended
    volatility: float           # e.g. 1m return stdev or ATR/price; >0
    score: float = 0.0          # informational only


@dataclass
class HeldPosition:
    """One existing open trade — its risk counts against the budget."""

    market: str
    weight: float               # current EUR weight as fraction of total budget
    volatility: float


# ---------- Output ----------

@dataclass
class PortfolioAllocation:
    """Result: how to split ``budget_eur`` over the candidates."""

    weights: Dict[str, float]                # market → fraction of budget (0..1)
    eur: Dict[str, float]                    # market → EUR amount
    skipped: List[Tuple[str, str]] = field(default_factory=list)  # (market, reason)
    total_risk: float = 0.0
    risk_cap: float = 0.0

    def as_dict(self) -> Dict[str, object]:
        return {
            "weights": {k: round(v, 6) for k, v in self.weights.items()},
            "eur": {k: round(v, 2) for k, v in self.eur.items()},
            "skipped": [list(s) for s in self.skipped],
            "total_risk": round(self.total_risk, 6),
            "risk_cap": round(self.risk_cap, 6),
        }


# ---------- Helpers ----------

def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _correlation_penalty(
    candidates: Sequence[CandidateMarket],
    correlation: Optional[Mapping[Tuple[str, str], float]],
) -> Dict[str, float]:
    """Average absolute correlation per candidate against the *other* candidates.

    Result in [0, 1]. Higher = more redundant with the rest of the basket.
    """
    if correlation is None or len(candidates) <= 1:
        return {c.market: 0.0 for c in candidates}
    out: Dict[str, float] = {}
    for c in candidates:
        corrs: List[float] = []
        for other in candidates:
            if other.market == c.market:
                continue
            key = (c.market, other.market)
            rev = (other.market, c.market)
            v = correlation.get(key, correlation.get(rev))
            if v is None:
                continue
            corrs.append(abs(float(v)))
        out[c.market] = sum(corrs) / len(corrs) if corrs else 0.0
    return out


# ---------- Core algorithm ----------

def compute_portfolio_weights(
    candidates: Sequence[CandidateMarket],
    held: Sequence[HeldPosition] = (),
    budget_eur: float = 0.0,
    *,
    correlation: Optional[Mapping[Tuple[str, str], float]] = None,
    risk_cap: float = 0.20,
    max_weight_per_market: float = 0.40,
    correlation_aversion: float = 0.50,
    min_eur_per_position: float = 10.0,
) -> PortfolioAllocation:
    """Allocate ``budget_eur`` across ``candidates``.

    Args:
        candidates: Buy opportunities, each with a Kelly fraction and volatility.
        held: Already-open positions whose risk eats into the cap.
        budget_eur: EUR available to deploy across candidates (e.g. cash reserve
            minus 15% safety buffer).
        correlation: Optional symmetric map ``(market_a, market_b) → corr``.
            Missing pairs are treated as zero correlation.
        risk_cap: Maximum allowed ``Σ |w| × vol`` for the *total* portfolio
            (held + candidates).
        max_weight_per_market: Single-market weight ceiling, fraction of budget.
        correlation_aversion: 0 disables correlation penalty, 1 fully discounts
            duplicated exposure.
        min_eur_per_position: Skip allocations smaller than this.

    Returns:
        :class:`PortfolioAllocation` with per-market weights and EUR amounts.
    """
    if budget_eur <= 0 or not candidates:
        return PortfolioAllocation(weights={}, eur={}, risk_cap=risk_cap)

    correlation_aversion = _clip(correlation_aversion, 0.0, 1.0)

    # Used risk from held positions (we do NOT touch them — only constrain new buys)
    held_risk = sum(max(0.0, p.weight) * max(0.0, p.volatility) for p in held)
    headroom = max(0.0, risk_cap - held_risk)
    if headroom <= 0:
        return PortfolioAllocation(
            weights={}, eur={},
            skipped=[(c.market, "risk_cap_exhausted_by_held") for c in candidates],
            total_risk=held_risk, risk_cap=risk_cap,
        )

    penalties = _correlation_penalty(candidates, correlation)

    # Raw weights: kelly × (1 - aversion·corr_penalty)
    raw: Dict[str, float] = {}
    for c in candidates:
        kf = max(0.0, float(c.kelly_fraction))
        pen = penalties.get(c.market, 0.0)
        raw[c.market] = kf * (1.0 - correlation_aversion * pen)
    total_raw = sum(raw.values())
    if total_raw <= 0:
        return PortfolioAllocation(
            weights={}, eur={},
            skipped=[(c.market, "no_kelly_signal") for c in candidates],
            total_risk=held_risk, risk_cap=risk_cap,
        )

    # Provisional fractions normalised to sum 1
    prov: Dict[str, float] = {m: r / total_raw for m, r in raw.items()}

    # Apply per-market ceiling and renormalise (one-pass — good enough)
    capped = {m: min(w, max_weight_per_market) for m, w in prov.items()}
    s = sum(capped.values())
    if s > 0:
        capped = {m: w / s for m, w in capped.items()}

    # Scale by risk-budget headroom: pick a scalar λ ≤ 1 so that
    # Σ λ·w·vol ≤ headroom. λ = min(1, headroom / Σ w·vol).
    vol_per_market = {c.market: max(0.0, c.volatility) for c in candidates}
    portfolio_vol = sum(capped[m] * vol_per_market[m] for m in capped)
    lam = 1.0 if portfolio_vol <= 0 else min(1.0, headroom / portfolio_vol)
    weights = {m: round(capped[m] * lam, 8) for m in capped}

    # Convert to EUR & enforce minimum-position size
    eur: Dict[str, float] = {}
    skipped: List[Tuple[str, str]] = []
    for m, w in weights.items():
        amount = w * budget_eur
        if amount < min_eur_per_position:
            skipped.append((m, f"below_min_eur({amount:.2f}<{min_eur_per_position})"))
            continue
        eur[m] = round(amount, 2)

    # If the min-EUR filter dropped some, redistribute their weight proportionally
    if skipped:
        kept = [m for m in weights if m in eur]
        kept_sum = sum(weights[m] for m in kept)
        if kept_sum > 0:
            spare = sum(weights[m] for m, _ in skipped)
            for m in kept:
                weights[m] = round(weights[m] + spare * (weights[m] / kept_sum), 8)
                eur[m] = round(weights[m] * budget_eur, 2)
        # Drop skipped from weights map for cleanliness
        for m, _ in skipped:
            weights.pop(m, None)

    total_risk = held_risk + sum(weights.get(m, 0.0) * vol_per_market.get(m, 0.0) for m in weights)
    return PortfolioAllocation(
        weights=weights, eur=eur, skipped=skipped,
        total_risk=total_risk, risk_cap=risk_cap,
    )
