"""Event-driven hooks for pausing/resuming bot components."""

from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from modules.logging_utils import log


@dataclass
class EventRecord:
    market: Optional[str]
    action: str
    message: str
    expires_ts: float


class EventState:
    def __init__(self, config: Dict | None = None) -> None:
        from modules.config import load_config

        cfg = config or load_config()
        hooks_cfg = (cfg or {}).get("EVENT_HOOKS", {})
        self.enabled = bool(hooks_cfg.get("enabled", True))
        self.watch_dir = Path(hooks_cfg.get("watch_dir", "data/event_hooks"))
        self.state_file = Path(hooks_cfg.get("state_file", "data/event_hooks_state.json"))
        self.auto_pause_minutes = int(hooks_cfg.get("auto_pause_minutes", 30))
        self.allow_resume = bool(hooks_cfg.get("allow_resume", True))
        self.records: Dict[str, EventRecord] = {}
        self._load_state()

    # --------------------------- persistence ----------------------------
    def _load_state(self) -> None:
        if not self.state_file.exists():
            return
        try:
            doc = json.loads(self.state_file.read_text(encoding="utf-8"))
            for market, rec in (doc.get("records") or {}).items():
                self.records[market] = EventRecord(
                    market if market != "__global__" else None,
                    rec.get("action", "pause"),
                    rec.get("message", ""),
                    float(rec.get("expires_ts") or 0.0),
                )
        except Exception:
            self.records = {}

    def _save_state(self) -> None:
        payload = {
            "updated_at": time.time(),
            "records": {
                (rec.market or "__global__"): {
                    "action": rec.action,
                    "message": rec.message,
                    "expires_ts": rec.expires_ts,
                }
                for rec in self.records.values()
            },
        }
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ------------------------- ingestion logic -------------------------
    def _parse_event_row(self, row: Dict[str, str]) -> Optional[EventRecord]:
        action = (row.get("action") or "").strip().lower()
        if action not in {"pause", "resume", "signal"}:
            return None
        market = (row.get("market") or row.get("symbol") or "").strip().upper() or None
        message = row.get("message") or row.get("reason") or ""
        ttl_minutes = int(row.get("ttl_minutes") or self.auto_pause_minutes)
        expires = time.time() + ttl_minutes * 60
        return EventRecord(market=market, action=action, message=message, expires_ts=expires)

    def _ingest_file(self, path: Path) -> None:
        try:
            if path.suffix.lower() == ".json":
                payload = json.loads(path.read_text(encoding="utf-8"))
                rows = payload if isinstance(payload, list) else payload.get("events", [])
                for row in rows or []:
                    if not isinstance(row, dict):
                        continue
                    rec = self._parse_event_row(row)
                    if rec:
                        self._apply_record(rec)
            else:
                with path.open("r", encoding="utf-8") as fh:
                    reader = csv.DictReader(fh)
                    for row in reader:
                        rec = self._parse_event_row(row)
                        if rec:
                            self._apply_record(rec)
            # move processed file aside
            processed_dir = path.parent / "processed"
            processed_dir.mkdir(parents=True, exist_ok=True)
            path.rename(processed_dir / path.name)
        except Exception as exc:
            log(f"[event_hooks] Kon bestand {path} niet verwerken: {exc}", level="error")

    def _apply_record(self, rec: EventRecord) -> None:
        key = rec.market or "__global__"
        if rec.action == "resume" and self.allow_resume:
            self.records.pop(key, None)
            log(f"[event_hooks] Markten hervat via hook ({rec.market or 'GLOBAL'})")
        else:
            self.records[key] = rec
            log(f"[event_hooks] Event '{rec.action}' voor {rec.market or 'GLOBAL'}: {rec.message}")
        self._save_state()

    def refresh(self) -> None:
        if not self.enabled:
            return
        if not self.watch_dir.exists():
            return
        for path in sorted(self.watch_dir.glob("*")):
            if path.is_dir():
                continue
            if path.suffix.lower() not in {".csv", ".json"}:
                continue
            self._ingest_file(path)
        # purge expired
        now = time.time()
        for key, rec in list(self.records.items()):
            if rec.expires_ts and rec.expires_ts < now:
                self.records.pop(key, None)
        self._save_state()

    # -------------------------- public access ---------------------------
    def market_paused(self, market: str) -> bool:
        if not self.enabled:
            return False
        self.refresh()
        rec = self.records.get(market)
        if rec and rec.action == "pause":
            return True
        global_rec = self.records.get("__global__")
        return bool(global_rec and global_rec.action == "pause")

    def active_actions(self) -> List[EventRecord]:
        self.refresh()
        return list(self.records.values())


__all__ = ["EventState", "EventRecord"]
