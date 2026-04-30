"""bot.event_hooks_adapter — Wrapper around `modules.event_hooks.EventState`.

Extracted from `trailing_bot.py` (#066 batch 4). Provides a singleton
`EVENT_STATE` plus pause-status helpers used by the main loop.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from bot.shared import state

try:
    from modules.event_hooks import EventState as _EventState
except Exception:  # pragma: no cover - optional dependency
    _EventState = None  # type: ignore


def _make_event_state():
    if _EventState is None:
        return None
    try:
        return _EventState()
    except Exception:
        return None


EVENT_STATE = _make_event_state()
_EVENT_PAUSE_CACHE: Dict[str, bool] = {}


def _log(msg: str, level: str = 'info') -> None:
    try:
        state.log(msg, level=level)
    except Exception:
        pass


def event_hooks_paused(market: str) -> bool:
    """Return True if a market (or global) pause is active via event hooks."""
    if not EVENT_STATE or not getattr(EVENT_STATE, "enabled", False):
        if _EVENT_PAUSE_CACHE.get(market):
            _EVENT_PAUSE_CACHE[market] = False
        return False
    try:
        paused = EVENT_STATE.market_paused(market)
    except Exception as exc:
        _log(f"[event_hooks] Kon pausestatus niet ophalen voor {market}: {exc}", level='warning')
        return False
    previous = _EVENT_PAUSE_CACHE.get(market)
    if paused and previous is not True:
        _log(f"[event_hooks] Pauze actief voor {market} -> nieuwe entries geblokkeerd", level='info')
    elif not paused and previous:
        _log(f"[event_hooks] Pauze opgeheven voor {market}", level='info')
    _EVENT_PAUSE_CACHE[market] = paused
    return paused


def event_hook_status_payload() -> Dict[str, Any]:
    if not EVENT_STATE:
        return {"enabled": False}
    try:
        records = EVENT_STATE.active_actions()
    except Exception as exc:
        _log(f"[event_hooks] Status opvragen mislukt: {exc}", level='debug')
        return {"enabled": getattr(EVENT_STATE, "enabled", False)}
    formatted = [
        {
            "market": rec.market or "GLOBAL",
            "action": rec.action,
            "message": rec.message,
            "expires_ts": rec.expires_ts,
        }
        for rec in records
    ]
    return {
        "enabled": getattr(EVENT_STATE, "enabled", False),
        "active": formatted,
        "last_refresh": time.time(),
    }
