"""bot.scheduler — Background-thread orchestration extracted from trailing_bot.py.

Thin facade over `monitoring_manager` + `synchronizer`. All start helpers are
idempotent (no-op when components missing) and return None. Used by
`trailing_bot.py` startup. Lives here so the monolith no longer owns thread
lifecycle code.

Road-to-10 #062: makes scheduler responsibilities discoverable and unit-testable.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

from bot.shared import state


def start_heartbeat_monitor(*, alert_stale_seconds: float = 300.0, interval: int = 60) -> None:
    mgr = getattr(state, 'monitoring_manager', None) or globals().get('monitoring_manager')
    if mgr is None:
        return
    try:
        mgr.start_heartbeat_monitor(
            state.send_alert,
            alert_stale_seconds=alert_stale_seconds,
            interval=interval,
        )
    except Exception as exc:
        state.log(f"start_heartbeat_monitor failed: {exc}", level='warning')


def start_heartbeat_writer(
    *,
    interval: int = 30,
    scan_stats_provider: Optional[Callable[[], Dict]] = None,
) -> None:
    mgr = getattr(state, 'monitoring_manager', None) or globals().get('monitoring_manager')
    if mgr is None:
        return
    try:
        mgr.start_heartbeat_writer(
            lambda: dict(state.open_trades or {}),
            state._get_pending_markets_dict,
            interval=interval,
            dust_threshold_eur=getattr(state, 'DUST_TRADE_THRESHOLD_EUR', 5.0),
            scan_stats_provider=scan_stats_provider or (lambda: dict(state.CONFIG.get('LAST_SCAN_STATS', {}) or {})),
        )
    except Exception as exc:
        state.log(f"start_heartbeat_writer failed: {exc}", level='warning')


def start_reservation_watchdog(*, interval: int = 30) -> None:
    mgr = getattr(state, 'monitoring_manager', None) or globals().get('monitoring_manager')
    if mgr is None:
        return
    try:
        mgr.start_reservation_watchdog(state._get_pending_markets_dict, interval=interval)
    except Exception as exc:
        state.log(f"start_reservation_watchdog failed: {exc}", level='warning')


def start_all_schedulers() -> Dict[str, bool]:
    """Convenience: kick off all background threads. Returns status dict."""
    out: Dict[str, bool] = {}
    for name, fn in (
        ('heartbeat_monitor', start_heartbeat_monitor),
        ('heartbeat_writer', start_heartbeat_writer),
        ('reservation_watchdog', start_reservation_watchdog),
    ):
        try:
            fn()
            out[name] = True
        except Exception as exc:
            state.log(f"scheduler.{name} failed: {exc}", level='warning')
            out[name] = False
    return out


def check_rate_limits(threshold: float = 0.80, cooldown_sec: float = 300.0) -> Dict[str, float]:
    """Periodic rate-limit health check — emits WARNING when any bucket exceeds threshold.

    Designed to be called every ~30s from the main loop. Returns breached buckets.
    """
    try:
        from bot.rate_limit_alert import check_and_alert
        return check_and_alert(threshold=threshold, cooldown_sec=cooldown_sec, log_fn=state.log)
    except Exception as exc:
        try:
            state.log(f"check_rate_limits failed: {exc}", level='debug')
        except Exception:
            pass
        return {}
