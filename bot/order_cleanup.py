"""Open BUY order cleanup.

Two responsibilities, both extracted from trailing_bot.py monolith:
    * cancel_open_buys_if_capped — proactively cancels outstanding buy orders
      when (open + reserved + pending) >= MAX_OPEN_TRADES so we never deadlock.
    * cancel_open_buys_by_age — cancels stale buy limit orders that are older
      than LIMIT_ORDER_TIMEOUT_SECONDS.

Both functions are best-effort and log+continue on errors. Grid-trading orders
are explicitly protected via market name + orderId allowlist.
"""

from __future__ import annotations

import statistics
import time
from typing import List, Set, Tuple

from bot.shared import state

_STATUS_OPEN_LIKE = {
    'new', 'open', 'partiallyfilled', 'partially filled', 'awaitingtrigger',
}
_TIMESTAMP_KEYS: Tuple[str, ...] = (
    'created', 'createdAt', 'timestamp', 'ts', 'time', 'lastUpdate', 'lastUpdated',
)


def _grid_protection() -> Tuple[Set[str], Set[str]]:
    """Return (grid_markets, grid_order_ids) — both safe defaults on failure."""
    try:
        grid_markets = set(state.get_active_grid_markets() or set())
    except Exception:
        grid_markets = set()
    grid_order_ids: Set[str] = set()
    try:
        from modules.grid_trading import get_grid_manager  # noqa: WPS433  (lazy)
        gm = get_grid_manager()
        if gm is not None:
            grid_order_ids = set(gm.get_grid_order_ids() or set())
    except Exception:
        pass
    return grid_markets, grid_order_ids


def _cancel_one(market: str, order_id: str) -> bool:
    """Cancel a single order, returns True on success."""
    try:
        if state.OPERATOR_ID:
            state.bitvavo.cancelOrder(market, order_id, operatorId=str(state.OPERATOR_ID))
        else:
            state.safe_call(state.bitvavo.cancelOrder, market, order_id)
        return True
    except Exception as exc:
        state.log(f"Failed to cancel order {order_id} for {market}: {exc}", level='error')
        return False


def _publish_metrics(payload: dict, source: str) -> None:
    try:
        if state.metrics_collector:
            state.metrics_collector.publish(payload, labels={'source': source})
    except Exception as exc:
        state.log(f"metrics publish failed for {source}: {exc}", level='warning')


def cancel_open_buys_if_capped() -> None:
    """Cancel buy orders for markets we are not yet long in when slot cap is reached."""
    try:
        max_trades = max(1, int(state.CONFIG.get('MAX_OPEN_TRADES', 5) or 5))
        # Dust threshold lives on state when set by trailing_bot init; fall back to 0.
        dust_thr = float(getattr(state, 'DUST_TRADE_THRESHOLD_EUR', 0.0) or 0.0)
        try:
            current = int(state.count_active_open_trades(threshold=dust_thr))
        except TypeError:
            current = int(state.count_active_open_trades())
        reserved = int(state._get_pending_count())
        pending_orders = int(state.count_pending_bitvavo_orders())
        if (current + reserved + pending_orders) < max_trades:
            return

        grid_markets, grid_order_ids = _grid_protection()
        orders = state.safe_call(state.bitvavo.ordersOpen, {}) or []
        to_cancel: List[Tuple[str, str]] = []
        for o in orders:
            try:
                if o.get('side') != 'buy':
                    continue
                market = o.get('market') or o.get('symbol')
                if not market or market in (state.open_trades or {}):
                    continue
                if market in grid_markets or o.get('orderId') in grid_order_ids:
                    continue
                status = str(o.get('status', '')).lower()
                if status not in _STATUS_OPEN_LIKE:
                    continue
                to_cancel.append((o.get('orderId'), market))
            except Exception:
                continue

        success = 0
        failed = 0
        for order_id, market in to_cancel:
            if _cancel_one(market, order_id):
                state.log(f"Canceled open BUY order {order_id} for {market} due to cap reached", level='warning')
                success += 1
            else:
                failed += 1

        if success or failed:
            _publish_metrics(
                {
                    'cancel_if_capped_attempts': float(len(to_cancel)),
                    'cancel_if_capped_success': float(success),
                    'cancel_if_capped_fail': float(failed),
                },
                source='cancel_if_capped',
            )
    except Exception as exc:
        state.log(f"cancel_open_buys_if_capped error: {exc}", level='error')


def cancel_open_buys_by_age() -> None:
    """Cancel BUY limit orders older than LIMIT_ORDER_TIMEOUT_SECONDS."""
    try:
        timeout = int(state.CONFIG.get('LIMIT_ORDER_TIMEOUT_SECONDS', 0) or 0)
        if timeout <= 0:
            return

        grid_markets, grid_order_ids = _grid_protection()
        orders = state.safe_call(state.bitvavo.ordersOpen, {}) or []
        now = time.time()

        to_cancel: List[Tuple[str, str, float]] = []
        for o in orders:
            try:
                if o.get('side') != 'buy':
                    continue
                market = o.get('market') or o.get('symbol')
                if not market or market in (state.open_trades or {}):
                    continue
                if market in grid_markets or o.get('orderId') in grid_order_ids:
                    continue
                status = str(o.get('status', '')).lower().replace('_', '').replace('-', '').strip()
                if status not in _STATUS_OPEN_LIKE:
                    continue
                order_type = str(o.get('type', '')).lower()
                if order_type and order_type != 'limit':
                    continue
                created_ms = None
                for key in _TIMESTAMP_KEYS:
                    raw = o.get(key)
                    if raw is None:
                        continue
                    try:
                        created_ms = int(raw)
                        break
                    except (TypeError, ValueError):
                        try:
                            created_ms = int(float(raw))
                            break
                        except (TypeError, ValueError):
                            continue
                if not created_ms:
                    if not getattr(cancel_open_buys_by_age, '_missing_ts_logged', False):
                        state.log(
                            f"Skip cancel_open_buys_by_age: no timestamp for order "
                            f"{o.get('orderId')} ({market})",
                            level='debug',
                        )
                        cancel_open_buys_by_age._missing_ts_logged = True  # type: ignore[attr-defined]
                    continue
                age = now - (created_ms / 1000.0)
                if age >= timeout:
                    to_cancel.append((o.get('orderId'), market, age))
            except Exception:
                continue

        success = 0
        failed = 0
        ages: List[float] = []
        for order_id, market, age in to_cancel:
            if _cancel_one(market, order_id):
                state.log(
                    f"Canceled open BUY order {order_id} for {market} due to "
                    f"timeout ({int(age)}s >= {timeout}s)",
                    level='warning',
                )
                success += 1
                ages.append(float(age))
            else:
                failed += 1

        if success or failed:
            payload = {
                'cancel_age_attempts': float(len(to_cancel)),
                'cancel_age_success': float(success),
                'cancel_age_fail': float(failed),
            }
            if ages:
                payload['cancel_age_avg_s'] = float(statistics.mean(ages))
                payload['cancel_age_max_s'] = float(max(ages))
            _publish_metrics(payload, source='cancel_by_age')
    except Exception as exc:
        state.log(f"cancel_open_buys_by_age error: {exc}", level='error')
