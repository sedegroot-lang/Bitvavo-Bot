"""
Invested EUR Sync Module - Automatically syncs invested_eur with Bitvavo API.
Ensures trade_log.json always has accurate cost basis data.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

from core.trade_investment import set_initial as _ti_set_initial
from modules.cost_basis import derive_cost_basis
from modules.logging_utils import log

if TYPE_CHECKING:
    from python_bitvavo_api.bitvavo import Bitvavo

# Track last sync time per market to avoid excessive API calls
_LAST_SYNC: dict[str, float] = {}
_SYNC_COOLDOWN = 1800  # 30 minutes between syncs per market


def sync_invested_eur(
    bitvavo_client: "Bitvavo",
    open_trades: dict,
    *,
    force: bool = False,
    tolerance: float = 0.50,
    silent: bool = False,
) -> int:
    """
    Sync invested_eur values for all open trades with Bitvavo API.

    Args:
        bitvavo_client: Bitvavo API client
        open_trades: Dict of open trades (will be modified in-place)
        force: If True, sync all trades regardless of cooldown
        tolerance: EUR difference threshold to trigger update (default 0.50)
        silent: If True, suppress log output

    Returns:
        Number of trades that were updated
    """
    if not bitvavo_client or not open_trades:
        return 0

    now = time.time()
    fixes_made = 0

    for market, trade in open_trades.items():
        # Check cooldown unless force is True
        if not force:
            last_sync = _LAST_SYNC.get(market, 0)
            if (now - last_sync) < _SYNC_COOLDOWN:
                continue

        amount = float(trade.get("amount", 0) or 0)
        if amount <= 0:
            continue

        try:
            result = derive_cost_basis(bitvavo_client, market, amount, tolerance=0.10)
        except Exception as e:
            if not silent:
                log(f"[InvestedSync] {market}: derive failed - {e}", level="debug")
            continue

        if not result or result.invested_eur <= 0:
            continue

        _LAST_SYNC[market] = now

        # CRITICAL FIX: invested_eur is IMMUTABLE after initial buy
        # NEVER update invested_eur from API - it causes corruption with historical trades
        # Only update if invested_eur is missing or zero (truly new trade)
        old_invested = float(trade.get("invested_eur", 0) or 0)
        initial_invested = float(trade.get("initial_invested_eur", 0) or 0)
        old_dca = int(trade.get("dca_buys", 0) or 0)

        # Only update invested_eur if it's missing/zero AND initial_invested_eur is also missing
        # This prevents overwriting valid data with corrupted API calculations
        if old_invested <= 0 and initial_invested <= 0:
            if not silent:
                log(f"[InvestedSync] {market}: Setting missing invested_eur to {result.invested_eur:.2f}")
            _ti_set_initial(trade, result.invested_eur, source=f"invested_sync_{market}")
            fixes_made += 1
        elif old_invested <= 0 and initial_invested > 0:
            # CRITICAL FIX: Do NOT blindly restore from initial_invested_eur.
            # If partial TPs have reduced invested_eur to 0 or below, restoring
            # initial would UNDO those legitimate reductions.
            # Instead, use total_invested minus partial_tp_returned as best estimate.
            partial_returned = float(trade.get("partial_tp_returned_eur", 0) or 0)
            total_inv = float(trade.get("total_invested_eur", initial_invested) or initial_invested)
            restored = max(total_inv - partial_returned, 0.01)
            if not silent:
                log(
                    f"[InvestedSync] {market}: Restoring invested_eur to {restored:.2f} "
                    f"(total={total_inv:.2f} - returned={partial_returned:.2f})"
                )
            trade["invested_eur"] = restored
            fixes_made += 1

        # Update buy_price and opened_ts (these are safe to update)
        if result.avg_price > 0 and (not trade.get("buy_price") or float(trade.get("buy_price", 0)) <= 0):
            trade["buy_price"] = result.avg_price
        if result.earliest_timestamp and not trade.get("opened_ts"):
            trade["opened_ts"] = result.earliest_timestamp

        # NEVER update dca_buys from API - this causes massive inflation
        # DCA buys should ONLY be updated when an actual DCA buy is executed

    return fixes_made


def sync_single_trade(
    bitvavo_client: "Bitvavo",
    market: str,
    trade: dict,
    *,
    force: bool = False,
) -> bool:
    """
    Sync invested_eur for a single trade.

    Returns:
        True if trade was updated, False otherwise
    """
    if not bitvavo_client or not trade:
        return False

    now = time.time()

    # Check cooldown unless force
    if not force:
        last_sync = _LAST_SYNC.get(market, 0)
        if (now - last_sync) < _SYNC_COOLDOWN:
            return False

    amount = float(trade.get("amount", 0) or 0)
    if amount <= 0:
        return False

    try:
        result = derive_cost_basis(bitvavo_client, market, amount, tolerance=0.10)
    except Exception:
        return False

    if not result or result.invested_eur <= 0:
        return False

    _LAST_SYNC[market] = now

    # CRITICAL FIX: invested_eur is IMMUTABLE after initial buy
    # Only update if truly missing, never overwrite existing values
    old_invested = float(trade.get("invested_eur", 0) or 0)
    initial_invested = float(trade.get("initial_invested_eur", 0) or 0)

    if old_invested <= 0 and initial_invested <= 0:
        # Only set if completely missing
        _ti_set_initial(trade, result.invested_eur, source=f"invested_sync_single_{market}")
        if result.earliest_timestamp:
            trade["opened_ts"] = result.earliest_timestamp
        return True
    elif old_invested <= 0 and initial_invested > 0:
        # CRITICAL FIX: Don't blindly restore from initial – partial TPs may have
        # legitimately reduced invested_eur. Use total minus returned.
        partial_returned = float(trade.get("partial_tp_returned_eur", 0) or 0)
        total_inv = float(trade.get("total_invested_eur", initial_invested) or initial_invested)
        trade["invested_eur"] = max(total_inv - partial_returned, 0.01)
        return True

    # NEVER update dca_buys from API
    return False


def clear_sync_cache(market: Optional[str] = None) -> None:
    """Clear sync cooldown cache for a market or all markets."""
    global _LAST_SYNC
    if market:
        _LAST_SYNC.pop(market, None)
    else:
        _LAST_SYNC.clear()
