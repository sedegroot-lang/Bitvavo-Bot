# -*- coding: utf-8 -*-
"""Portfolio snapshot, trade value computation, and account overview.

Extracted from trailing_bot.py to reduce monolith size.
All shared state accessed via ``bot.shared.state``.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


def _get_state():
    """Lazy import to avoid circular imports at module load time."""
    from bot.shared import state

    return state


# ─── Trade-value helpers ────────────────────────────────────────────


def resolve_dust_threshold(override: Optional[float] = None) -> Optional[float]:
    S = _get_state()
    value = override if override is not None else S.DUST_TRADE_THRESHOLD_EUR
    try:
        value = float(value)
    except Exception:
        value = float(S.DUST_TRADE_THRESHOLD_EUR)
    if value <= 0:
        return None
    return value


def compute_trade_value_eur(
    market: str,
    trade: Dict[str, Any],
    *,
    price_cache: Optional[Dict[str, Optional[float]]] = None,
) -> Tuple[Optional[float], Optional[float]]:
    S = _get_state()
    from bot.helpers import coerce_positive_float, safe_mul

    if not isinstance(trade, dict):
        return None, None
    try:
        amount = float(trade.get("amount", 0.0) or 0.0)
    except Exception:
        amount = 0.0
    invested_val = coerce_positive_float(trade.get("invested_eur"))
    cache = price_cache if price_cache is not None else None
    if amount <= 0:
        return invested_val, None
    price = None
    if cache is not None and market in cache:
        price = cache.get(market)
    if price is None:
        price = S.get_current_price(market)
        if cache is not None:
            cache[market] = price
    resolved_price = price
    if resolved_price is None:
        fallback = coerce_positive_float(trade.get("buy_price") or trade.get("entry_price"))
        if fallback is not None:
            resolved_price = fallback
            if cache is not None:
                cache[market] = resolved_price
    exposure = safe_mul(amount, resolved_price)
    if exposure is None:
        return invested_val, resolved_price
    try:
        exp_float = float(exposure)
    except Exception:
        exp_float = None
    return exp_float, resolved_price


def iter_trade_values(price_cache: Optional[Dict[str, Optional[float]]] = None):
    """Yield (market, trade, exposure_eur, price) for all open trades."""
    S = _get_state()
    cache = price_cache if price_cache is not None else {}
    with S.trades_lock:
        snapshot = list((S.open_trades or {}).items())
    for market, trade in snapshot:
        exposure, resolved_price = compute_trade_value_eur(market, trade, price_cache=cache)
        if exposure is None:
            continue
        yield market, trade, float(exposure), resolved_price


# ─── Counting helpers ───────────────────────────────────────────────


def count_active_open_trades(
    threshold: Optional[float] = None,
    *,
    price_cache: Optional[Dict[str, Optional[float]]] = None,
) -> int:
    effective = resolve_dust_threshold(threshold)
    count = 0
    for _, _, value, _ in iter_trade_values(price_cache=price_cache):
        if effective is not None and value < effective:
            continue
        count += 1
    return count


def count_dust_trades(threshold: Optional[float] = None) -> int:
    effective = resolve_dust_threshold(threshold)
    if effective is None:
        return 0
    count = 0
    for _, _, value, _ in iter_trade_values():
        if value < effective:
            count += 1
    return count


def current_open_exposure_eur(include_dust: bool = False) -> float:
    effective = None if include_dust else resolve_dust_threshold()
    total = 0.0
    for _, _, value, _ in iter_trade_values():
        if effective is not None and value < effective:
            continue
        total += value
    return float(total)


def estimate_max_eur_per_trade() -> Optional[float]:
    S = _get_state()
    try:
        base_amount = float(S.BASE_AMOUNT_EUR)
        if S.AUTO_USE_FULL_BALANCE:
            return float(min(S.FULL_BALANCE_MAX_EUR, base_amount))
        return base_amount
    except Exception:
        return None


def estimate_max_total_eur() -> Optional[float]:
    S = _get_state()
    try:
        return float(S.CONFIG.get("MAX_TOTAL_EXPOSURE_EUR", S.MAX_TOTAL_EXPOSURE_EUR))
    except Exception:
        return None


# ─── Analysis ───────────────────────────────────────────────────────


def analyse_trades(trades) -> Tuple[float, float, float, float]:
    S = _get_state()
    try:
        if not trades:
            return 0.0, 0.0, 0.0, 0.0
        profits = [float(t.get("profit", 0) or 0) for t in trades]
        wins = [p for p in profits if p > 0]
        losses = [p for p in profits if p <= 0]
        win_ratio = (len(wins) / len(profits)) if profits else 0.0
        avg_win = (sum(wins) / len(wins)) if wins else 0.0
        avg_loss = (sum(losses) / len(losses)) if losses else 0.0
        avg_profit = (sum(profits) / len(profits)) if profits else 0.0
        return float(win_ratio), float(avg_win), float(avg_loss), float(avg_profit)
    except Exception as e:
        S.log(f"analyse_trades failed: {e}", level="error")
        return 0.0, 0.0, 0.0, 0.0


# ─── Portfolio snapshot ─────────────────────────────────────────────


def build_portfolio_snapshot() -> Dict[str, Any]:
    S = _get_state()
    from modules.trading_risk import segment_for_market

    total = 0.0
    per_market: Dict[str, float] = {}
    per_base: Dict[str, float] = {}
    per_segment: Dict[str, float] = {}
    dust_trades: Dict[str, Dict[str, Any]] = {}
    threshold = resolve_dust_threshold()
    for market, trade, exposure, price in iter_trade_values():
        if threshold is not None and exposure < threshold:
            try:
                amount = float(trade.get("amount", 0.0) or 0.0)
            except Exception:
                amount = 0.0
            dust_trades[market] = {
                "value_eur": exposure,
                "amount": amount,
                "buy_price": trade.get("buy_price"),
                "current_price": price,
            }
            continue
        total += exposure
        per_market[market] = exposure
        base = market.split("-", 1)[0]
        per_base[base] = per_base.get(base, 0.0) + exposure
        seg = segment_for_market(market, S.CONFIG)
        per_segment[seg] = per_segment.get(seg, 0.0) + exposure
    active_count = len(per_market)
    return {
        "ts": int(time.time()),
        "total_exposure_eur": total,
        "open_trade_count": active_count,
        "dust_trade_count": len(dust_trades),
        "per_market": per_market,
        "per_base": per_base,
        "per_segment": per_segment,
        "dust_trades": dust_trades,
    }


def write_portfolio_snapshot() -> Optional[Dict[str, Any]]:
    S = _get_state()
    try:
        snapshot = build_portfolio_snapshot()
        S.write_json_locked(str(S.PORTFOLIO_SNAPSHOT_FILE), snapshot)
        return snapshot
    except Exception:
        return None


# ─── Account overview ───────────────────────────────────────────────


def build_account_overview(
    *,
    balances: Optional[List[Dict[str, Any]]] = None,
    snapshot: Optional[Dict[str, Any]] = None,
    eur_balance: Optional[float] = None,
) -> Dict[str, Any]:
    S = _get_state()

    def _to_float(value: Any) -> Optional[float]:
        try:
            return float(value)
        except Exception:
            return None

    now = int(time.time())
    updated_at = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    open_value = None
    open_count = None
    snapshot_ts = None
    if isinstance(snapshot, dict):
        open_value = _to_float(snapshot.get("total_exposure_eur"))
        open_count_raw = snapshot.get("open_trade_count")
        try:
            open_count = int(open_count_raw)
        except Exception:
            open_count = None
        snapshot_ts = snapshot.get("ts")
    if open_value is None:
        open_value = current_open_exposure_eur()
    if open_count is None:
        open_count = count_active_open_trades(threshold=S.DUST_TRADE_THRESHOLD_EUR)

    eur_available = _to_float(eur_balance)
    eur_in_orders: Optional[float] = None
    total_account_value: Optional[float] = None
    conversion_failures: list[str] = []

    if balances:
        total_account_value = 0.0
        price_cache: Dict[str, Optional[float]] = {}
        for entry in balances:
            if not isinstance(entry, dict):
                continue
            symbol = str(entry.get("symbol") or "").upper().strip()
            if not symbol:
                continue
            available = _to_float(entry.get("available"))
            if available is None:
                available = _to_float(entry.get("balance"))
            if available is None:
                available = 0.0
            in_order = _to_float(entry.get("inOrder"))
            if in_order is None:
                in_order = _to_float(entry.get("inorder"))
            if in_order is None:
                in_order = 0.0
            total_amount = max(0.0, available + in_order)
            if symbol == "EUR":
                if eur_available is None:
                    eur_available = available
                eur_in_orders = in_order
                total_account_value += total_amount
                continue
            if total_amount <= 0:
                continue
            price = price_cache.get(symbol)
            if price is None:
                market = f"{symbol}-EUR"
                price = S.get_current_price(market)
                price_cache[symbol] = price
            if price:
                total_account_value += total_amount * price
            else:
                if len(conversion_failures) < 5:
                    conversion_failures.append(symbol)

    payload = {
        "ts": now,
        "updated_at": updated_at,
        "snapshot_ts": snapshot_ts,
        "eur_available": eur_available,
        "eur_in_orders": eur_in_orders,
        "open_trade_value_eur": open_value,
        "open_trade_count": open_count,
        "total_account_value_eur": total_account_value,
        "sources": {
            "balances": bool(balances),
            "snapshot": snapshot is not None,
        },
    }
    if conversion_failures:
        payload["missing_conversion_symbols"] = conversion_failures
    return payload


def write_account_overview(
    *,
    balances: Optional[List[Dict[str, Any]]] = None,
    snapshot: Optional[Dict[str, Any]] = None,
    eur_balance: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    S = _get_state()
    try:
        overview = build_account_overview(
            balances=balances,
            snapshot=snapshot,
            eur_balance=eur_balance,
        )
        S.write_json_locked(str(S.ACCOUNT_OVERVIEW_FILE), overview)
        return overview
    except Exception as exc:
        # FIX #080: was silently swallowed → impossible to diagnose stale account_overview.
        try:
            S.log(f"[ERROR] write_account_overview failed: {exc}", level="error")
        except Exception:
            pass
        return None
