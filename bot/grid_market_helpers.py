"""Grid market helpers (extracted from trailing_bot.py — road-to-10 #066 batch 7).

Returns the set of markets currently active in grid trading so the trailing
bot/HODL flows can exclude them.
"""

from __future__ import annotations

from bot.shared import state


def get_active_grid_markets() -> set:
    """Get set of markets that are currently active in grid trading.

    Returns empty set when GRID_TRADING is disabled in config (FIX #043) —
    stale grid_states.json on disk must not block the trailing bot from
    trading those markets.
    """
    log = state.log
    grid_markets: set = set()
    try:
        grid_cfg = state.CONFIG.get("GRID_TRADING") or {}
        if not bool(grid_cfg.get("enabled", False)):
            return grid_markets
    except Exception:
        return grid_markets
    try:
        from modules.grid_trading import get_grid_manager  # type: ignore

        grid_manager = get_grid_manager()
        for grid_summary in grid_manager.get_all_grids_summary():
            if grid_summary.get("status") in ("running", "paused", "initialized"):
                grid_markets.add(grid_summary.get("market"))
    except ImportError as e:
        try:
            log(f"get_grid_manager failed: {e}", level="warning")
        except Exception:
            pass
    except Exception as e:
        try:
            log(f"get_grid_manager failed: {e}", level="warning")
        except Exception:
            pass
    return grid_markets
