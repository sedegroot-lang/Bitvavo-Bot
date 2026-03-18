#!/usr/bin/env python3
"""
One-time repair script: reconcile NEAR-EUR and AVAX-EUR DCA events with
exchange order history (18 mrt 2026).

Run ONLY when the bot is STOPPED:
    python scripts/repair_dca_events.py

What it does:
  - AVAX-EUR: adds missing 3rd DCA buy (1.68966478 AVAX @ €14.15)
  - NEAR-EUR: adds 5 missing DCA buys from 15:39-16:00
  - Updates dca_buys, invested_eur, total_invested_eur, buy_price
  - Writes atomically via tmp + os.replace
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import uuid

TRADE_LOG = os.path.join(os.path.dirname(__file__), "..", "data", "trade_log.json")
TRADE_LOG = os.path.normpath(TRADE_LOG)


def _load():
    with open(TRADE_LOG, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data):
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(TRADE_LOG), suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, TRADE_LOG)
    except Exception:
        os.unlink(tmp_path)
        raise


def _repair_avax(trade: dict) -> int:
    """Add missing 3rd AVAX DCA (1.68966478 @ €14.15, 18:37)."""
    events = trade.setdefault("dca_events", [])
    # Check if already present (by token amount)
    for ev in events:
        if abs(float(ev.get("tokens_bought", 0)) - 1.68966478) < 0.001:
            print("  AVAX 3rd DCA event already present, skipping")
            return 0

    missing_eur = 14.15
    missing_tokens = 1.68966478
    missing_price = missing_eur / missing_tokens  # ~8.3745

    # Timestamp: ~18:37, based on existing events (18:34 = 1773855262, 18:35 = 1773855342)
    ts = 1773855462.0  # ~18:37

    events.append({
        "event_id": f"repair-avax-dca3-{uuid.uuid4().hex[:8]}",
        "timestamp": ts,
        "price": round(missing_price, 6),
        "amount_eur": missing_eur,
        "tokens_bought": missing_tokens,
        "dca_level": 3,
        "repair_note": "reconstructed from exchange order history (18 mrt 18:37)",
    })
    events.sort(key=lambda e: e.get("timestamp", 0))

    # Update counters
    old_buys = trade.get("dca_buys", 0)
    trade["dca_buys"] = len(events)

    # Update invested_eur
    old_invested = float(trade.get("invested_eur", 0))
    trade["invested_eur"] = round(old_invested + missing_eur, 4)
    trade["total_invested_eur"] = trade["invested_eur"]

    # Recalculate average buy_price
    amount = float(trade.get("amount", 0))
    if amount > 0:
        trade["buy_price"] = round(trade["invested_eur"] / amount, 12)

    print(f"  AVAX: added 3rd DCA event. dca_buys {old_buys} → {trade['dca_buys']}, "
          f"invested €{old_invested:.2f} → €{trade['invested_eur']:.2f}")
    return 1


def _repair_near(trade: dict) -> int:
    """Add 5 missing NEAR DCA buys from 15:39-16:00."""
    events = trade.setdefault("dca_events", [])

    # The 5 missing buys from exchange history
    missing_buys = [
        {"tokens": 9.39955204, "eur": 11.39, "time_hhmm": "15:39", "ts": 1773844786.0},
        {"tokens": 7.51839624, "eur": 9.11,  "time_hhmm": "15:40", "ts": 1773844846.0},
        {"tokens": 11.7738185, "eur": 14.24, "time_hhmm": "15:58", "ts": 1773845926.0},
        {"tokens": 9.43001174, "eur": 11.39, "time_hhmm": "15:59", "ts": 1773845986.0},
        {"tokens": 7.52723945, "eur": 9.08,  "time_hhmm": "16:00", "ts": 1773846046.0},
    ]

    added = 0
    for buy in missing_buys:
        # Check if already present
        already = any(
            abs(float(ev.get("tokens_bought", 0)) - buy["tokens"]) < 0.001
            for ev in events
        )
        if already:
            print(f"  NEAR {buy['time_hhmm']} event already present, skipping")
            continue

        price = buy["eur"] / buy["tokens"]
        events.append({
            "event_id": f"repair-near-{buy['time_hhmm'].replace(':', '')}-{uuid.uuid4().hex[:8]}",
            "timestamp": buy["ts"],
            "price": round(price, 6),
            "amount_eur": buy["eur"],
            "tokens_bought": buy["tokens"],
            "dca_level": 0,  # will be renumbered below
            "repair_note": f"reconstructed from exchange order history (18 mrt {buy['time_hhmm']})",
        })
        added += 1

    if added == 0:
        print("  NEAR: no missing events to add")
        return 0

    # Sort all events chronologically and renumber dca_level
    events.sort(key=lambda e: e.get("timestamp", 0))
    for i, ev in enumerate(events, 1):
        ev["dca_level"] = i

    # Set dca_buys to min(total_events, dca_max)
    dca_max = int(trade.get("dca_max", 9))
    old_buys = trade.get("dca_buys", 0)
    trade["dca_buys"] = min(len(events), dca_max)

    # invested_eur: the current value (192.20) already includes these buys
    # from sync_engine balance reconciliation. Don't double-add.
    # Only verify it's reasonable.
    initial = float(trade.get("initial_invested_eur", 0))
    dca_sum = sum(float(ev.get("amount_eur", 0)) for ev in events)
    expected = initial + dca_sum
    current = float(trade.get("invested_eur", 0))

    print(f"  NEAR: added {added} events. dca_buys {old_buys} → {trade['dca_buys']} "
          f"(events={len(events)}, max={dca_max})")
    print(f"  NEAR: invested_eur={current:.2f}, expected from events={expected:.2f}")
    if current < expected - 0.5:
        trade["invested_eur"] = round(expected, 4)
        trade["total_invested_eur"] = round(expected, 4)
        print(f"  NEAR: invested_eur corrected → €{trade['invested_eur']:.2f}")
    elif current > expected + 5.0:
        print(f"  NEAR: invested_eur is higher (€{current - expected:.2f} unaccounted, likely earlier untracked DCAs)")

    # Recalculate buy_price
    amount = float(trade.get("amount", 0))
    invested = float(trade.get("invested_eur", 0))
    if amount > 0 and invested > 0:
        trade["buy_price"] = round(invested / amount, 12)

    return added


def main():
    print(f"Reading {TRADE_LOG}")
    data = _load()
    opens = data.get("open", {})

    repairs = 0

    avax = opens.get("AVAX-EUR")
    if avax:
        print("\n--- AVAX-EUR ---")
        repairs += _repair_avax(avax)
    else:
        print("AVAX-EUR not found in open trades")

    near = opens.get("NEAR-EUR")
    if near:
        print("\n--- NEAR-EUR ---")
        repairs += _repair_near(near)
    else:
        print("NEAR-EUR not found in open trades")

    if repairs > 0:
        print(f"\nSaving {repairs} repairs...")
        _save(data)
        print("Done! Trade log updated.")
    else:
        print("\nNo repairs needed.")


if __name__ == "__main__":
    main()
