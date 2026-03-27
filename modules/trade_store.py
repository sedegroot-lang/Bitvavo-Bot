"""Utilities for keeping trade log data in sync between JSON and TinyDB."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from modules import storage
from modules.logging_utils import locked_write_json, log

TRADE_JSON_DEFAULT = 'trade_log.json'
TRADE_DATASET = 'trade_log'
TRADE_SNAPSHOT_TABLE = 'snapshot'
TRADE_META_TABLE = 'meta'
_META_KEY = 'meta'


def _collect_file_meta(path: Path) -> Dict[str, Any]:
    try:
        stat = path.stat()
        return {
            'key': _META_KEY,
            'mtime': stat.st_mtime,
            'size': stat.st_size,
        }
    except FileNotFoundError:
        return {'key': _META_KEY, 'mtime': 0.0, 'size': 0}


def _load_snapshot_table() -> Dict[str, Any]:
    try:
        rows = storage.fetch_all(TRADE_DATASET, table=TRADE_SNAPSHOT_TABLE)
        if rows:
            last = rows[-1]
            if isinstance(last, dict):
                return last
    except Exception as exc:
        log(f"TradeStore: lezen snapshot uit TinyDB mislukt: {exc}", level='warning')
    return {}


def _load_meta() -> Dict[str, Any]:
    try:
        rows = storage.fetch_all(TRADE_DATASET, table=TRADE_META_TABLE)
        if rows:
            first = rows[-1]
            if isinstance(first, dict) and first.get('key') == _META_KEY:
                return first
    except Exception:
        pass
    return {'key': _META_KEY, 'mtime': 0.0, 'size': 0}


def _persist_snapshot(data: Dict[str, Any], meta: Dict[str, Any]) -> None:
    try:
        storage.replace_all(TRADE_DATASET, [data], table=TRADE_SNAPSHOT_TABLE)
        storage.replace_all(TRADE_DATASET, [meta], table=TRADE_META_TABLE)
    except Exception as exc:
        log(f"TradeStore: kon TinyDB snapshot niet opslaan: {exc}", level='warning')


def load_snapshot(json_path: str | os.PathLike[str] = TRADE_JSON_DEFAULT) -> Dict[str, Any]:
    """Return the latest trade log snapshot, preferring TinyDB but syncing from JSON as needed."""

    path = Path(json_path)
    json_doc: Dict[str, Any] | None = None

    meta = _load_meta()
    file_meta = _collect_file_meta(path)
    needs_refresh = not _load_snapshot_table() or (
        abs(meta.get('mtime', 0.0) - file_meta.get('mtime', 0.0)) > 1e-6
        or meta.get('size') != file_meta.get('size')
    )

    if needs_refresh and path.exists():
        try:
            # Use utf-8-sig to automatically handle BOM if present
            with path.open('r', encoding='utf-8-sig') as fh:
                payload = json.load(fh)
            if isinstance(payload, dict):
                json_doc = payload
                meta = file_meta
                _persist_snapshot(payload, meta)
        except Exception as exc:
            log(f"TradeStore: JSON laden mislukt ({path}): {exc}", level='warning')

    snapshot = _load_snapshot_table()
    if snapshot:
        return snapshot

    if json_doc is None and path.exists():
        try:
            # Use utf-8-sig to automatically handle BOM if present
            with path.open('r', encoding='utf-8-sig') as fh:
                payload = json.load(fh)
            if isinstance(payload, dict):
                json_doc = payload
        except Exception:
            json_doc = None
        if json_doc:
            _persist_snapshot(json_doc, file_meta)
            return json_doc

    return {'open': {}, 'closed': []}


def _validate_and_fix_trade_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and fix corrupted invested_eur/dca_buys before saving.
    
    CRITICAL GUARD: This prevents corrupted data from derive_cost_basis() from being saved.
    Rules:
    - invested_eur must be > 0 (restore from initial_invested_eur if corrupted)
    - invested_eur must equal initial_invested_eur if no dca_events exist
    - dca_buys must be >= 0 and <= dca_max (reset to reasonable value if corrupted)
    - total_invested_eur must match actual investment (initial + sum of dca_events)
    """
    if not isinstance(data, dict):
        return data
    
    open_trades = data.get('open', {})
    if not isinstance(open_trades, dict):
        return data
    
    fixed_count = 0
    for market, trade in open_trades.items():
        if not isinstance(trade, dict):
            continue
        
        # Rule 0: buy_price must be positive (prevents division-by-zero in profit calcs)
        buy_price = float(trade.get('buy_price', 0) or 0)
        if buy_price <= 0:
            log(f"VALIDATION WARN [{market}]: buy_price={buy_price} is invalid (skipping trade validation)", level='warning')
            continue
        
        # Rule 0b: amount must be positive
        amount = float(trade.get('amount', 0) or 0)
        if amount <= 0:
            log(f"VALIDATION WARN [{market}]: amount={amount} is invalid (skipping trade validation)", level='warning')
            continue
        
        initial = float(trade.get('initial_invested_eur', 0) or 0)
        invested = float(trade.get('invested_eur', 0) or 0)
        total = float(trade.get('total_invested_eur', 0) or 0)
        dca_buys = int(trade.get('dca_buys', 0) or 0)
        dca_max = int(trade.get('dca_max', 3) or 3)
        dca_events = trade.get('dca_events', [])
        actual_dca_count = len(dca_events) if isinstance(dca_events, list) else 0
        
        needs_fix = False
        
        # Rule 1: invested_eur must be positive
        if invested <= 0 and initial > 0:
            log(f"VALIDATION FIX [{market}]: invested_eur={invested} -> {initial} (was negative/zero)", level='warning')
            trade['invested_eur'] = initial
            invested = initial
            needs_fix = True
        
        # Rule 2: If NO dca_events AND no partial TPs, invested_eur MUST equal initial
        # After partial TPs, invested_eur is legitimately lower than initial
        has_partial_tp = float(trade.get('partial_tp_returned_eur', 0) or 0) > 0
        tp_flags = trade.get('tp_flags', trade.get('tp_levels_done', []))
        has_tp_flags = isinstance(tp_flags, list) and any(tp_flags)
        if actual_dca_count == 0 and initial > 0 and not has_partial_tp and not has_tp_flags:
            if abs(invested - initial) > 0.01:
                log(f"VALIDATION FIX [{market}]: invested_eur={invested:.2f} -> {initial:.2f} (no DCA/TP, must match initial)", level='warning')
                trade['invested_eur'] = initial
                invested = initial
                needs_fix = True
        
        # Rule 3: total_invested_eur must be reasonable
        # total_invested_eur = initial + sum(dca_events), NEVER modified by partial TPs
        if actual_dca_count == 0 and initial > 0:
            if abs(total - initial) > 0.01:
                log(f"VALIDATION FIX [{market}]: total_invested_eur={total:.2f} -> {initial:.2f} (no DCA events)", level='warning')
                trade['total_invested_eur'] = initial
                needs_fix = True
        elif actual_dca_count > 0 and initial > 0:
            # Verify total = initial + sum of DCA amounts
            # NOTE: Only WARN, never auto-correct. initial_invested_eur may have been
            # set by sync engine (derive_cost_basis) which includes DCA costs already.
            # Auto-correcting would double-count DCA costs and cause massive phantom losses.
            dca_sum = sum(float(e.get('amount_eur', 0) or 0) for e in dca_events if isinstance(e, dict))
            expected_total = initial + dca_sum
            if dca_sum > 0 and abs(total - expected_total) > 0.50:
                log(f"VALIDATION WARN [{market}]: total_invested_eur={total:.2f} != initial({initial:.2f}) + DCA({dca_sum:.2f}) = {expected_total:.2f} — NOT auto-correcting (initial may include synced DCA costs)", level='warning')
        if actual_dca_count == 0 and dca_buys > 0:
            # FIX #006: No events tracked → synced position, no bot DCAs.
            # Reset dca_buys to 0.
            log(f"VALIDATION FIX [{market}]: dca_buys={dca_buys} -> 0 (no dca_events, synced position)", level='warning')
            trade['dca_buys'] = 0
            needs_fix = True
        elif dca_buys < actual_dca_count:
            # More events than dca_buys → increase to match
            log(f"VALIDATION FIX [{market}]: dca_buys={dca_buys} -> {actual_dca_count} (matched to dca_events)", level='warning')
            trade['dca_buys'] = actual_dca_count
            needs_fix = True
        # If dca_buys > actual_dca_count > 0: events were lost during
        # sync/restart. Keep dca_buys to prevent duplicate DCA at same level.
        
        if needs_fix:
            fixed_count += 1
    
    if fixed_count > 0:
        log(f"VALIDATION: Fixed {fixed_count} corrupted trades before save", level='warning')
    
    return data


