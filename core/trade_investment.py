"""
Trade Investment Module - Single Source of Truth for invested_eur mutations.

This module provides the ONLY code paths that may modify invested_eur,
total_invested_eur, and initial_invested_eur on trade dicts.

Rules:
  1. invested_eur = current exposure (reduced by partial TPs, increased by DCAs)
  2. total_invested_eur = cumulative cost (initial + all DCAs, NEVER reduced)
  3. initial_invested_eur = first buy cost (IMMUTABLE after set)

NEVER mutate these fields directly on a trade dict. Always use this module.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

_log = logging.getLogger("trade_investment")

# Type alias for readability
Trade = Dict[str, Any]


def set_initial(trade: Trade, invested_eur: float, *, source: str = "unknown") -> None:
    """
    Set initial investment on a NEW trade.

    Must be called exactly once per trade when it is first created.
    Raises ValueError if initial_invested_eur is already set and positive.

    Args:
        trade: Trade dict (mutated in-place).
        invested_eur: The actual EUR cost of the initial buy.
        source: Caller label for audit logging.
    """
    if invested_eur <= 0:
        _log.warning("[TradeInvestment] set_initial called with non-positive %.4f from %s", invested_eur, source)
        return

    existing = float(trade.get("initial_invested_eur", 0) or 0)
    if existing > 0:
        _log.warning(
            "[TradeInvestment] set_initial BLOCKED – initial_invested_eur already %.2f (source=%s)",
            existing,
            source,
        )
        return

    trade["invested_eur"] = round(invested_eur, 4)
    trade["initial_invested_eur"] = round(invested_eur, 4)
    trade["total_invested_eur"] = round(invested_eur, 4)
    _log.info("[TradeInvestment] set_initial €%.2f (source=%s)", invested_eur, source)


def add_dca(trade: Trade, dca_cost_eur: float, *, source: str = "unknown") -> None:
    """
    Add DCA buy cost to the trade.

    Increases both invested_eur (current exposure) and total_invested_eur.
    Preserves partial TP reductions in invested_eur (adds, never replaces).

    Args:
        trade: Trade dict (mutated in-place).
        dca_cost_eur: Actual EUR spent on this DCA buy.
        source: Caller label for audit logging.
    """
    if dca_cost_eur <= 0:
        _log.warning("[TradeInvestment] add_dca called with non-positive %.4f from %s", dca_cost_eur, source)
        return

    # Ensure initial_invested_eur is set (safety net for legacy trades)
    if not float(trade.get("initial_invested_eur", 0) or 0) > 0:
        old_inv = float(trade.get("invested_eur", 0) or 0)
        if old_inv > 0:
            trade["initial_invested_eur"] = round(old_inv, 4)

    old_invested = float(trade.get("invested_eur", 0) or 0)
    old_total = float(trade.get("total_invested_eur", old_invested) or old_invested)

    trade["invested_eur"] = round(old_invested + dca_cost_eur, 4)
    trade["total_invested_eur"] = round(old_total + dca_cost_eur, 4)
    _log.info(
        "[TradeInvestment] add_dca +€%.2f → invested €%.2f→€%.2f, total €%.2f→€%.2f (source=%s)",
        dca_cost_eur,
        old_invested,
        trade["invested_eur"],
        old_total,
        trade["total_invested_eur"],
        source,
    )


def reduce_partial_tp(trade: Trade, portion: float, *, source: str = "unknown") -> float:
    """
    Reduce invested_eur proportionally after a partial take-profit sell.

    total_invested_eur stays UNCHANGED (it tracks cumulative cost).

    Args:
        trade: Trade dict (mutated in-place).
        portion: Fraction sold (0.0 – 1.0). E.g., 0.33 for 33% sell.
        source: Caller label for audit logging.

    Returns:
        The EUR reduction amount.
    """
    if not (0.0 < portion <= 1.0):
        _log.warning("[TradeInvestment] reduce_partial_tp invalid portion %.4f from %s", portion, source)
        return 0.0

    current = float(trade.get("invested_eur", 0) or 0)
    total = float(trade.get("total_invested_eur", current) or current)

    if current <= 0:
        _log.warning("[TradeInvestment] reduce_partial_tp on zero invested (source=%s)", source)
        return 0.0

    reduction = current * portion
    trade["invested_eur"] = round(current - reduction, 4)
    # total_invested_eur is NEVER reduced
    _log.info(
        "[TradeInvestment] reduce_partial_tp %.0f%% → invested €%.2f→€%.2f, reduction €%.2f (source=%s)",
        portion * 100,
        current,
        trade["invested_eur"],
        reduction,
        source,
    )
    return round(reduction, 4)


def repair_negative(trade: Trade, market: str = "?") -> bool:
    """
    Repair negative invested_eur using initial_invested_eur (NOT config constant).

    Returns True if a repair was made.
    """
    invested = float(trade.get("invested_eur", 0) or 0)
    if invested >= 0:
        return False

    # Prefer initial_invested_eur, then total_invested_eur, then buy_price*amount
    initial = float(trade.get("initial_invested_eur", 0) or 0)
    total = float(trade.get("total_invested_eur", 0) or 0)
    buy_price = float(trade.get("buy_price", 0) or 0)
    amount = float(trade.get("amount", 0) or 0)

    if initial > 0:
        repair_value = initial
        src = "initial_invested_eur"
    elif total > 0:
        repair_value = total
        src = "total_invested_eur"
    elif buy_price > 0 and amount > 0:
        repair_value = buy_price * amount
        src = "buy_price*amount"
    else:
        _log.error("[TradeInvestment] Cannot repair negative invested_eur for %s – no source data", market)
        return False

    trade["invested_eur"] = round(repair_value, 4)
    _log.warning(
        "[TradeInvestment] REPAIR %s: invested_eur %.2f → %.2f (from %s)",
        market,
        invested,
        repair_value,
        src,
    )
    return True


def get_invested(trade: Trade) -> float:
    """Read invested_eur safely. Returns 0.0 if missing/invalid."""
    try:
        return float(trade.get("invested_eur", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def get_total_invested(trade: Trade) -> float:
    """Read total_invested_eur safely. Falls back to invested_eur."""
    try:
        val = float(trade.get("total_invested_eur", 0) or 0)
        if val > 0:
            return val
        return get_invested(trade)
    except (TypeError, ValueError):
        return get_invested(trade)
