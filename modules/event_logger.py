"""Structured JSON event logger — appends one JSON object per line.

Use for machine-readable events (filterable via jq, ingestable by ELK/Loki).
Independent of the human log under `logs/bot.log`.

Usage:
    from modules.event_logger import log_event
    log_event("trade_open", market="BTC-EUR", price=43000.0, score=8.5)
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_DEFAULT_PATH = Path("logs") / "events.jsonl"


def _path() -> Path:
    p = os.environ.get("BOT_EVENTS_LOG", "")
    return Path(p) if p else _DEFAULT_PATH


def log_event(event: str, **fields: Any) -> None:
    """Append a single JSON event line. Never raises."""
    try:
        rec = {"ts": time.time(), "event": str(event), **fields}
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(rec, ensure_ascii=False, default=str)
        with _LOCK:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception:
        # Never let logging crash anything.
        pass


__all__ = ["log_event"]
