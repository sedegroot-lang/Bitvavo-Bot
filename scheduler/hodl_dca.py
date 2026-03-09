"""Simple HODL/DCA scheduler that respects event hook pauses."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING

from modules.bitvavo_client import get_bitvavo, place_market_order
from modules.config import load_config
from modules.logging_utils import log

try:  # optional dependency
    from modules.event_hooks import EventState as EventStateImpl
except Exception:  # pragma: no cover
    EventStateImpl = None  # type: ignore

if TYPE_CHECKING:
    from modules.event_hooks import EventState


@dataclass
class HodlSchedule:
    market: str
    amount_eur: float
    interval_minutes: int
    dry_run: bool = True


class HodlScheduler:
    """Executes fixed-interval buys per market while honoring event pauses."""

    def __init__(self, config: Optional[Dict] = None, event_state: Optional["EventState"] = None) -> None:
        self.config = config or load_config() or {}
        self.settings = (self.config or {}).get("HODL_SCHEDULER", {}) or {}
        self.enabled = bool(self.settings.get("enabled", False))
        self.state_file = Path(self.settings.get("state_file", "data/hodl_schedule.json"))
        self.default_dry_run = bool(self.settings.get("dry_run", True))
        self.poll_interval = int(max(60, int(self.settings.get("poll_interval_seconds", 300))))
        self.schedules = self._load_schedules(self.settings.get("schedules") or [])
        self.state = self._load_state()
        self.event_state = event_state or (EventStateImpl() if EventStateImpl else None)

    def _load_schedules(self, raw_entries: List[Dict]) -> List[HodlSchedule]:
        schedules: List[HodlSchedule] = []
        for entry in raw_entries:
            if not isinstance(entry, dict):
                continue
            market = str(entry.get("market") or "").upper()
            if not market:
                continue
            try:
                amt = float(entry.get("amount_eur", 0))
                interval = int(entry.get("interval_minutes", 1440))
                dry_run = bool(entry.get("dry_run", self.default_dry_run))
            except Exception:
                continue
            if amt <= 0 or interval <= 0:
                continue
            schedules.append(HodlSchedule(market=market, amount_eur=amt, interval_minutes=interval, dry_run=dry_run))
        return schedules

    # ------------------------------ state ---------------------------------
    def _load_state(self) -> Dict[str, Dict[str, float]]:
        if not self.state_file.exists():
            return {"entries": {}}
        try:
            doc = json.loads(self.state_file.read_text(encoding="utf-8"))
            if isinstance(doc, dict):
                doc.setdefault("entries", {})
                return doc
        except Exception:
            pass
        return {"entries": {}}

    def _save_state(self) -> None:
        payload = {
            "updated_at": time.time(),
            "entries": self.state.get("entries", {}),
        }
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(self.state_file)
        except Exception as exc:
            log(f"[hodl_scheduler] Kon state niet opslaan: {exc}", level='warning')

    # --------------------------- helpers ----------------------------------
    def _current_price(self, market: str) -> float:
        client = get_bitvavo(self.config, require_operator=False)
        if not client:
            return 0.0
        try:
            ticker = client.tickerPrice({"market": market})
            if isinstance(ticker, dict):
                return float(ticker.get("price") or 0.0)
            if isinstance(ticker, list):
                for entry in ticker:
                    if entry.get("market") == market:
                        return float(entry.get("price") or 0.0)
        except Exception:
            return 0.0
        return 0.0

    def _is_paused(self, market: str) -> bool:
        if not self.event_state or not getattr(self.event_state, "enabled", False):
            return False
        try:
            return self.event_state.market_paused(market)
        except Exception as exc:
            log(f"[hodl_scheduler] Pauzestatus onbekend voor {market}: {exc}", level='warning')
            return False

    def _record_run(self, market: str, status: str) -> None:
        entries = self.state.setdefault("entries", {})
        entries[market] = {"last_run": time.time(), "status": status}
        self._save_state()

    # ------------------------------ cycle ---------------------------------
    def run_cycle(self) -> List[Dict[str, str]]:
        if not self.enabled:
            log("[hodl_scheduler] Scheduler not enabled", level='debug')
            return []
        executed: List[Dict[str, str]] = []
        log(f"[hodl_scheduler] Running cycle with {len(self.schedules)} schedules", level='info')
        for sched in self.schedules:
            entry_state = (self.state.get("entries", {}).get(sched.market) or {})
            last_run = float(entry_state.get("last_run") or 0)
            interval_secs = max(60, sched.interval_minutes * 60)
            time_since_last = time.time() - last_run
            log(f"[hodl_scheduler] {sched.market}: last_run={last_run:.0f}, interval={interval_secs}s, elapsed={time_since_last:.0f}s", level='info')
            if time_since_last < interval_secs:
                log(f"[hodl_scheduler] {sched.market}: skipping, need to wait {interval_secs - time_since_last:.0f}s more", level='info')
                continue
            if self._is_paused(sched.market):
                log(f"[hodl_scheduler] Markt {sched.market} gepauzeerd, entry overgeslagen", level='info')
                continue
            try:
                price = self._current_price(sched.market)
                if price <= 0:
                    raise RuntimeError("geen prijs beschikbaar")
                base_amount = sched.amount_eur / price
                if sched.dry_run:
                    log(
                        f"[hodl_scheduler] DRY-RUN koop {sched.market}: €{sched.amount_eur:.2f} ({base_amount:.6f} @ {price:.4f})",
                        level='info',
                    )
                    self._record_run(sched.market, "dry_run")
                else:
                    # Get operator_id from config
                    operator_id = self.config.get('OPERATOR_ID') or self.config.get('BITVAVO_OPERATOR_ID')
                    client = get_bitvavo(self.config, require_operator=True)
                    if not client:
                        raise RuntimeError("Bitvavo client niet beschikbaar")
                    
                    # Round amount to 8 decimals (Bitvavo requirement)
                    base_amount_rounded = round(base_amount, 8)
                    
                    # Build order params - placeOrder expects positional args: market, side, orderType, body
                    order_body = {'amount': str(base_amount_rounded)}
                    if operator_id:
                        order_body['operatorId'] = str(operator_id)
                    
                    resp = client.placeOrder(sched.market, 'buy', 'market', order_body)
                    if isinstance(resp, dict) and resp.get('error'):
                        raise RuntimeError(str(resp.get('error')))
                    log(
                        f"[hodl_scheduler] Koop geplaatst voor {sched.market}: €{sched.amount_eur:.2f} (order: {resp})",
                        level='info',
                    )
                    self._record_run(sched.market, "executed")
                executed.append({"market": sched.market, "status": "ok"})
            except Exception as exc:
                log(f"[hodl_scheduler] Entry mislukt voor {sched.market}: {exc}", level='error')
                self._record_run(sched.market, "error")
        return executed


__all__ = ["HodlScheduler", "HodlSchedule"]
