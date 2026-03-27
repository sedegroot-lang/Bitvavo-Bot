"""Event-sourced DCA state — dca_events is the SINGLE source of truth.

dca_buys is ALWAYS len(dca_events). It is stored in the trade dict for backward
compatibility, but every mutation goes through this module which recomputes it.

Architecture:
  - record_dca()          → The ONLY way to add a DCA event. Updates all derived fields.
  - sync_derived_fields() → Recomputes all derived DCA fields from events. Use at startup,
                            after sync, and in validation guards.
  - compute_state()       → Pure function: read-only snapshot of DCA state from events.
  - validate_events()     → Integrity checks on dca_events list. Returns warnings.
  - detect_untracked_buys() → Finds Bitvavo orders not in dca_events (manual/external buys).

FIX #007: This module replaces all scattered dca_buys mutations with a single
source of truth. dca_buys desync is now structurally impossible.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

_log = logging.getLogger("dca_state")

# Type alias
Trade = Dict[str, Any]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DCAEvent:
    """Immutable record of a single DCA buy."""
    event_id: str
    timestamp: float        # time.time() epoch
    price: float            # execution price per token
    amount_eur: float       # EUR cost including fees
    tokens_bought: float
    dca_level: int          # 1-based level at time of execution
    source: str = "bot"     # "bot" | "manual" | "pyramid" | "sync"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "price": self.price,
            "amount_eur": self.amount_eur,
            "tokens_bought": self.tokens_bought,
            "dca_level": self.dca_level,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> DCAEvent:
        return cls(
            event_id=d.get("event_id") or str(uuid.uuid4()),
            timestamp=float(d.get("timestamp", 0) or 0),
            price=float(d.get("price", 0) or 0),
            amount_eur=float(d.get("amount_eur", 0) or 0),
            tokens_bought=float(d.get("tokens_bought", 0) or 0),
            dca_level=int(d.get("dca_level", 0) or 0),
            source=d.get("source", "bot"),
        )


@dataclass(slots=True)
class DCAState:
    """Read-only snapshot of DCA state computed from events."""
    events: List[DCAEvent]
    dca_buys: int           # ALWAYS len(events)
    total_dca_eur: float    # sum of all event costs
    last_dca_price: float   # price of most recent event, or 0
    last_dca_ts: float      # timestamp of most recent event, or 0
    dca_max: int            # config-driven max

    @property
    def has_events(self) -> bool:
        return len(self.events) > 0

    @property
    def can_dca(self) -> bool:
        return self.dca_buys < self.dca_max

    @property
    def next_level(self) -> int:
        return self.dca_buys + 1


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def compute_state(trade: Trade, dca_max: int) -> DCAState:
    """Derive DCA state from trade's dca_events list.

    Pure function — reads trade["dca_events"] but does NOT mutate the trade.
    """
    raw_events = trade.get("dca_events") or []
    events = []
    for e in raw_events:
        if isinstance(e, dict):
            events.append(DCAEvent.from_dict(e))
        elif isinstance(e, DCAEvent):
            events.append(e)
    events.sort(key=lambda ev: ev.timestamp)

    total_eur = sum(ev.amount_eur for ev in events)
    last_price = events[-1].price if events else 0.0
    last_ts = events[-1].timestamp if events else 0.0

    return DCAState(
        events=events,
        dca_buys=len(events),
        total_dca_eur=round(total_eur, 4),
        last_dca_price=last_price,
        last_dca_ts=last_ts,
        dca_max=dca_max,
    )


def record_dca(
    trade: Trade,
    price: float,
    amount_eur: float,
    tokens_bought: float,
    dca_max: int,
    *,
    source: str = "bot",
    drop_pct: float = 0.0,
    step_multiplier: float = 1.0,
) -> DCAState:
    """Record a new DCA event and update ALL derived fields atomically.

    This is the ONLY way to add a DCA. It:
      1. Creates a DCAEvent with unique ID
      2. Appends to trade["dca_events"]
      3. Recomputes dca_buys, last_dca_price from events
      4. Updates dca_next_price for cascading prevention (FIX #003)
      5. Returns new computed state

    The caller is still responsible for:
      - Updating buy_price (weighted average), amount, invested_eur
        (via core.trade_investment.add_dca)
      - These are trade-level fields, not DCA-specific
    """
    events_list: list = trade.setdefault("dca_events", [])
    level = len(events_list) + 1

    event = DCAEvent(
        event_id=str(uuid.uuid4()),
        timestamp=time.time(),
        price=price,
        amount_eur=amount_eur,
        tokens_bought=tokens_bought,
        dca_level=level,
        source=source,
    )
    events_list.append(event.to_dict())

    # Recompute all derived fields from events
    new_state = compute_state(trade, dca_max)

    # Sync derived fields into trade dict
    trade["dca_buys"] = new_state.dca_buys
    trade["last_dca_price"] = new_state.last_dca_price
    trade["dca_max"] = dca_max

    # Update dca_next_price using last_dca_price (FIX #003: prevents cascading)
    if drop_pct > 0 and new_state.last_dca_price > 0:
        next_step = drop_pct * (step_multiplier ** new_state.dca_buys)
        trade["dca_next_price"] = new_state.last_dca_price * (1 - next_step)

    _log.info(
        "[DCAState] record_dca level=%d price=%.6f eur=%.2f tokens=%.6f source=%s → dca_buys=%d",
        level, price, amount_eur, tokens_bought, source, new_state.dca_buys,
    )

    return new_state


def sync_derived_fields(trade: Trade, dca_max: int) -> Tuple[DCAState, List[str]]:
    """Recompute and sync ALL derived DCA fields from events.

    Call this:
      - At bot startup (validate_and_repair_trades)
      - After sync_engine re-derive
      - In trade_store validation

    This replaces GUARD 5, GUARD 1 dca logic, and trade_store Rule 4.

    Returns:
        (state, repairs) — the computed state and a list of repair descriptions.
    """
    state = compute_state(trade, dca_max)
    repairs: List[str] = []

    # Sync dca_buys from events, but never LOWER below stored value.
    # Stored dca_buys may include historical/synced buys with no events (FIX #008).
    stored_buys = int(trade.get("dca_buys", 0) or 0)
    effective_buys = max(state.dca_buys, stored_buys)
    if stored_buys != effective_buys:
        repairs.append(
            f"dca_buys {stored_buys} → {effective_buys} (from {len(state.events)} events)"
        )
        trade["dca_buys"] = effective_buys

    # Sync last_dca_price
    if state.has_events:
        stored_ldp = float(trade.get("last_dca_price", 0) or 0)
        if abs(stored_ldp - state.last_dca_price) > 1e-8:
            repairs.append(
                f"last_dca_price {stored_ldp:.6f} → {state.last_dca_price:.6f}"
            )
            trade["last_dca_price"] = state.last_dca_price

    # Sync dca_max: only SET if trade has no dca_max yet (new trade).
    # Per-trade dca_max is preserved once set — global config is the default,
    # not a forced override. (FIX #008: prevents resetting user overrides)
    stored_max = int(trade.get("dca_max", 0) or 0)
    if stored_max <= 0:
        repairs.append(f"dca_max {stored_max} → {dca_max} (initialized from config)")
        trade["dca_max"] = dca_max

    return state, repairs


def validate_events(trade: Trade, dca_max: int) -> List[str]:
    """Validate dca_events integrity. Returns list of warnings (empty = clean)."""
    warnings: List[str] = []
    state = compute_state(trade, dca_max)

    # Check stored dca_buys matches computed
    stored_buys = int(trade.get("dca_buys", 0) or 0)
    if stored_buys != state.dca_buys:
        warnings.append(
            f"dca_buys mismatch: stored={stored_buys}, computed={state.dca_buys}"
        )

    # Check for duplicate event_ids
    ids = [ev.event_id for ev in state.events]
    if len(ids) != len(set(ids)):
        warnings.append("Duplicate event_ids found in dca_events")

    # Check chronological order
    for i in range(1, len(state.events)):
        if state.events[i].timestamp < state.events[i - 1].timestamp:
            warnings.append(f"Events not in chronological order at index {i}")

    # Check dca_level sequence
    for i, ev in enumerate(state.events):
        expected_level = i + 1
        if ev.dca_level != expected_level:
            warnings.append(
                f"Event {i} has dca_level={ev.dca_level}, expected {expected_level}"
            )

    # Check for zero/negative amounts
    for i, ev in enumerate(state.events):
        if ev.amount_eur <= 0:
            warnings.append(f"Event {i} has non-positive amount_eur={ev.amount_eur}")
        if ev.tokens_bought <= 0:
            warnings.append(f"Event {i} has non-positive tokens_bought={ev.tokens_bought}")

    return warnings


def detect_untracked_buys(
    trade: Trade,
    bitvavo_orders: Sequence[Dict[str, Any]],
    dca_max: int,
    min_eur: float = 5.0,
) -> List[Dict[str, Any]]:
    """Detect buy orders on Bitvavo not tracked in dca_events.

    Compares Bitvavo order history with stored events to find untracked buys.
    Only considers BUY orders AFTER the trade's opened_ts (skips the initial buy).

    Does NOT auto-record them — returns a list of untracked order dicts.
    The caller decides whether to record them (via record_dca with source="manual").

    Args:
        trade: Trade dict with dca_events and opened_ts.
        bitvavo_orders: List of Bitvavo order dicts (from getOrders API).
        dca_max: Config max DCA buys.
        min_eur: Minimum EUR to consider (skip dust).

    Returns:
        List of Bitvavo order dicts that are not tracked in dca_events.
    """
    # Build signature set from existing events for dedup
    existing_sigs: set = set()
    for ev in (trade.get("dca_events") or []):
        # Signature: (rounded timestamp, rounded EUR)
        ts = round(float(ev.get("timestamp", 0) or 0), 0)
        eur = round(float(ev.get("amount_eur", 0) or 0), 2)
        existing_sigs.add((ts, eur))

    opened_ts = float(trade.get("opened_ts", 0) or 0)

    untracked: List[Dict[str, Any]] = []
    for order in bitvavo_orders:
        if order.get("side") != "buy":
            continue

        # Bitvavo timestamps are in milliseconds
        order_ts_ms = float(order.get("timestamp", 0) or 0)
        order_ts = order_ts_ms / 1000.0 if order_ts_ms > 1e12 else order_ts_ms

        # Skip the initial buy and anything before it
        if order_ts <= opened_ts + 2:  # 2s grace for timestamp rounding
            continue

        filled_eur = float(order.get("filledAmountQuote", 0) or 0)
        if filled_eur < min_eur:
            continue

        # Check if already tracked
        sig = (round(order_ts, 0), round(filled_eur, 2))
        if sig in existing_sigs:
            continue

        untracked.append(order)

    return untracked
