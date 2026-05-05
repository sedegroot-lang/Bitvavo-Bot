# -*- coding: utf-8 -*-
"""Bitvavo SSOT reconcile engine for DCA events and trade financials.

Uses Bitvavo order/trade history as the single source of truth.
Reconciles dca_events, dca_buys, amount, and invested_eur against actual
exchange data. Self-healing: any lost events are recovered automatically.

FIX_LOG #016.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

_log = logging.getLogger("dca_reconcile")


@dataclass(slots=True)
class ReconcileResult:
    """Outcome of a single-market reconcile."""

    market: str
    exchange_dca_count: int  # DCA buy orders found on Bitvavo (excl. initial)
    bot_dca_count: int  # dca_events in bot before reconcile
    events_added: int  # new events injected
    events_total: int  # total events after reconcile
    amount_corrected: bool  # was amount updated?
    invested_corrected: bool  # was invested_eur updated?
    buy_price_corrected: bool  # was buy_price updated?
    repairs: List[str]  # human-readable repair log


def _fetch_filled_buys(
    bitvavo: Any,
    market: str,
    since_ms: int,
) -> List[Dict[str, Any]]:
    """Fetch all filled buy trades for *market* since *since_ms* from Bitvavo.

    Uses ``bitvavo.trades()`` (fill-level, not order-level) which returns
    individual fills with unique ``id``, ``orderId``, ``timestamp``, etc.
    Paginates backwards until no more results.
    """
    all_fills: List[Dict[str, Any]] = []
    end_ms: Optional[int] = None
    seen_ids: set = set()

    for _ in range(10):  # max 10 pages
        params: Dict[str, Any] = {"limit": 500}
        if since_ms and since_ms > 0:
            params["start"] = since_ms
        if end_ms is not None and end_ms > 0:
            params["end"] = end_ms

        try:
            batch = bitvavo.trades(market, params)
        except Exception as exc:
            _log.warning("trades() call failed for %s: %s", market, exc)
            break

        if not isinstance(batch, list) or not batch:
            break
        if isinstance(batch, dict) and "error" in batch:
            _log.warning("Bitvavo API error for %s trades: %s", market, batch)
            break

        new_count = 0
        for fill in batch:
            fid = fill.get("id", "")
            if fid and fid not in seen_ids:
                seen_ids.add(fid)
                all_fills.append(fill)
                new_count += 1

        if new_count == 0:
            break

        # Paginate backwards
        oldest_ts = min(int(f.get("timestamp", 0)) for f in batch)
        if oldest_ts <= 0:
            break
        end_ms = oldest_ts - 1

    # Filter to buy-side only
    buys = [f for f in all_fills if f.get("side") == "buy"]
    buys.sort(key=lambda f: int(f.get("timestamp", 0)))
    return buys


def _group_fills_by_order(fills: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group individual fills into order-level summaries.

    Each order can have multiple fills. We group by orderId and compute
    aggregate amount, cost, fee, and timestamp.
    """
    orders: Dict[str, Dict[str, Any]] = {}

    for fill in fills:
        oid = fill.get("orderId", fill.get("id", ""))
        if not oid:
            continue

        amount = float(fill.get("amount", 0) or 0)
        price = float(fill.get("price", 0) or 0)
        fee = float(fill.get("fee", 0) or 0)
        ts = int(fill.get("timestamp", 0))

        if oid not in orders:
            orders[oid] = {
                "orderId": oid,
                "timestamp_ms": ts,
                "total_amount": 0.0,
                "total_cost": 0.0,  # amount * price (quote currency)
                "total_fee": 0.0,
                "fill_count": 0,
            }

        orders[oid]["total_amount"] += amount
        orders[oid]["total_cost"] += amount * price
        orders[oid]["total_fee"] += fee
        orders[oid]["fill_count"] += 1
        # Keep earliest timestamp per order
        if ts < orders[oid]["timestamp_ms"] or orders[oid]["timestamp_ms"] == 0:
            orders[oid]["timestamp_ms"] = ts

    result = list(orders.values())
    result.sort(key=lambda o: o["timestamp_ms"])
    return result


