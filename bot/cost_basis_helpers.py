"""Cost basis helpers (extracted from trailing_bot.py — road-to-10 #066 batch 6).

Pure helpers, no state dependencies.
"""
from __future__ import annotations

from typing import Any, Dict


def get_true_total_invested(trade: Dict[str, Any]) -> float:
    """Return the most reliable total investment cost for a trade.

    Prefers initial_invested_eur (immutable) as ground truth.
    Falls back to total_invested_eur, then invested_eur, then buy_price*amount.
    Ensures total_invested is never less than initial_invested.
    """
    _init = float(trade.get('initial_invested_eur', 0) or 0)
    _total = float(trade.get('total_invested_eur', 0) or 0)
    _current = float(trade.get('invested_eur', 0) or 0)
    _bp = float(trade.get('buy_price', 0) or 0)
    _amt = float(trade.get('amount', 0) or 0)
    _computed = round(_bp * _amt, 4) if _bp > 0 and _amt > 0 else 0.0

    result = _total if _total > 0 else (_current if _current > 0 else _computed)

    if _init > 0 and result < _init:
        result = _init

    return result
