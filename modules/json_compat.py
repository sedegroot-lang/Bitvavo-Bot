"""Compatibility layer that writes JSON files and mirrors them into TinyDB datasets.

This provides a safe rollover path: writers can continue to call the compat function
and the repo will maintain the original JSON file while keeping a synced TinyDB
representation for faster reads and safer concurrent access.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from modules import storage
from modules.logging_utils import locked_write_json, log

# Map common JSON filenames to TinyDB dataset names
# NOTE: price_cache.json is excluded because it has high-frequency writes
# from multiple processes, which causes corruption. It's cached in-memory anyway.
FILENAME_TO_DATASET = {
    "data/pending_saldo.json": "pending_saldo",
    "pending_saldo.json": "pending_saldo",  # legacy fallback
    # 'price_cache.json': 'price_cache',  # DISABLED - high-frequency, multi-process writes
    "data/sync_raw_markets.json": "sync_raw_markets",
    "sync_raw_markets.json": "sync_raw_markets",  # legacy fallback
    "data/sync_raw_balances.json": "sync_raw_balances",
    "sync_raw_balances.json": "sync_raw_balances",  # legacy fallback
    "data/sync_removed_cache.json": "sync_removed_cache",
    "sync_removed_cache.json": "sync_removed_cache",  # legacy fallback
    "data/sync_debug.json": "sync_debug",
    "sync_debug.json": "sync_debug",  # legacy fallback
    "ai/ai_changes.json": "ai_changes",
    "ai_changes.json": "ai_changes",  # legacy fallback
    "ai/ai_suggestions.json": "ai_suggestions",
    "ai_suggestions.json": "ai_suggestions",  # legacy fallback
    "data/ai_heartbeat.json": "ai_heartbeat",
    "ai_heartbeat.json": "ai_heartbeat",  # legacy fallback
    "data/heartbeat.json": "heartbeat",
    "heartbeat.json": "heartbeat",  # legacy fallback
    "data/trade_log.json": "trade_log",
    "trade_log.json": "trade_log",  # legacy fallback
    "data/top30_eur_markets.json": "top30_markets",
    "top30_eur_markets.json": "top30_markets",  # legacy fallback
    "data/top50_eur_markets.json": "top50_markets",
    "top50_eur_markets.json": "top50_markets",  # legacy fallback
    "config/bot_config.json": "bot_config",
    "bot_config.json": "bot_config",  # legacy fallback
}


def _coerce_records(data: Any) -> Iterable[dict]:
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        docs = [item for item in data if isinstance(item, dict)]
        if docs:
            return docs
    return [{"value": data}]


def write_json_compat(
    filename: str,
    data: Any,
    *,
    indent: int = 2,
    dataset: str | None = None,
    table: str | None = None,
) -> None:
    """Write JSON to disk and mirror into TinyDB when a mapping exists.

    This is intentionally tolerant: failures to update TinyDB are logged but
    do not raise, preserving the original behaviour of file writes.
    """

    try:
        locked_write_json(filename, data, indent=indent)
    except Exception as exc:
        log(f"json_compat: failed to write {filename}: {exc}", level="error")
        return

    dataset_name = dataset or FILENAME_TO_DATASET.get(Path(filename).name)
    if not dataset_name:
        return

    try:
        records = list(_coerce_records(data))
        storage.replace_all(dataset_name, records, table=table)
    except Exception as exc:
        log(
            f"json_compat: failed to mirror {filename} -> {dataset_name} (table={table}): {exc}",
            level="warning",
        )


def touch_json_timestamp(filename: str, *, dataset: str | None = None) -> None:
    """Update TinyDB meta for a JSON file without reimporting payload.

    Useful when an external process updates the JSON and we only want to bump
    the recorded mtime/size so readers that prefer TinyDB will refresh.
    """
    try:
        path = Path(filename)
        if not path.exists():
            return
        meta = {
            "key": "meta",
            "mtime": path.stat().st_mtime,
            "size": path.stat().st_size,
        }
        dataset_name = dataset or FILENAME_TO_DATASET.get(path.name)
        if dataset_name:
            storage.replace_all(dataset_name, [meta], table="meta")
    except Exception as exc:
        log(f"json_compat: failed to touch meta for {filename}: {exc}", level="warning")
