"""bot.entry_pipeline — High-level entry orchestration extracted from trailing_bot.

Roadmap fase 2 — first slice. Splits the entry decision into a small,
testable pipeline:

    decide_entry(ctx) -> EntryDecision

This does NOT yet replace the entry loop in trailing_bot.py — it is a
parallel, side-effect-free decision helper that the loop can adopt
incrementally. The loop currently calls into bot.signals + bot.entry_confidence
+ bot.sizing_floor in a long inline sequence; this module wraps the same
checks behind one clean dataclass.

Limit-orders fase 5 reminder: the order placement itself remains in
bot/orders_impl.py. Pipeline outputs `order_type='limit'|'market'` honoring
`CONFIG.ORDER_TYPE` (default 'auto') so callers can pass it straight to
place_buy(). When `LIMIT_ORDER_PREFER=True` is set in local config, the
pipeline always returns 'limit' to recapture the 39% slippage observed in
roadmap analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(slots=True)
class EntryDecision:
    market: str
    proceed: bool
    reason: str = ''
    score: float = 0.0
    eur_amount: float = 0.0
    order_type: str = 'auto'
    metadata: Dict[str, Any] = field(default_factory=dict)


def decide_order_type(config: Dict[str, Any], spread_pct: Optional[float] = None) -> str:
    """Return 'limit' | 'market' based on config + live spread.

    Rules:
        * `LIMIT_ORDER_PREFER=True` → always 'limit'
        * `ORDER_TYPE='limit'` → 'limit' (legacy)
        * `ORDER_TYPE='market'` → 'market'
        * `ORDER_TYPE='auto'` (default) → 'limit' when spread<0.1%, else 'market'
    """
    try:
        if bool(config.get('LIMIT_ORDER_PREFER', False)):
            return 'limit'
    except Exception:
        pass
    ot = str(config.get('ORDER_TYPE', 'auto') or 'auto').lower()
    if ot == 'limit':
        return 'limit'
    if ot == 'market':
        return 'market'
    if spread_pct is not None and spread_pct < 0.001:
        return 'limit'
    return 'market'


def decide_entry(
    *,
    market: str,
    score: float,
    min_score: float,
    eur_amount: float,
    spread_pct: Optional[float] = None,
    block_reason: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> EntryDecision:
    """Pure decision helper. No I/O, no order placement. Easily unit-tested."""
    config = config or {}

    if block_reason:
        return EntryDecision(market=market, proceed=False, reason=block_reason, score=score)

    if score < min_score:
        return EntryDecision(
            market=market,
            proceed=False,
            reason=f'score_below_min({score:.2f}<{min_score:.2f})',
            score=score,
        )

    if eur_amount <= 0:
        return EntryDecision(market=market, proceed=False, reason='zero_eur', score=score)

    order_type = decide_order_type(config, spread_pct=spread_pct)
    return EntryDecision(
        market=market,
        proceed=True,
        reason='ok',
        score=score,
        eur_amount=eur_amount,
        order_type=order_type,
        metadata={'spread_pct': spread_pct},
    )


def apply_decorrelation_filter(
    decision: EntryDecision,
    *,
    candidate_closes,
    open_market_closes,
    config: Optional[Dict[str, Any]] = None,
) -> EntryDecision:
    """Optionally veto a passing decision when correlation with open trades > threshold.

    Reads `DECORRELATION_ENABLED` (bool) and `DECORRELATION_MAX_CORR` (float, default 0.7)
    from config. When disabled or insufficient data, returns the input decision unchanged.
    """
    config = config or {}
    if not bool(config.get('DECORRELATION_ENABLED', False)):
        return decision
    if not decision.proceed:
        return decision
    try:
        from bot.decorrelation import is_decorrelated
    except Exception:
        return decision
    max_corr = float(config.get('DECORRELATION_MAX_CORR', 0.7) or 0.7)
    ok, corrs = is_decorrelated(candidate_closes, open_market_closes, max_corr=max_corr)
    if ok:
        decision.metadata['correlations'] = corrs
        return decision
    worst = max(corrs.items(), key=lambda kv: abs(kv[1])) if corrs else ('?', 0.0)
    return EntryDecision(
        market=decision.market,
        proceed=False,
        reason=f'too_correlated_with_{worst[0]}({worst[1]:.2f}>{max_corr})',
        score=decision.score,
        metadata={'correlations': corrs},
    )
