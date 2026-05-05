"""Persistent cost-basis cache for positions whose true cost basis cannot be
derived from Bitvavo trade history.

Use cases:
- Coins acquired via SWAP (NOT-EUR from ENJ swap): no entry in `bv.trades()`.
- Airdrops, internal transfers, deposits without an order.
- Manual recovery from `tmp/recover_positions.py` after sync incidents.

Without this cache, sync_engine repeatedly resets such positions' buy_price /
invested_eur to current price, which:
  (a) breaks unrealised P&L display,
  (b) makes trailing-stop / DCA / TP decisions based on wrong basis,
  (c) wipes the user's actual economic loss/profit.

The cache is a small JSON file under data/cost_basis_cache.json, keyed by
market. RLock-protected, atomic tmp+replace writes. No TTL — entries persist
until explicitly cleared (or the position is closed).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CACHE_PATH = _PROJECT_ROOT / "data" / "cost_basis_cache.json"
_LOCK = RLock()


def _read() -> Dict[str, Dict[str, Any]]:
    if not _CACHE_PATH.exists():
        return {}
    try:
        return json.loads(_CACHE_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _write(data: Dict[str, Dict[str, Any]]) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _CACHE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, _CACHE_PATH)


def get(market: str) -> Optional[Dict[str, Any]]:
    """Return cached entry for `market` or None.

    Entry shape: {buy_price, invested_eur, amount, source, ts}.
    """
    with _LOCK:
        data = _read()
        return data.get(market)


def set(
    market: str,
    *,
    buy_price: float,
    invested_eur: float,
    amount: Optional[float] = None,
    source: str = "manual",
) -> None:
    """Store/update cost basis for `market`."""
    with _LOCK:
        data = _read()
        data[market] = {
            "buy_price": float(buy_price),
            "invested_eur": float(invested_eur),
            "amount": float(amount) if amount is not None else None,
            "source": str(source),
            "ts": time.time(),
        }
        _write(data)


def remove(market: str) -> bool:
    """Remove the cached entry for `market`. Returns True if it existed."""
    with _LOCK:
        data = _read()
        if market in data:
            del data[market]
            _write(data)
            return True
        return False


def all_markets() -> Dict[str, Dict[str, Any]]:
    """Return a shallow copy of the entire cache (for inspection / dashboards)."""
    with _LOCK:
        return dict(_read())


def restore_into(market: str, trade: Dict[str, Any]) -> bool:
    """If a cache entry exists for `market`, write its cost-basis fields into
    `trade` (only when those fields look unset/wrong). Returns True on restore.

    This is the single integration point used by sync_engine. Safe to call
    unconditionally — it is a no-op when no cache entry exists.
    """
    entry = get(market)
    if not entry:
        return False
    buy_price = float(entry.get("buy_price") or 0)
    invested = float(entry.get("invested_eur") or 0)
    if buy_price <= 0 or invested <= 0:
        return False

    cur_bp = float(trade.get("buy_price") or 0)
    cur_inv = float(trade.get("invested_eur") or 0)
    # Only restore when missing or clearly stale (sync had to fall back to
    # current price → buy_price equals trade['highest_price'] but invested==0).
    needs_restore = (
        cur_bp <= 0
        or cur_inv <= 0
        or float(trade.get("initial_invested_eur") or 0) <= 0
    )
    if not needs_restore:
        return False

    trade["buy_price"] = buy_price
    trade["invested_eur"] = invested
    trade["initial_invested_eur"] = invested
    trade.setdefault("total_invested_eur", invested)
    if not trade.get("highest_price") or float(trade["highest_price"]) < buy_price:
        # do not lower an existing higher highest_price (preserves trailing high-water mark)
        if not trade.get("highest_price"):
            trade["highest_price"] = buy_price
    trade["_cost_basis_restored_from_cache"] = True
    return True
