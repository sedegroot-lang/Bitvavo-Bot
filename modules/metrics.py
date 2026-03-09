"""Metrics collection helpers for the Bitvavo bot."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional


__all__ = ["MetricsCollector", "configure", "get_collector"]


LogFn = Callable[[str], None]


@dataclass(slots=True)
class MetricsConfig:
	prom_path: Path
	influx_path: Path
	json_path: Path
	measurement: str = "bitvavo_bot"
	push_url: Optional[str] = None
	push_job: str = "bitvavo_bot"


class MetricsCollector:
	"""Persist metrics snapshots in Prometheus, Influx and JSON formats."""

	def __init__(self, config: MetricsConfig, log: Optional[LogFn] = None) -> None:
		self._cfg = config
		self._log = log or (lambda msg: None)
		self._lock = threading.RLock()
		self._counters: Dict[str, float] = {}
		for path in (config.prom_path, config.influx_path, config.json_path):
			path.parent.mkdir(parents=True, exist_ok=True)

	def publish(
		self,
		metrics: Mapping[str, float],
		*,
		counters: Optional[Mapping[str, float]] = None,
		labels: Optional[Mapping[str, str]] = None,
		timestamp: Optional[float] = None,
	) -> None:
		with self._lock:
			if counters:
				for name, value in counters.items():
					if value is None:
						continue
					self._counters[name] = self._counters.get(name, 0.0) + float(value)
			payload: Dict[str, float] = {k: float(v) for k, v in metrics.items() if v is not None}
			for name, value in self._counters.items():
				payload[f"{name}_total"] = float(value)
			ts = float(timestamp or time.time())
			self._write_prometheus(payload, labels)
			self._write_influx(payload, labels, ts)
			self._write_json(payload, labels, ts)
			self._pushgateway(payload, labels)

	def increment_counter(self, name: str, value: float = 1.0) -> None:
		with self._lock:
			self._counters[name] = self._counters.get(name, 0.0) + float(value)

	# ------------------------------------------------------------------
	# Writers
	# ------------------------------------------------------------------
	def _write_prometheus(self, metrics: Mapping[str, float], labels: Optional[Mapping[str, str]]) -> None:
		lines = []
		label_txt = ""
		if labels:
			pairs = ",".join(f"{k}={self._quote_prom(v)}" for k, v in sorted(labels.items()))
			label_txt = f"{{{pairs}}}"
		for name, value in sorted(metrics.items()):
			if value is None:
				continue
			lines.append(f"# TYPE {name} gauge")
			lines.append(f"{name}{label_txt} {float(value):.6f}")
		content = "\n".join(lines) + "\n"
		try:
			self._cfg.prom_path.write_text(content, encoding="utf-8")
		except Exception as exc:  # pragma: no cover - filesystem edge cases
			self._log(f"MetricsCollector: kon Prometheus output niet schrijven: {exc}")

	def _write_influx(
		self,
		metrics: Mapping[str, float],
		labels: Optional[Mapping[str, str]],
		timestamp: float,
	) -> None:
		fields = []
		for name, value in sorted(metrics.items()):
			if value is None:
				continue
			fields.append(f"{name}={float(value):.6f}")
		if not fields:
			return
		label_txt = ""
		if labels:
			label_txt = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
		measurement = self._cfg.measurement
		if label_txt:
			measurement = f"{measurement},{label_txt}"
		line = f"{measurement} {','.join(fields)} {int(timestamp * 1_000_000_000)}\n"
		try:
			self._cfg.influx_path.write_text(line, encoding="utf-8")
		except Exception as exc:  # pragma: no cover
			self._log(f"MetricsCollector: kon Influx output niet schrijven: {exc}")

	def _write_json(
		self,
		metrics: Mapping[str, float],
		labels: Optional[Mapping[str, str]],
		timestamp: float,
	) -> None:
		payload = {
			"timestamp": int(timestamp),
			"metrics": dict(metrics),
			"labels": dict(labels or {}),
		}
		try:
			self._cfg.json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
		except Exception as exc:  # pragma: no cover
			self._log(f"MetricsCollector: kon JSON output niet schrijven: {exc}")

	def _pushgateway(self, metrics: Mapping[str, float], labels: Optional[Mapping[str, str]]) -> None:
		if not self._cfg.push_url:
			return
		try:
			import requests  # type: ignore
		except Exception:  # pragma: no cover - requests optional
			return
		label_txt = ""
		if labels:
			pairs = ",".join(f"{k}={self._quote_prom(v)}" for k, v in sorted(labels.items()))
			label_txt = f"{{{pairs}}}"
		lines = []
		for name, value in sorted(metrics.items()):
			if value is None:
				continue
			lines.append(f"{name}{label_txt} {float(value):.6f}")
		body = "\n".join(lines) + "\n"
		url = f"{self._cfg.push_url.rstrip('/')}/metrics/job/{self._cfg.push_job}"
		try:
			requests.post(url, data=body, timeout=2)
		except Exception as exc:  # pragma: no cover - network optional
			self._log(f"MetricsCollector: pushgateway post mislukt: {exc}")

	# ------------------------------------------------------------------
	# Helpers
	# ------------------------------------------------------------------
	@staticmethod
	def _quote_prom(value: str) -> str:
		escaped = (
			str(value)
			.replace("\\", "\\\\")
			.replace("\n", "\\n")
			.replace("\"", "\\\"")
		)
		return f'"{escaped}"'


_COLLECTOR: Optional[MetricsCollector] = None


def configure(config: Mapping[str, object], log: Optional[LogFn] = None) -> MetricsCollector:
	"""Initialise the global metrics collector from configuration."""

	prom_path = Path(str(config.get("METRICS_PROM_PATH", "metrics/bot_metrics.prom")))
	influx_path = Path(str(config.get("METRICS_INFLUX_PATH", "metrics/bot_metrics.lp")))
	json_path = Path(str(config.get("METRICS_JSON_PATH", "metrics/latest_metrics.json")))
	measurement = str(config.get("METRICS_MEASUREMENT", "bitvavo_bot"))
	push_url_raw = config.get("METRICS_PUSH_URL")
	push_url = str(push_url_raw) if push_url_raw else None
	push_job = str(config.get("METRICS_PUSH_JOB", "bitvavo_bot"))
	metrics_cfg = MetricsConfig(
		prom_path=prom_path,
		influx_path=influx_path,
		json_path=json_path,
		measurement=measurement,
		push_url=push_url,
		push_job=push_job,
	)
	collector = MetricsCollector(metrics_cfg, log=log)
	global _COLLECTOR
	_COLLECTOR = collector
	return collector


def get_collector() -> Optional[MetricsCollector]:
	return _COLLECTOR
