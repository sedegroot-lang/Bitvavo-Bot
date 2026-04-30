"""bot.market_helpers — Market selection + pending-order + invested-cost utilities.

Extracted from `trailing_bot.py` (#066 batch 4). Self-contained helpers that
were previously module-level functions in the monolith. Access shared state via
`bot.shared.state`.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from bot.shared import state


def _log(msg: str, level: str = 'info') -> None:
    try:
        state.log(msg, level=level)
    except Exception:
        pass


def get_true_invested_eur(trade: Dict[str, Any], market: str = '') -> float:
    """BULLETPROOF invested_eur calculation.

    Returns the TRUE current invested EUR for a trade. Cross-checks stored
    invested_eur against buy_price * amount. If they diverge by >20%, uses
    buy_price * amount (always correct).
    """
    buy_price = float(trade.get('buy_price', 0) or 0)
    amount = float(trade.get('amount', 0) or 0)
    stored_invested = float(trade.get('invested_eur', 0) or 0)
    total_invested = float(trade.get('total_invested_eur', 0) or 0)

    computed = round(buy_price * amount, 4) if buy_price > 0 and amount > 0 else 0.0

    if stored_invested <= 0 and total_invested > 0:
        stored_invested = total_invested

    if stored_invested <= 0 and computed > 0:
        _log(f"[INVESTED FIX] {market}: No stored invested_eur, using computed €{computed:.2f}", level='warning')
        trade['invested_eur'] = computed
        if total_invested <= 0:
            trade['total_invested_eur'] = computed
        if float(trade.get('initial_invested_eur', 0) or 0) <= 0:
            trade['initial_invested_eur'] = computed
        return computed

    if stored_invested > 0 and computed > 0:
        divergence = abs(computed - stored_invested) / max(stored_invested, 0.01)
        if divergence > 0.20:
            _log(
                f"[INVESTED FIX] {market}: stored invested €{stored_invested:.2f} vs computed "
                f"€{computed:.2f} (divergence {divergence:.0%}) — CORRECTING invested_eur to computed",
                level='warning',
            )
            trade['invested_eur'] = computed
            # CRITICAL: never reduce total_invested_eur — it tracks cumulative cost basis.
            if total_invested <= 0:
                trade['total_invested_eur'] = computed
            if float(trade.get('initial_invested_eur', 0) or 0) <= 0:
                trade['initial_invested_eur'] = computed
            return computed

    return stored_invested if stored_invested > 0 else computed


def get_pending_bitvavo_orders() -> List[Dict[str, Any]]:
    """Return list of pending BUY orders from Bitvavo not yet in `open_trades`.

    Excludes grid trading orders to avoid conflicts.
    """
    try:
        get_active_grid_markets = getattr(state, 'get_active_grid_markets', lambda: set())
        grid_markets = get_active_grid_markets() or set()
        grid_order_ids: set = set()
        try:
            from modules.grid_trading import get_grid_manager
            gm = get_grid_manager()
            grid_order_ids = gm.get_grid_order_ids()
        except Exception:
            pass

        bitvavo = state.bitvavo
        open_trades = state.open_trades
        orders = state.safe_call(bitvavo.ordersOpen, {}) or []

        pending: List[Dict[str, Any]] = []
        for o in orders:
            try:
                if o.get('side') != 'buy':
                    continue
                market = o.get('market') or o.get('symbol')
                if not market or market in open_trades:
                    continue
                if market in grid_markets or o.get('orderId') in grid_order_ids:
                    continue
                status = str(o.get('status', '')).lower().replace('_', '').replace('-', '').strip()
                if status not in {'new', 'open', 'partiallyfilled', 'partially filled', 'awaitingtrigger'}:
                    continue
                created_ms = o.get('created', 0)
                age_sec = (time.time() * 1000 - created_ms) / 1000 if created_ms else 0
                pending.append({
                    'market': market,
                    'orderId': o.get('orderId'),
                    'amount': float(o.get('amount', 0) or 0),
                    'price': float(o.get('price', 0) or 0),
                    'status': o.get('status'),
                    'created': created_ms,
                    'age_seconds': age_sec,
                })
            except Exception:
                continue
        return pending
    except Exception as e:
        _log(f"Error getting pending Bitvavo orders: {e}", level='debug')
        return []


def count_pending_bitvavo_orders() -> int:
    return len(get_pending_bitvavo_orders())