def reconcile_trade(
    bitvavo: Any,
    market: str,
    trade: Dict[str, Any],
    *,
    dca_max: int = 17,
    dry_run: bool = False,
) -> ReconcileResult:
    """Reconcile a single trade's DCA events + financials against Bitvavo.

    This is the core SSOT function. It:
      1. Fetches ALL buy fills for this market since trade opening
      2. Groups fills into orders (initial buy + DCA orders)
      3. Compares with bot's dca_events
      4. Adds missing events, corrects amount/invested/buy_price
      5. Returns a detailed ReconcileResult

    Args:
        bitvavo: Bitvavo API client instance
        market: e.g. "UNI-EUR"
        trade: the trade dict (MUTATED in-place unless dry_run=True)
        dca_max: max DCA buys allowed
        dry_run: if True, compute diffs but don't modify trade
    """
    repairs: List[str] = []
    opened_ts = float(trade.get("opened_ts", 0) or trade.get("timestamp", 0) or 0)
    opened_ms = int(opened_ts * 1000) if opened_ts > 0 else 0

    # --- Fetch exchange data ---
    fills = _fetch_filled_buys(bitvavo, market, since_ms=opened_ms - 60000 if opened_ms > 0 else 0)
    if not fills:
        return ReconcileResult(
            market=market,
            exchange_dca_count=0,
            bot_dca_count=0,
            events_added=0,
            events_total=0,
            amount_corrected=False,
            invested_corrected=False,
            buy_price_corrected=False,
            repairs=["No fills found on Bitvavo"],
        )

    orders = _group_fills_by_order(fills)
    if not orders:
        return ReconcileResult(
            market=market,
            exchange_dca_count=0,
            bot_dca_count=0,
            events_added=0,
            events_total=0,
            amount_corrected=False,
            invested_corrected=False,
            buy_price_corrected=False,
            repairs=["No orders after grouping"],
        )

    # --- Separate initial buy from DCAs ---
    # First order (by timestamp) = initial buy, rest = DCAs
    initial_order = orders[0]
    dca_orders = orders[1:]
    exchange_dca_count = len(dca_orders)

    # --- Current bot state ---
    existing_events = trade.get("dca_events", []) or []
    bot_dca_count = len(existing_events)

    # --- Build set of known order IDs from existing events ---
    known_order_ids: set = set()
    for ev in existing_events:
        oid = ev.get("order_id") or ev.get("orderId")
        if oid:
            known_order_ids.add(oid)

    # --- Also match by timestamp+amount for events without order_id ---
    known_timestamps: set = set()
    for ev in existing_events:
        ts = float(ev.get("timestamp", 0) or ev.get("ts", 0) or 0)
        eur = float(ev.get("amount_eur", 0) or 0)
        if ts > 0 and eur > 0:
            known_timestamps.add((round(ts, 0), round(eur, 1)))

    # --- Find missing DCA events ---
    missing_events: List[Dict[str, Any]] = []
    for i, dca_order in enumerate(dca_orders):
        oid = dca_order["orderId"]
        ts_s = dca_order["timestamp_ms"] / 1000.0
        cost_with_fee = dca_order["total_cost"] + dca_order["total_fee"]

        # Check if already known
        if oid in known_order_ids:
            continue

        # Fuzzy match by timestamp (within 5s) and EUR amount (within €1)
        ts_match = False
        for kts, keur in known_timestamps:
            if abs(kts - round(ts_s, 0)) < 5 and abs(keur - round(cost_with_fee, 1)) < 1.0:
                ts_match = True
                break
        if ts_match:
            continue

        # This DCA exists on Bitvavo but NOT in bot — add it
        amount = dca_order["total_amount"]
        price = dca_order["total_cost"] / amount if amount > 0 else 0
        level = bot_dca_count + len(missing_events) + 1

        new_event = {
            "event_id": str(uuid.uuid4()),
            "timestamp": ts_s,
            "price": round(price, 8),
            "amount_eur": round(cost_with_fee, 6),
            "tokens_bought": round(amount, 10),
            "dca_level": level,
            "source": "reconcile",
            "order_id": oid,
        }
        missing_events.append(new_event)
        repairs.append(
            f"DCA #{level} recovered from Bitvavo: orderId={oid[:12]}.. "
            f"price={price:.4f} eur={cost_with_fee:.2f} tokens={amount:.6f} "
            f"ts={time.strftime('%Y-%m-%d %H:%M', time.localtime(ts_s))}"
        )

    events_added = len(missing_events)

    # --- Also enrich existing events with order_id if missing ---
    for ev in existing_events:
        if ev.get("order_id"):
            continue
        ev_ts = float(ev.get("timestamp", 0) or ev.get("ts", 0) or 0)
        ev_eur = float(ev.get("amount_eur", 0) or 0)
        for dca_order in dca_orders:
            oid = dca_order["orderId"]
            ts_s = dca_order["timestamp_ms"] / 1000.0
            cost = dca_order["total_cost"] + dca_order["total_fee"]
            if abs(ev_ts - ts_s) < 5 and abs(ev_eur - cost) < 1.0:
                if not dry_run:
                    ev["order_id"] = oid
                break

    # --- Compute expected totals from ALL exchange orders ---
    exchange_total_amount = sum(o["total_amount"] for o in orders)
    exchange_total_cost = sum(o["total_cost"] + o["total_fee"] for o in orders)
    exchange_avg_price = exchange_total_cost / exchange_total_amount if exchange_total_amount > 0 else 0

    # --- Apply corrections ---
    bot_amount = float(trade.get("amount", 0) or 0)
    bot_invested = float(trade.get("invested_eur", 0) or 0)
    bot_buy_price = float(trade.get("buy_price", 0) or 0)
    partial_tp_returned = float(trade.get("partial_tp_returned_eur", 0) or 0)

    amount_corrected = False
    invested_corrected = False
    buy_price_corrected = False

    if not dry_run:
        # Add missing DCA events
        if missing_events:
            events_list = trade.setdefault("dca_events", [])
            events_list.extend(missing_events)
            # Sort by timestamp
            events_list.sort(key=lambda e: float(e.get("timestamp", 0) or e.get("ts", 0) or 0))
            # Renumber levels
            for idx, ev in enumerate(events_list):
                ev["dca_level"] = idx + 1

        # Update dca_buys from event count
        all_events = trade.get("dca_events", []) or []
        trade["dca_buys"] = len(all_events)

        # Correct amount if significantly different (>0.1%)
        if exchange_total_amount > 0 and bot_amount > 0:
            diff_pct = abs(exchange_total_amount - bot_amount) / bot_amount
            if diff_pct > 0.001:  # >0.1% difference
                repairs.append(f"amount: {bot_amount:.8f} → {exchange_total_amount:.8f} (diff {diff_pct * 100:.2f}%)")
                trade["amount"] = round(exchange_total_amount, 10)
                amount_corrected = True

        # Correct invested_eur if significantly different (>1%)
        # invested_eur = total cost including fees, minus partial TP returned
        expected_invested = exchange_total_cost - partial_tp_returned
        if expected_invested > 0 and bot_invested > 0:
            diff_pct = abs(expected_invested - bot_invested) / bot_invested
            if diff_pct > 0.01:  # >1% difference
                repairs.append(
                    f"invested_eur: €{bot_invested:.2f} → €{expected_invested:.2f} (diff {diff_pct * 100:.2f}%)"
                )
                trade["invested_eur"] = round(expected_invested, 4)
                trade["total_invested_eur"] = round(exchange_total_cost, 4)
                invested_corrected = True
        elif bot_invested <= 0 and expected_invested > 0:
            repairs.append(f"invested_eur: €0 → €{expected_invested:.2f} (was missing)")
            trade["invested_eur"] = round(expected_invested, 4)
            trade["total_invested_eur"] = round(exchange_total_cost, 4)
            invested_corrected = True

        # Correct buy_price from exchange data
        new_amount = float(trade.get("amount", 0) or 0)
        new_total = float(trade.get("total_invested_eur", 0) or 0)
        if new_amount > 0 and new_total > 0:
            expected_bp = new_total / new_amount
            if bot_buy_price > 0:
                bp_diff = abs(expected_bp - bot_buy_price) / bot_buy_price
                if bp_diff > 0.01:  # >1% difference
                    repairs.append(f"buy_price: {bot_buy_price:.6f} → {expected_bp:.6f} (diff {bp_diff * 100:.2f}%)")
                    trade["buy_price"] = round(expected_bp, 12)
                    buy_price_corrected = True

        # Correct initial_invested_eur from the FIRST buy order on Bitvavo.
        # After sync recreates trades, initial_invested_eur may be set to the
        # total cost (including DCAs) instead of just the initial buy.
        initial_inv = float(trade.get("initial_invested_eur", 0) or 0)
        initial_cost = initial_order["total_cost"] + initial_order["total_fee"]
        if initial_cost > 0:
            if initial_inv <= 0:
                trade["initial_invested_eur"] = round(initial_cost, 4)
                repairs.append(f"initial_invested_eur: €0 → €{initial_cost:.2f}")
            elif dca_orders and abs(initial_inv - initial_cost) / initial_cost > 0.05:
                # initial_invested_eur significantly differs from first buy AND
                # there are DCA orders — likely set to total cost after sync
                repairs.append(
                    f"initial_invested_eur: €{initial_inv:.2f} → €{initial_cost:.2f} "
                    f"(was total cost, corrected to initial buy only)"
                )
                trade["initial_invested_eur"] = round(initial_cost, 4)

    events_total = len(trade.get("dca_events", [])) if not dry_run else bot_dca_count + events_added

    return ReconcileResult(
        market=market,
        exchange_dca_count=exchange_dca_count,
        bot_dca_count=bot_dca_count,
        events_added=events_added,
        events_total=events_total,
        amount_corrected=amount_corrected,
        invested_corrected=invested_corrected,
        buy_price_corrected=buy_price_corrected,
        repairs=repairs,
    )


