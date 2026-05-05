"""Extracted trade execution utilities from trailing_bot.py.

This module provides reusable trade execution helpers that reduce the
monolith's size and enable independent testing. The trailing_bot.py
delegates to these functions rather than duplicating logic.

Functions:
  - calculate_trade_value: Compute current value, P&L, and ROI
  - build_close_entry: Construct a standardized closed-trade dict
  - validate_trade_entry: Ensure a trade dict has all required fields
  - compute_trailing_stop: Calculate trailing stop price from config
  - compute_dca_next_price: Calculate next DCA trigger price
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple


def calculate_trade_value(
    trade: Dict[str, Any],
    current_price: float,
    *,
    fee_pct: float = 0.0025,
) -> Dict[str, float]:
    """Calculate current value, P&L, and ROI for a trade.

    Returns dict with: current_value, invested, pnl, pnl_pct, fee_estimate.
    """
    buy_price = float(trade.get("buy_price", 0) or 0)
    amount = float(trade.get("amount", 0) or 0)
    invested = float(trade.get("invested_eur", buy_price * amount) or (buy_price * amount))

    if amount <= 0 or buy_price <= 0:
        return {
            "current_value": 0.0,
            "invested": invested,
            "pnl": 0.0,
            "pnl_pct": 0.0,
            "fee_estimate": 0.0,
        }

    current_value = current_price * amount
    sell_fee = current_value * fee_pct
    buy_fee = invested * fee_pct
    fee_estimate = buy_fee + sell_fee

    pnl = current_value - invested - fee_estimate
    pnl_pct = (pnl / invested * 100) if invested > 0 else 0.0

    return {
        "current_value": current_value,
        "invested": invested,
        "pnl": round(pnl, 4),
        "pnl_pct": round(pnl_pct, 4),
        "fee_estimate": round(fee_estimate, 4),
    }


def build_close_entry(
    market: str,
    trade: Dict[str, Any],
    sell_price: float,
    reason: str,
    *,
    fee_pct: float = 0.0025,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a standardized closed-trade entry.

    Uses invested_eur as the single source of truth for P&L calculation.
    """
    buy_price = float(trade.get("buy_price", 0) or 0)
    amount = float(trade.get("amount", 0) or 0)
    invested = float(trade.get("invested_eur", buy_price * amount) or (buy_price * amount))

    revenue = sell_price * amount
    total_fees = (invested + revenue) * fee_pct
    profit = revenue - invested - total_fees

    entry = {
        "market": market,
        "buy_price": buy_price,
        "sell_price": sell_price,
        "amount": amount,
        "invested_eur": invested,
        "revenue_eur": round(revenue, 4),
        "profit": round(profit, 4),
        "profit_pct": round((profit / invested * 100) if invested > 0 else 0.0, 4),
        "fees_eur": round(total_fees, 4),
        "timestamp": time.time(),
        "reason": reason,
        "dca_buys": int(trade.get("dca_buys", 0) or 0),
    }

    if extra:
        entry.update(extra)

    return entry


def validate_trade_entry(trade: Dict[str, Any]) -> Tuple[bool, list]:
    """Validate that a trade dict has all required fields.

    Returns (is_valid, list_of_issues).
    """
    issues = []

    required = {"buy_price", "amount"}
    for field in required:
        if field not in trade:
            issues.append(f"Missing required field: {field}")

    # Numeric checks
    for field in ("buy_price", "amount"):
        val = trade.get(field)
        if val is not None:
            try:
                f = float(val)
                if f < 0:
                    issues.append(f"{field}={f} is negative")
            except (TypeError, ValueError):
                issues.append(f"{field}={val!r} not numeric")

    return len(issues) == 0, issues


def compute_trailing_stop(
    highest_price: float,
    trailing_pct: float,
) -> float:
    """Calculate trailing stop price from highest price and trailing %."""
    if highest_price <= 0 or trailing_pct <= 0:
        return 0.0
    return highest_price * (1 - trailing_pct)


def compute_dca_next_price(
    buy_price: float,
    drop_pct: float,
    dca_level: int = 0,
    step_multiplier: float = 1.0,
) -> float:
    """Calculate next DCA trigger price.

    Each successive DCA level drops further by step_multiplier.
    """
    if buy_price <= 0 or drop_pct <= 0:
        return 0.0
    effective_drop = drop_pct * (step_multiplier**dca_level)
    return buy_price * (1 - effective_drop)


def compute_partial_tp_price(
    buy_price: float,
    tp_pct: float,
    fee_pct: float = 0.0025,
) -> float:
    """Calculate partial take-profit price that guarantees net profit after fees."""
    if buy_price <= 0 or tp_pct <= 0:
        return 0.0
    # Need to cover buy+sell fees plus target profit
    min_price = buy_price * (1 + tp_pct + 2 * fee_pct)
    return round(min_price, 8)
