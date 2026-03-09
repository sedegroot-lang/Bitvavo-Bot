"""Automation helpers for managing the QUARANTINE_MARKETS kill-switch list.

This module keeps the existing hard block (config-driven) but adds metadata so
AI governance can periodically re-evaluate quarantined markets and, when safe,
route them back through the watchlist flow before re-entering live trading.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from modules.logging_utils import log
from modules.watchlist_manager import queue_market_for_watchlist
from modules.ai_markets import evaluate_market_guardrails

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / 'config' / 'bot_config.json'
STATE_PATH = PROJECT_ROOT / 'data' / 'quarantine_state.json'


def _load_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        with path.open('r', encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return default


def _write_json(path: Path, payload: Any) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + '.tmp')
        with tmp.open('w', encoding='utf-8') as fh:
            json.dump(payload, fh, indent=2)
        tmp.replace(path)
        return True
    except Exception as exc:
        log(f"quarantine_manager: failed to write {path.name}: {exc}", level='error')
        return False


def _load_config() -> Dict[str, Any]:
    return _load_json(CONFIG_PATH, {}) or {}


def _write_config(cfg: Dict[str, Any]) -> bool:
    return _write_json(CONFIG_PATH, cfg)


def _load_state() -> Dict[str, Any]:
    state = _load_json(STATE_PATH, {'markets': {}, 'last_review_ts': 0})
    if not isinstance(state, dict):
        state = {'markets': {}, 'last_review_ts': 0}
    state.setdefault('markets', {})
    state.setdefault('last_review_ts', 0)
    return state


def _save_state(state: Dict[str, Any]) -> bool:
    return _write_json(STATE_PATH, state)


def get_quarantine_list(cfg: Optional[Dict[str, Any]] = None) -> List[str]:
    cfg = cfg or _load_config()
    qlist = cfg.get('QUARANTINE_MARKETS') or []
    return list(qlist)


def _sync_state_with_config(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = cfg or _load_config()
    state = _load_state()
    markets_state = state.setdefault('markets', {})
    now = time.time()
    changed = False
    for market in get_quarantine_list(cfg):
        entry = markets_state.get(market)
        if not entry:
            markets_state[market] = {
                'market': market,
                'added_ts': now,
                'status': 'quarantined',
                'reason': 'manual',
                'source': 'config',
            }
            changed = True
    # Flag entries that left the config list
    config_set = set(get_quarantine_list(cfg))
    for market, entry in list(markets_state.items()):
        if market not in config_set and entry.get('status') == 'quarantined':
            entry['status'] = 'removed'
            entry['removed_ts'] = now
            markets_state[market] = entry
            changed = True
    if changed:
        _save_state(state)
    return state


def remove_from_quarantine(market: str, cfg: Optional[Dict[str, Any]] = None) -> bool:
    cfg = cfg or _load_config()
    qlist = get_quarantine_list(cfg)
    if market not in qlist:
        return True
    qlist = [m for m in qlist if m != market]
    cfg['QUARANTINE_MARKETS'] = qlist
    if not _write_config(cfg):
        return False
    state = _load_state()
    entry = state.get('markets', {}).get(market)
    now = time.time()
    if entry:
        entry['status'] = 'removed'
        entry['removed_ts'] = now
        state['markets'][market] = entry
        _save_state(state)
    return True


def add_to_quarantine(
    market: str,
    *,
    reason: str = 'manual',
    source: str = 'manual',
    cfg: Optional[Dict[str, Any]] = None,
) -> bool:
    cfg = cfg or _load_config()
    qlist = get_quarantine_list(cfg)
    if market not in qlist:
        qlist.append(market)
        cfg['QUARANTINE_MARKETS'] = qlist
        if not _write_config(cfg):
            return False
    state = _load_state()
    entry = state.setdefault('markets', {}).get(market, {})
    entry.update({
        'market': market,
        'added_ts': entry.get('added_ts', time.time()),
        'status': 'quarantined',
        'reason': reason,
        'source': source,
    })
    state['markets'][market] = entry
    _save_state(state)
    log(f"[QUARANTINE] {market} added ({reason})", level='warning')
    return True


def review_quarantine(cfg: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    cfg = cfg or _load_config()
    settings = cfg.get('QUARANTINE_SETTINGS') or {}
    if not settings.get('enabled', True):
        return []
    qlist = get_quarantine_list(cfg)
    if not qlist:
        return []

    state = _sync_state_with_config(cfg)
    markets_state = state.get('markets', {})
    now = time.time()
    min_age_days = max(1, int(settings.get('review_after_days', 7)))
    min_age_seconds = min_age_days * 86400
    max_promotions = max(1, int(settings.get('max_promotions_per_cycle', 1)))
    review_limit = max_promotions if settings.get('review_max_markets') in (None, 0) else max(1, int(settings.get('review_max_markets')))
    reviewed = 0
    promotions = 0
    actions: List[Dict[str, Any]] = []

    for market in qlist:
        if reviewed >= review_limit or promotions >= max_promotions:
            break
        reviewed += 1
        entry = markets_state.get(market) or {'market': market}
        added_ts = float(entry.get('added_ts') or now)
        entry['last_review_ts'] = now
        if (now - added_ts) < min_age_seconds:
            entry['last_review_reason'] = 'waiting_for_min_age'
            markets_state[market] = entry
            continue

        guard = evaluate_market_guardrails(market, cfg)
        entry['last_guardrail_check'] = guard
        if settings.get('release_requires_guardrails', True) and not guard.get('ok', False):
            entry['last_review_reason'] = 'guardrails_failed'
            markets_state[market] = entry
            continue

        queued = queue_market_for_watchlist(
            market,
            reason='quarantine review passed',
            source='quarantine',
            cfg=cfg,
        )
        if not queued:
            entry['last_review_reason'] = 'watchlist_queue_failed'
            markets_state[market] = entry
            continue

        if remove_from_quarantine(market, cfg):
            promotions += 1
            entry['status'] = 'released'
            entry['released_ts'] = now
            entry['last_review_reason'] = 'released'
            markets_state[market] = entry
            actions.append({'action': 'released', 'market': market})
            log(f"[QUARANTINE] Released {market} -> watchlist", level='info')
        else:
            entry['last_review_reason'] = 'remove_failed'
            markets_state[market] = entry

    state['markets'] = markets_state
    state['last_review_ts'] = now
    _save_state(state)
    if actions:
        log(f"[QUARANTINE] Review complete: {len(actions)} release(s)", level='info')
    return actions
