from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


@dataclass
class CostBasisResult:
    invested_eur: float
    avg_price: float
    position_amount: float
    position_cost: float
    amount_diff: float
    fills_used: int
    earliest_timestamp: float | None
    buy_order_count: int


def _normalize_ts(raw: Any) -> float:
    try:
        value = float(raw or 0.0)
    except Exception:
        return 0.0
    if value > 1_000_000_000_000:
        value /= 1000.0
    return value if value > 0 else 0.0


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        num = float(value)
    except Exception:
        return default
    if not (num == num):
        return default
    return num


def _compute_cost_basis_from_fills(
    fills: Iterable[Dict[str, Any]],
    *,
    market: str,
    target_amount: float,
    tolerance: float,
) -> CostBasisResult | None:
    if target_amount <= 0:
        return None
    market_base = market.split("-")[0].upper() if market else ""
    fills_sorted = sorted(fills, key=lambda item: _normalize_ts(item.get("timestamp")))
    pos_amount = 0.0
    pos_cost = 0.0
    earliest_ts: float | None = None
    buy_order_ids: Set[str] = set()

    for fill in fills_sorted:
        side = str(fill.get("side") or "").lower()
        price = _to_float(fill.get("price"))
        amount = abs(_to_float(fill.get("amount")))
        fee = abs(_to_float(fill.get("fee")))
        fee_curr = str(fill.get("feeCurrency") or "").upper()
        if price <= 0 or amount <= 0:
            continue
        if side == "buy":
            base_delta = amount
            if fee_curr == market_base and fee > 0:
                base_delta = max(0.0, base_delta - fee)
            eur_cost = price * amount
            if fee_curr == "EUR":
                eur_cost += fee
            pos_cost += eur_cost
            pos_amount += base_delta
            if base_delta > 0 and earliest_ts is None:
                earliest_ts = _normalize_ts(fill.get("timestamp"))
            if base_delta > 0:
                order_id = str(
                    fill.get("orderId")
                    or fill.get("orderID")
                    or fill.get("order_id")
                    or fill.get("order")
                    or fill.get("id")
                    or fill.get("tradeId")
                    or fill.get("tradeid")
                    or ""
                )
                if not order_id:
                    order_id = f"{_normalize_ts(fill.get('timestamp'))}-{price}-{amount}"
                buy_order_ids.add(order_id)
        elif side == "sell":
            base_delta = amount
            if fee_curr == market_base and fee > 0:
                base_delta = max(0.0, base_delta - fee)
            if base_delta <= 0 or pos_amount <= 0:
                continue
            sold = min(base_delta, pos_amount)
            if sold <= 0:
                continue
            avg_cost = pos_cost / pos_amount if pos_amount else 0.0
            pos_amount -= sold
            pos_cost -= avg_cost * sold
            if pos_amount <= 1e-8:
                pos_amount = 0.0
                pos_cost = 0.0
                buy_order_ids.clear()
    if pos_amount <= 0 or pos_cost <= 0:
        return None
    amount_diff = abs(pos_amount - target_amount)
    tolerance_abs = max(1e-8, target_amount * tolerance)
    invested = pos_cost
    if amount_diff > tolerance_abs and pos_amount > 0:
        avg_cost = pos_cost / pos_amount
        invested = avg_cost * target_amount
    avg_price = invested / target_amount if target_amount > 0 else 0.0
    return CostBasisResult(
        invested_eur=invested,
        avg_price=avg_price,
        position_amount=pos_amount,
        position_cost=pos_cost,
        amount_diff=amount_diff,
        fills_used=len(fills_sorted),
        earliest_timestamp=earliest_ts,
        buy_order_count=len(buy_order_ids),
    )


def _fetch_trades_with_paging(
    bitvavo: Any,
    market: str,
    *,
    start_ts: float | None,
    limit: int,
    max_iterations: int,
) -> List[Dict[str, Any]]:
    seen: Set[Tuple[str, float, str, str, str]] = set()
    accum: List[Dict[str, Any]] = []
    end_ms: Optional[int] = None
    for _ in range(max_iterations):
        params: Dict[str, Any] = {"limit": limit}
        if start_ts is not None and start_ts > 0:
            params["start"] = int(start_ts * 1000)
        if end_ms is not None and end_ms > 0:
            params["end"] = end_ms
        try:
            batch = bitvavo.trades(market, params)
        except Exception:
            break
        if isinstance(batch, dict) or not batch:
            break
        new_items = 0
        for fill in batch:
            key = (
                str(fill.get("id") or fill.get("tradeId") or fill.get("tradeid") or fill.get("orderId") or ""),
                _normalize_ts(fill.get("timestamp")),
                str(fill.get("side") or ""),
                str(fill.get("amount") or ""),
                str(fill.get("price") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            accum.append(fill)
            new_items += 1
        if len(batch) < limit or new_items == 0:
            break
        ts_values = [
            _normalize_ts(item.get("timestamp"))
            for item in batch
            if item.get("timestamp") is not None
        ]
        if not ts_values:
            break
        oldest = min(ts_values)
        if oldest <= 0:
            break
        end_ms = int((oldest - 1) * 1000)
        start_ts = None
    return accum


def derive_cost_basis(
    bitvavo: Any,
    market: str,
    target_amount: float,
    *,
    opened_ts: float | None = None,
    tolerance: float = 0.02,
    max_iterations: int = 5,
    batch_limit: int = 1000,
) -> CostBasisResult | None:
    if target_amount <= 0:
        return None
    start_ts: float | None = None
    if opened_ts and opened_ts > 0:
        # START FROM opened_ts, not 7 days before - only count trades from when position opened
        start_ts = float(opened_ts)
    fills = _fetch_trades_with_paging(
        bitvavo,
        market,
        start_ts=start_ts,
        limit=batch_limit,
        max_iterations=max_iterations,
    )
    result = _compute_cost_basis_from_fills(
        fills,
        market=market,
        target_amount=target_amount,
        tolerance=tolerance,
    )
    tolerance_abs = max(1e-8, target_amount * tolerance)
    if result and result.amount_diff <= tolerance_abs:
        return result
    extra = _fetch_trades_with_paging(
        bitvavo,
        market,
        start_ts=None,
        limit=batch_limit,
        max_iterations=max_iterations,
    )
    if extra:
        combined: Dict[Tuple[str, float, str, str, str], Dict[str, Any]] = {}
        for fill in fills + extra:
            key = (
                str(fill.get("id") or fill.get("tradeId") or fill.get("tradeid") or fill.get("orderId") or ""),
                _normalize_ts(fill.get("timestamp")),
                str(fill.get("side") or ""),
                str(fill.get("amount") or ""),
                str(fill.get("price") or ""),
            )
            combined[key] = fill
        merged = list(combined.values())
        result = _compute_cost_basis_from_fills(
            merged,
            market=market,
            target_amount=target_amount,
            tolerance=tolerance,
        )
    return result


__all__ = ["CostBasisResult", "derive_cost_basis"]
