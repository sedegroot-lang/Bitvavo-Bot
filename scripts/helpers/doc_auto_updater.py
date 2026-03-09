"""Documentation auto-updater daemon.

Periodically regenerates documentation files that include runtime statistics,
such as the architecture overview or config reference metadata.
Runs in a background daemon thread so it never blocks the bot.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DOCS_DIR = _PROJECT_ROOT / "docs"
_CONFIG_PATH = _PROJECT_ROOT / "config" / "bot_config.json"
_HEARTBEAT_PATH = _PROJECT_ROOT / "data" / "doc_sync_heartbeat.json"

_thread: threading.Thread | None = None
_running = False


def _write_heartbeat() -> None:
    """Write a small heartbeat file so monitoring knows the updater is alive."""
    try:
        _HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_run": datetime.now(timezone.utc).isoformat(),
            "status": "ok",
        }
        tmp = _HEARTBEAT_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(_HEARTBEAT_PATH)
    except Exception:
        pass  # Non-critical


def _update_architecture_stats() -> None:
    """Update ARCHITECTURE.md with current line counts if markers are present."""
    arch_path = _DOCS_DIR / "ARCHITECTURE.md"
    if not arch_path.exists():
        return

    try:
        bot_path = _PROJECT_ROOT / "trailing_bot.py"
        if bot_path.exists():
            line_count = sum(1 for _ in bot_path.open(encoding="utf-8", errors="ignore"))
        else:
            line_count = 0

        content = arch_path.read_text(encoding="utf-8")

        # Replace line count marker if present: <!-- BOT_LINES:XXXX -->
        import re
        new_content = re.sub(
            r"<!-- BOT_LINES:\d+ -->",
            f"<!-- BOT_LINES:{line_count} -->",
            content,
        )
        if new_content != content:
            tmp = arch_path.with_suffix(".tmp")
            tmp.write_text(new_content, encoding="utf-8")
            tmp.replace(arch_path)
    except Exception:
        pass


def _run_loop(interval: int) -> None:
    """Background loop that periodically refreshes documentation."""
    global _running
    while _running:
        try:
            _update_architecture_stats()
            _write_heartbeat()
        except Exception:
            pass  # Never crash the daemon

        # Sleep in small increments so we can stop quickly
        for _ in range(interval):
            if not _running:
                break
            time.sleep(1)


def start_doc_updater(update_interval_seconds: int = 300) -> None:
    """Start the documentation auto-updater as a daemon thread.

    Args:
        update_interval_seconds: How often to refresh docs (default 5 min).
    """
    global _thread, _running

    if _thread is not None and _thread.is_alive():
        return  # Already running

    _running = True
    _thread = threading.Thread(
        target=_run_loop,
        args=(update_interval_seconds,),
        daemon=True,
        name="doc-auto-updater",
    )
    _thread.start()


def stop_doc_updater() -> None:
    """Signal the updater thread to stop."""
    global _running
    _running = False
