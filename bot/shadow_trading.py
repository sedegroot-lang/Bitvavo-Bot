"""bot.shadow_trading — Append-only shadow log for would-be trades.

Roadmap fase 4: log every entry-decision (and the EntryDecision/confidence)
to ``data/shadow_trades.jsonl`` so we can verify model output for ≥1 week
before letting it gate live entries.

Pure helpers, no I/O risk: every write is wrapped in try/except.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict

from bot.shared import state

_SHADOW_PATH = Path(__file__).resolve().parent.parent / "data" / "shadow_trades.jsonl"


def log_shadow_entry(market: str, payload: Dict[str, Any]) -> bool:
    """Append a shadow entry. Returns True on success, False on (silent) failure."""
    if not bool(state.CONFIG.get("SHADOW_TRADING_ENABLED", False)):
        return False
    try:
        record = {
            "ts": time.time(),
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "market": market,
            "payload": payload,
        }
        _SHADOW_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_SHADOW_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
        return True
    except Exception:
        return False


def shadow_path() -> Path:
    return _SHADOW_PATH
