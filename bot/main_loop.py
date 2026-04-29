"""Thin entry-point wrapper around the legacy `trailing_bot.bot_loop`.

The eventual goal is to fully extract the main scan/manage loop out of the
~4,300-line `trailing_bot.py` monolith and into this module. This file is the
seam where that extraction starts: today it just re-exports the existing
function so callers can switch to importing from `bot.main_loop` without
touching the monolith. As pieces of `bot_loop()` are pulled out, they should
land in this module.

Public API:
    bot_loop()          — the recurring scan/manage tick (legacy).
    run(once=False)     — thin runner. ``once=True`` calls bot_loop once;
                          otherwise it loops forever with sleep cadence
                          driven by ``CONFIG['BOT_LOOP_INTERVAL']``
                          (default 25 s).
"""
from __future__ import annotations

import time
from typing import Any

from modules.logging_utils import log

# Lazy import to avoid heavy startup cost at import time.
def _load_bot_loop():
    from trailing_bot import bot_loop  # type: ignore
    return bot_loop


def bot_loop(*args: Any, **kwargs: Any):
    """Forward to the legacy implementation in `trailing_bot.bot_loop`."""
    fn = _load_bot_loop()
    return fn(*args, **kwargs)


def run(once: bool = False) -> None:
    """Run the main loop. ``once=True`` for tests/scripts; otherwise loops."""
    from modules.config import CONFIG  # local import: config may not be init'd yet
    if once:
        bot_loop()
        return
    interval = float(CONFIG.get("BOT_LOOP_INTERVAL", 25))
    while True:
        try:
            bot_loop()
        except Exception as exc:  # noqa: BLE001 — never crash the loop
            log(f"[main_loop] tick error: {exc}", level="error")
        time.sleep(max(1.0, interval))


__all__ = ["bot_loop", "run"]