def reconcile_all_trades(
    bitvavo: Any,
    open_trades: Dict[str, Dict[str, Any]],
    *,
    dca_max: int = 17,
    dry_run: bool = False,
    exclude_markets: Optional[set] = None,
) -> List[ReconcileResult]:
    """Reconcile all open trades against Bitvavo order history.

    Args:
        bitvavo: Bitvavo API client
        open_trades: dict of market→trade (from state.open_trades)
        dca_max: max DCA level
        dry_run: don't modify trades, just report
        exclude_markets: skip these markets (e.g. grid-managed)

    Returns:
        List of ReconcileResult, one per market processed.
    """
    results: List[ReconcileResult] = []
    exclude = exclude_markets or set()

    for market, trade in open_trades.items():
        if market in exclude:
            continue
        try:
            result = reconcile_trade(
                bitvavo,
                market,
                trade,
                dca_max=dca_max,
                dry_run=dry_run,
            )
            results.append(result)
            if result.repairs:
                for r in result.repairs:
                    _log.warning("[RECONCILE %s] %s", market, r)
            else:
                _log.debug("[RECONCILE %s] OK — %d DCA events matched", market, result.events_total)
        except Exception as exc:
            _log.error("[RECONCILE %s] Error: %s", market, exc)
            results.append(
                ReconcileResult(
                    market=market,
                    exchange_dca_count=0,
                    bot_dca_count=0,
                    events_added=0,
                    events_total=0,
                    amount_corrected=False,
                    invested_corrected=False,
                    buy_price_corrected=False,
                    repairs=[f"Error: {exc}"],
                )
            )

    return results
