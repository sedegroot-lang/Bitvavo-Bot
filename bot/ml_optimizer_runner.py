"""ML optimizer runner (extracted from trailing_bot.py — road-to-10 #066 batch 6).

Run the ML optimizer at most once per configured interval. State is owned at
module scope so the trailing_bot.py shim stays a one-liner.
"""

from __future__ import annotations

import asyncio
import time

from bot.shared import state

_LAST_RUN: float = 0.0


async def maybe_run() -> None:
    global _LAST_RUN
    log = state.log
    cfg = state.CONFIG
    try:
        interval = float(cfg.get("ML_OPTIMIZER_INTERVAL_SECONDS", 86400))
    except Exception:
        interval = 86400.0
    if interval <= 0:
        return
    now = time.time()
    if (now - _LAST_RUN) < interval:
        return
    try:
        from ai import ml_optimizer  # type: ignore

        try:
            log("Start ML-optimalisatie van parameters...")
        except Exception:
            pass
        if hasattr(ml_optimizer, "optimize_ml_parameters_async"):
            await ml_optimizer.optimize_ml_parameters_async()
        else:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, ml_optimizer.optimize_ml_parameters)
        _LAST_RUN = now
    except Exception as exc:
        try:
            log(f"ML-optimalisatie mislukt: {exc}", level="error")
        except Exception:
            pass
