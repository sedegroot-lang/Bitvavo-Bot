from __future__ import annotations

from collections import deque
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


def _fifo_remove(lots: deque, qty: float) -> float:
    """Remove *qty* units from the front of the FIFO lot queue.

    Returns the total EUR cost removed.
    """
    removed_cost = 0.0
    remaining = qty
    while remaining > 1e-12 and lots:
        lot = lots[0]  # [amount, cost_per_unit, timestamp, order_id]
        lot_amt = lot[0]
        lot_cpu = lot[1]
        if lot_amt <= remaining + 1e-12:
            lots.popleft()
            removed_cost += lot_amt * lot_cpu
            remaining -= lot_amt
        else:
            lot[0] = lot_amt - remaining
            removed_cost += remaining * lot_cpu
            remaining = 0.0
    return removed_cost


def _compute_cost_basis_from_fills(
    fills: Iterable[Dict[str, Any]],
    *,
    market: str,
    target_amount: float,
    tolerance: float,
) -> CostBasisResult | None:
    """Compute cost basis using true FIFO lot tracking.

    FIX #009: Replaced average-cost sell deduction with per-lot FIFO.
    Average cost caused residual cost from old buy/sell cycles to bleed
    into the current position when computed position > actual balance
    (e.g. due to fills missing from the API).  True FIFO correctly
    attributes cost to the most recent purchases.
    """
    if target_amount <= 0:
        return None
    market_base = market.split("-")[0].upper() if market else ""
    fills_sorted = sorted(fills, key=lambda item: _normalize_ts(item.get("timestamp")))

    # FIFO lot queue: each entry is [remaining_amount, cost_per_unit, timestamp, order_id]
    lots: deque = deque()
    pos_amount = 0.0
    pos_cost = 0.0

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
                cost_per_unit = eur_cost / base_delta
                lots.append([base_delta, cost_per_unit, _normalize_ts(fill.get("timestamp")), order_id])
                pos_cost += eur_cost
                pos_amount += base_delta
        elif side == "sell":
            base_delta = amount
            if fee_curr == market_base and fee > 0:
                base_delta = max(0.0, base_delta - fee)
            if base_delta <= 0 or pos_amount <= 0:
                continue
            sold = min(base_delta, pos_amount)
            if sold <= 0:
                continue
            removed_cost = _fifo_remove(lots, sold)
            pos_amount -= sold
            pos_cost -= removed_cost
            # FIX #006: generous dust threshold to prevent old position
            # costs from bleeding into current position's cost basis.
            if pos_amount < 1e-6 or (pos_amount > 0 and pos_cost < 1.0):
                pos_amount = 0.0
                pos_cost = 0.0
                lots.clear()

    if pos_amount <= 0 or pos_cost <= 0:
        return None

    # FIX #009: When computed position exceeds actual balance (phantom
    # holdings due to missing sells in API), FIFO-remove the excess
    # oldest lots so cost basis reflects only the most recent purchases.
    amount_diff = abs(pos_amount - target_amount)
    tolerance_abs = max(1e-8, target_amount * tolerance)
    if pos_amount > target_amount + tolerance_abs:
        excess = pos_amount - target_amount
        removed_cost = _fifo_remove(lots, excess)
        pos_amount -= excess
        pos_cost -= removed_cost
        amount_diff = abs(pos_amount - target_amount)

    invested = pos_cost
    if amount_diff > tolerance_abs and pos_amount > 0:
        avg_cost = pos_cost / pos_amount
        invested = avg_cost * target_amount
    avg_price = invested / target_amount if target_amount > 0 else 0.0

    # Derive earliest_ts and buy_order_ids from remaining lots
    earliest_ts: float | None = None
    buy_order_ids: Set[str] = set()
    for lot in lots:
        if lot[0] > 1e-12:
            if earliest_ts is None or lot[2] < earliest_ts:
                earliest_ts = lot[2]
            buy_order_ids.add(lot[3])

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
    """Derive cost basis from Bitvavo order history.

    ALWAYS fetches full trade history (ignores opened_ts) to prevent
    missing earlier buys that are part of the current position.
    The opened_ts parameter is kept for API compatibility but NOT used
    as a filter — see FIX_LOG.md #001 for why.
    """
    if target_amount <= 0:
        return None
    # ALWAYS fetch full history — never filter by opened_ts.
    # opened_ts was previously used as start_ts filter, but this caused
    # external buys before the recorded opened_ts to be missed, leading
    # to wrong cost basis (invested_eur too low).  See FIX_LOG.md #001.
    fills = _fetch_trades_with_paging(
        bitvavo,
        market,
        start_ts=None,
        limit=batch_limit,
        max_iterations=max_iterations,
    )
    result = _compute_cost_basis_from_fills(
        fills,
        market=market,
        target_amount=target_amount,
        tolerance=tolerance,
    )
    return result


__all__ = ["CostBasisResult", "derive_cost_basis"]