def save_snapshot(
    data: Dict[str, Any],
    json_path: str | os.PathLike[str] = TRADE_JSON_DEFAULT,
    *,
    backup_path: str | os.PathLike[str] | None = None,
    indent: int = 2,
) -> None:
    """Write trade log data to JSON and TinyDB."""

    if not isinstance(data, dict):
        raise TypeError('trade log snapshot must be a dict')

    # CRITICAL: Validate and fix data before saving
    data = _validate_and_fix_trade_data(data)

    path = Path(json_path)
    backup_file: Path | None = Path(backup_path) if backup_path else None

    if backup_file:
        try:
            if path.exists():
                backup_file.write_text(path.read_text(encoding='utf-8'), encoding='utf-8')
        except Exception as exc:
            log(f"TradeStore: backup schrijven mislukt ({backup_file}): {exc}", level='warning')

    locked_write_json(str(path), data, indent=indent)
    meta = _collect_file_meta(path)
    _persist_snapshot(data, meta)


def touch_snapshot_timestamp(json_path: str | os.PathLike[str] = TRADE_JSON_DEFAULT) -> None:
    """Update only the meta record so TinyDB stays aware of external JSON changes."""

    path = Path(json_path)
    meta = _collect_file_meta(path)
    _persist_snapshot(_load_snapshot_table() or {'open': {}, 'closed': []}, meta)


__all__ = ['load_snapshot', 'save_snapshot', 'touch_snapshot_timestamp']
