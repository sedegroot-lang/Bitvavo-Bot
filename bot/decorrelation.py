"""bot.decorrelation — Cross-market correlation filter for entry pipeline.

Roadmap fase 5: prevents opening N trades that are effectively the same trade
(e.g. SOL + AVAX + MATIC all moving with BTC). Reads recent closes for
candidate vs already-open trades and rejects if max correlation > threshold.

Design: pure helpers, no I/O. Caller passes candle dicts; returns bool/score.
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional, Sequence


def pearson_correlation(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    n = min(len(a), len(b))
    if n < 10:
        return None
    a = list(a)[-n:]
    b = list(b)[-n:]
    mean_a = sum(a) / n
    mean_b = sum(b) / n
    num = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    den_a = math.sqrt(sum((x - mean_a) ** 2 for x in a))
    den_b = math.sqrt(sum((y - mean_b) ** 2 for y in b))
    if den_a == 0 or den_b == 0:
        return None
    return num / (den_a * den_b)


def _returns(closes: Sequence[float]) -> List[float]:
    out: List[float] = []
    prev = None
    for c in closes:
        if prev is not None and prev > 0:
            out.append((c - prev) / prev)
        prev = c
    return out


def is_decorrelated(
    candidate_closes: Sequence[float],
    open_market_closes: Dict[str, Sequence[float]],
    *,
    max_corr: float = 0.7,
) -> tuple[bool, Dict[str, float]]:
    """Return (ok, per-market correlations).

    `ok` = True when correlation with EVERY open market is ≤ `max_corr`.
    Insufficient data → treated as ok (don't block on missing data).
    """
    cand_ret = _returns(candidate_closes)
    if len(cand_ret) < 10:
        return True, {}
    corrs: Dict[str, float] = {}
    for market, closes in open_market_closes.items():
        ret = _returns(closes)
        c = pearson_correlation(cand_ret, ret)
        if c is None:
            continue
        corrs[market] = round(c, 3)
        if abs(c) > max_corr:
            return False, corrs
    return True, corrs
