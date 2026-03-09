"""Helpers for lightweight performance sampling of long-running processes."""

from __future__ import annotations

import json
import statistics
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable, Deque, List, Optional

try:  # psutil is optional; fall back gracefully when missing
    import psutil  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    psutil = None  # type: ignore


def _quantile(data: List[float], q: float) -> float:
    if not data:
        return 0.0
    if len(data) == 1:
        return data[0]
    try:
        return statistics.quantiles(data, n=100, method="inclusive")[int(q * 100) - 1]
    except Exception:
        idx = max(0, min(len(data) - 1, int(q * len(data)) - 1))
        return sorted(data)[idx]


class PerfSampler:
    """Collects iteration durations and process resource stats."""

    def __init__(
        self,
        name: str,
        sample_interval: float = 120.0,
        history_size: int = 600,
        log_fn: Optional[Callable[[str], None]] = None,
        metrics_file: Optional[str] = None,
    ) -> None:
        self._name = name
        self._sample_interval = max(5.0, float(sample_interval))
        self._log_fn = log_fn or (lambda msg: print(msg))
        self._metrics_path = Path(metrics_file) if metrics_file else None
        self._lock = threading.Lock()
        self._pending: List[float] = []
        self._history: Deque[float] = deque(maxlen=max(10, int(history_size)))
        self._failures = 0
        self._last_sample = 0.0
        if self._metrics_path:
            self._metrics_path.parent.mkdir(parents=True, exist_ok=True)
        if psutil is not None:
            try:
                self._process = psutil.Process()
                self._process.cpu_percent(interval=None)
            except Exception:  # pragma: no cover - psutil edge cases
                self._process = None
        else:
            self._process = None

    def start_iteration(self) -> float:
        return time.perf_counter()

    def end_iteration(self, token: Optional[float], failed: bool = False) -> None:
        if token is None:
            return
        duration = max(0.0, time.perf_counter() - token)
        with self._lock:
            self._pending.append(duration)
            self._history.append(duration)
            if failed:
                self._failures += 1
        self._maybe_emit(force=failed)

    def record_exception(self) -> None:
        with self._lock:
            self._failures += 1
        self._maybe_emit(force=True)

    def _maybe_emit(self, force: bool = False) -> None:
        now = time.time()
        if not force and (now - self._last_sample) < self._sample_interval:
            return
        with self._lock:
            batch = list(self._pending)
            history = list(self._history)
            failures = self._failures
            self._pending.clear()
            self._failures = 0
            self._last_sample = now
        if not batch and not failures and not force:
            return
        avg_duration = statistics.mean(batch) if batch else 0.0
        p95_duration = _quantile(batch, 0.95) if batch else 0.0
        max_duration = max(batch) if batch else 0.0
        iterations = len(batch)
        per_minute = (iterations / max(self._sample_interval, 1.0)) * 60.0
        cpu_pct = None
        rss_mb = None
        threads = None
        if self._process is not None:
            try:
                cpu_pct = self._process.cpu_percent(interval=None)
                mem = self._process.memory_info()
                rss_mb = mem.rss / (1024 * 1024)
                threads = self._process.num_threads()
            except Exception:  # pragma: no cover - psutil edge cases
                cpu_pct = None
        summary = {
            "name": self._name,
            "timestamp": int(now),
            "iterations": iterations,
            "iter_avg_ms": round(avg_duration * 1000, 2),
            "iter_p95_ms": round(p95_duration * 1000, 2),
            "iter_max_ms": round(max_duration * 1000, 2),
            "iter_per_minute": round(per_minute, 2),
            "failures": failures,
            "cpu_percent": round(cpu_pct, 2) if cpu_pct is not None else None,
            "rss_mb": round(rss_mb, 2) if rss_mb is not None else None,
            "threads": threads,
            "history_window": len(history),
            "history_avg_ms": round(statistics.mean(history) * 1000, 2) if history else 0.0,
        }
        self._log(summary)
        if self._metrics_path:
            try:
                with self._metrics_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(summary) + "\n")
            except Exception:  # pragma: no cover - file IO edge cases
                pass

    def _log(self, summary: dict) -> None:
        msg_parts = [
            f"{self._name} perf",
            f"avg={summary['iter_avg_ms']}ms",
            f"p95={summary['iter_p95_ms']}ms",
            f"max={summary['iter_max_ms']}ms",
            f"count={summary['iterations']}",
        ]
        if summary.get("cpu_percent") is not None:
            msg_parts.append(f"cpu={summary['cpu_percent']}%")
        if summary.get("rss_mb") is not None:
            msg_parts.append(f"rss={summary['rss_mb']}MB")
        if summary.get("threads") is not None:
            msg_parts.append(f"threads={summary['threads']}")
        if summary.get("failures"):
            msg_parts.append(f"failures={summary['failures']}")
        self._log_fn(" | ".join(msg_parts))
