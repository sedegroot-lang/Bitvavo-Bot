"""Rate-limit alert helper — emits a throttled WARNING when any bucket exceeds threshold.

Pure / non-blocking. Reads from `bot.api.get_rate_limit_status()`.
Designed to be called periodically by `bot.scheduler` (e.g. every 30s).
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

_last_alert_ts: Dict[str, float] = {}
_DEFAULT_THRESHOLD = 0.80
_DEFAULT_COOLDOWN = 300.0  # 5 min between alerts per bucket


def check_and_alert(
    *,
    threshold: float = _DEFAULT_THRESHOLD,
    cooldown_sec: float = _DEFAULT_COOLDOWN,
    log_fn: Optional[Callable[..., None]] = None,
    status_fn: Optional[Callable[[], Dict[str, Any]]] = None,
) -> Dict[str, float]:
    """Check rate-limit usage. Returns dict {bucket: usage_ratio} that breached threshold.

    Logs a WARNING per bucket at most once per `cooldown_sec`.
    """
    if status_fn is None:
        try:
            from bot.api import get_rate_limit_status as status_fn  # type: ignore
        except Exception:
            return {}
    try:
        snapshot = status_fn() or {}
    except Exception:
        return {}

    if log_fn is None:
        try:
            from modules.logging_utils import log as log_fn  # type: ignore
        except Exception:
            log_fn = None

    breached: Dict[str, float] = {}
    now = time.time()
    for bucket, info in snapshot.items():
        if not isinstance(info, dict):
            continue
        try:
            ratio = float(info.get("usage_ratio", 0.0) or 0.0)
        except Exception:
            ratio = 0.0
        if ratio < threshold:
            continue
        breached[bucket] = ratio
        last = _last_alert_ts.get(bucket, 0.0)
        if (now - last) >= cooldown_sec and log_fn is not None:
            try:
                log_fn(
                    f"[RateLimit] {bucket} op {ratio*100:.0f}% van quota "
                    f"(used={info.get('used')}/{info.get('limit')} window={info.get('window')}s)",
                    level="warning",
                )
            except Exception:
                pass
            _last_alert_ts[bucket] = now
    return breached


def reset_alert_state() -> None:
    """Test helper — clear cooldown memory."""
    _last_alert_ts.clear()
