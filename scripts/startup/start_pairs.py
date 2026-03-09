"""Lightweight runner for the spot–spot pairs arbitrage pilot (Golf 3).

Usage:
    python scripts/startup/start_pairs.py

Reads bot_config.json, instantiates PairsArbitrageEngine and keeps it ticking
until interrupted (Ctrl+C / SIGTERM).  The engine writes state snapshots to
configurable JSON files so dashboards or other services can consume the data.
"""
from __future__ import annotations

import signal
import sys
import time
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from modules.config import load_config  # noqa: E402
from modules.logging_utils import log  # noqa: E402
from modules.pairs_arbitrage import PairsArbitrageEngine  # noqa: E402
from modules.pairs_executor import PairsExecutor  # noqa: E402


def main() -> None:
    config = load_config()
    executor: Optional[PairsExecutor] = None
    try:
        executor_candidate = PairsExecutor(config)
        if executor_candidate.active:
            executor = executor_candidate
        else:
            log("Pairs-executor staat uit of heeft geen notional; draai alleen signalen.", level="info")
    except Exception as exc:
        log(f"Pairs-executor kon niet initialiseren: {exc}", level="error")

    engine = PairsArbitrageEngine(config, signal_executor=executor)
    if not engine.enabled:
        log("Pairs-arbitrage staat uit in config; stop runner.", level="warning")
        return

    interval = max(5, int(engine.settings.get("poll_interval_seconds", 30)))
    exec_status = "aan" if executor else "uit"
    exec_dry = executor.dry_run if executor else True
    log(
        f"Pairs-arbitrage runner gestart (interval {interval}s, dry_run={engine.dry_run}, executor={exec_status}, exec_dry_run={exec_dry})"
    )

    stop_flag = {"stop": False}

    def _shutdown(signum, _frame):
        if stop_flag["stop"]:
            return
        stop_flag["stop"] = True
        log(f"Ontvangen signaal {signum}; stop pairs-arbitrage runner.", level="warning")

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _shutdown)
        except Exception:
            pass

    while not stop_flag["stop"]:
        try:
            engine.tick()
        except Exception as exc:
            log(f"Pairs tick faalde: {exc}", level="error")
        for _ in range(interval):
            if stop_flag["stop"]:
                break
            time.sleep(1)

    log("Pairs-arbitrage runner gestopt.")


if __name__ == "__main__":
    main()
