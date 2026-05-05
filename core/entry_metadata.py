"""Entry-metadata persistent cache.

Solves a real bug: when sync_engine re-adopts a trade that the bot opened
(e.g. after the trade briefly fell out of open_trades due to auto_free_slot,
a save failure, or a restart), the metadata fields ``score``, ``opened_regime``,
``volatility_at_entry``, ``rsi_at_entry``, ``macd_at_entry`` are lost — they
get reset to ``0.0`` / ``'sync_attach'``. This cache restores them.

API:
    record(market, metadata_dict)  # called right after trade open
    get(market) -> dict | None     # called by sync to recover lost fields
    clear(market)                  # called on close

The file is JSON-encoded, atomic-write, single dict keyed by market.
Entries older than ``MAX_AGE_DAYS`` are pruned on load.

Thread-safe via module-level RLock.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DATA_FILE = PROJECT_ROOT / "data" / "entry_metadata.json"
_LOCK = RLock()
_MAX_AGE_DAYS = 30

# Fields we care about restoring after a sync re-adopt.
_PRESERVED_FIELDS = (
    "score",
    "opened_regime",
    "volatility_at_entry",
    "rsi_at_entry",
    "macd_at_entry",
    "macd_line_at_entry",
    "macd_signal_at_entry",
    "sma_short_at_entry",
    "sma_long_at_entry",
    "ema20_at_entry",
    "stochastic_at_entry",
    "stochastic_k_at_entry",
    "bb_upper_at_entry",
    "bb_lower_at_entry",
    "bb_position_at_entry",
    "volume_avg_at_entry",
    "volume_24h_eur",
    "opened_ts",
    "_entry_source",
)


def _load() -> Dict[str, Dict[str, Any]]:
    if not _DATA_FILE.exists():
        return {}
    try:
        with _DATA_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f) or {}
        # Prune stale entries
        now = time.time()
        cutoff = now - _MAX_AGE_DAYS * 86400
        return {
            m: rec for m, rec in data.items() if isinstance(rec, dict) and float(rec.get("_recorded_ts", now)) > cutoff
        }
    except Exception:
        return {}


def _save(data: Dict[str, Dict[str, Any]]) -> None:
    try:
        _DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _DATA_FILE.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(str(tmp), str(_DATA_FILE))
    except Exception:
        pass


def record(market: str, trade_dict: Dict[str, Any]) -> None:
    """Persist entry metadata for ``market`` from a freshly-opened trade dict."""
    if not market:
        return
    rec: Dict[str, Any] = {"_recorded_ts": time.time()}
    for field in _PRESERVED_FIELDS:
        if field in trade_dict and trade_dict[field] is not None:
            rec[field] = trade_dict[field]
    if not rec or len(rec) == 1:  # only timestamp = nothing useful
        return
    with _LOCK:
        data = _load()
        data[market] = rec
        _save(data)


def get(market: str) -> Optional[Dict[str, Any]]:
    """Return cached metadata for ``market`` or None."""
    if not market:
        return None
    with _LOCK:
        return _load().get(market)


def clear(market: str) -> None:
    """Remove cached metadata for ``market`` (called on close)."""
    if not market:
        return
    with _LOCK:
        data = _load()
        if market in data:
            del data[market]
            _save(data)


def restore_into(market: str, trade: Dict[str, Any]) -> int:
    """Restore preserved fields from cache INTO trade dict if missing/default.

    A field is restored when:
      * the cache has it AND
      * the trade either lacks it OR has the sentinel default
        (``score==0.0`` or ``opened_regime in {'unknown','sync_attach'}``).

    Returns the number of fields actually restored.
    """
    cache = get(market)
    if not cache:
        return 0
    restored = 0
    for field in _PRESERVED_FIELDS:
        if field not in cache:
            continue
        cur = trade.get(field)
        is_default = (
            cur is None
            or (field == "score" and float(cur or 0) == 0.0)
            or (field == "opened_regime" and cur in ("unknown", "sync_attach", "", None))
            or (field == "volatility_at_entry" and float(cur or 0) == 0.0)
        )
        if is_default:
            trade[field] = cache[field]
            restored += 1
    if restored:
        trade["_metadata_restored_from_cache"] = True
    return restored
