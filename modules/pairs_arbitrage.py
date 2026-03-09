"""Spot–spot statistical pairs-arbitrage scaffolding.

This module keeps the implementation intentionally conservative: it calculates
rolling spreads and generates entry/exit signals but does not place orders unless
callers explicitly plug in an execution callback.  The goal is to pilot Golf 3
hedge ideas without touching the main trading loop yet.
"""
from __future__ import annotations

import json
import math
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from modules.logging_utils import log
from modules.bitvavo_client import get_bitvavo

# Types
PriceFetcher = Callable[[str], Optional[float]]
SignalExecutor = Callable[["PairDefinition", str, float, float], None]


@dataclass
class PairDefinition:
    """Configuration for a market pair."""

    market_long: str
    market_short: str
    hedge_ratio: float = 1.0
    z_entry: float = 2.0
    z_exit: float = 0.5
    max_notional_eur: float = 50.0
    dry_run: bool = True
    enabled: bool = True

    @property
    def key(self) -> str:
        return f"{self.market_long}->{self.market_short}"


@dataclass
class PairState:
    """Runtime statistics written to disk and optionally to dashboards."""

    last_spread: Optional[float] = None
    last_zscore: Optional[float] = None
    last_action: Optional[str] = None
    last_update_ts: Optional[float] = None
    history_points: int = 0
    position_open: bool = False


class RollingSpread:
    """Keeps the rolling mean/std for spreads without storing large arrays."""

    def __init__(self, window: int) -> None:
        self.window = max(2, int(window))
        self.values: deque[float] = deque(maxlen=self.window)

    def push(self, value: float) -> Optional[float]:
        self.values.append(value)
        if len(self.values) < 2:
            return None
        mean = statistics.fmean(self.values)
        stdev = statistics.pstdev(self.values)
        if stdev == 0:
            return 0.0
        return (value - mean) / stdev

    @property
    def count(self) -> int:
        return len(self.values)


class PairsArbitrageEngine:
    """Coordinates pair monitoring, signal generation, and state persistence."""

    def __init__(
        self,
        config: Dict,
        price_fetcher: Optional[PriceFetcher] = None,
        signal_executor: Optional[SignalExecutor] = None,
    ) -> None:
        self.config = config or {}
        self.settings = (self.config.get("PAIRS_ARBITRAGE") or {}).copy()
        self.enabled = bool(self.settings.get("enabled"))
        self.dry_run = bool(self.settings.get("dry_run", True))
        self.spread_window = int(self.settings.get("spread_window", 180))
        self.min_history = int(self.settings.get("min_history_points", 60))
        self.state_path = Path(self.settings.get("state_file", "data/pairs_state.json"))
        self.metrics_path = Path(self.settings.get("metrics_file", "logs/pairs_arbitrage.jsonl"))
        self.heartbeat_path = Path(self.settings.get("heartbeat_file", "data/pairs_heartbeat.json"))
        self.config_path = Path(self.settings.get("config_file", "config/pairs_config.json"))
        self.max_pairs = int(self.settings.get("max_parallel_pairs", 2))
        self.price_fetcher = price_fetcher or self._default_price_fetcher
        self.signal_executor = signal_executor
        self.pairs = self._load_pairs()
        self.trackers: Dict[str, RollingSpread] = {
            p.key: RollingSpread(self.spread_window) for p in self.pairs
        }
        self.states: Dict[str, PairState] = {p.key: PairState() for p in self.pairs}

    # ------------------------------------------------------------------
    def _load_pairs(self) -> List[PairDefinition]:
        if not self.config_path.exists():
            log(f"[pairs] Geen pair-config gevonden op {self.config_path}; gebruik lege lijst", level="warning")
            return []
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception as exc:
            log(f"[pairs] Kon pair-config niet lezen: {exc}", level="error")
            return []
        pairs: List[PairDefinition] = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            try:
                pair = PairDefinition(
                    market_long=str(entry["market_long"]).upper(),
                    market_short=str(entry["market_short"]).upper(),
                    hedge_ratio=float(entry.get("hedge_ratio", self.settings.get("default_hedge_ratio", 1.0))),
                    z_entry=float(entry.get("z_entry", self.settings.get("default_z_entry", 2.0))),
                    z_exit=float(entry.get("z_exit", self.settings.get("default_z_exit", 0.5))),
                    max_notional_eur=float(entry.get("max_notional_eur", self.settings.get("default_notional_cap_eur", 50.0))),
                    dry_run=bool(entry.get("dry_run", True)),
                    enabled=bool(entry.get("enabled", True)),
                )
            except Exception as exc:
                log(f"[pairs] Ongeldige pair config {entry}: {exc}", level="warning")
                continue
            if pair.enabled:
                pairs.append(pair)
        return pairs

    def _default_price_fetcher(self, market: str) -> Optional[float]:
        try:
            client = get_bitvavo()
            book = client.tickerPrice({"market": market})
            price = book.get("price") if isinstance(book, dict) else None
            return float(price) if price is not None else None
        except Exception as exc:
            log(f"[pairs] Kon prijs niet ophalen voor {market}: {exc}", level="warning")
            return None

    # ------------------------------------------------------------------
    def _calc_spread(self, pair: PairDefinition, price_long: float, price_short: float) -> float:
        # log spread is more stable across magnitudes
        return math.log(price_long) - pair.hedge_ratio * math.log(price_short)

    def _record_metric(self, pair: PairDefinition, state: PairState) -> None:
        try:
            self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
            with self.metrics_path.open("a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        {
                            "ts": time.time(),
                            "pair": pair.key,
                            "spread": state.last_spread,
                            "zscore": state.last_zscore,
                            "action": state.last_action,
                            "position_open": state.position_open,
                        }
                    )
                    + "\n"
                )
        except Exception:
            pass

    def _persist_state(self) -> None:
        try:
            payload = {
                "ts": time.time(),
                "pairs": {
                    key: state.__dict__
                    for key, state in self.states.items()
                },
            }
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:
            log(f"[pairs] Kon state niet wegschrijven: {exc}", level="warning")
    
    def _update_heartbeat(self) -> None:
        try:
            summary = {
                "ts": time.time(),
                "enabled": self.enabled,
                "dry_run": self.dry_run,
                "pair_count": len(self.pairs),
                "active_pairs": {
                    key: {
                        "zscore": state.last_zscore,
                        "spread": state.last_spread,
                        "position_open": state.position_open,
                        "history_points": state.history_points,
                        "last_action": state.last_action,
                        "updated": state.last_update_ts,
                    }
                    for key, state in self.states.items()
                },
            }
            self.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
            self.heartbeat_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        except Exception as exc:
            log(f"[pairs] Kon heartbeat niet bijwerken: {exc}", level="warning")

    # ------------------------------------------------------------------
    def tick(self) -> None:
        if not self.enabled:
            return
        active_pairs = self.pairs[: self.max_pairs]
        for pair in active_pairs:
            price_long = self.price_fetcher(pair.market_long)
            price_short = self.price_fetcher(pair.market_short)
            if price_long is None or price_short is None:
                continue
            spread = self._calc_spread(pair, price_long, price_short)
            tracker = self.trackers[pair.key]
            zscore = tracker.push(spread)
            state = self.states[pair.key]
            state.last_spread = spread
            state.last_zscore = zscore
            state.last_update_ts = time.time()
            state.history_points = tracker.count
            action = self._evaluate(pair, state)
            state.last_action = action
            if action and tracker.count >= self.min_history:
                self._handle_signal(pair, action, price_long, price_short, state)
            self._record_metric(pair, state)
        self._persist_state()
        self._update_heartbeat()

    def _evaluate(self, pair: PairDefinition, state: PairState) -> Optional[str]:
        if state.last_zscore is None:
            return None
        if not state.position_open and abs(state.last_zscore) >= pair.z_entry:
            return "enter_long" if state.last_zscore < 0 else "enter_short"
        if state.position_open and abs(state.last_zscore) <= pair.z_exit:
            return "exit"
        return None

    def _handle_signal(
        self,
        pair: PairDefinition,
        action: str,
        price_long: float,
        price_short: float,
        state: PairState,
    ) -> bool:
        dry_run = self.dry_run or pair.dry_run or self.signal_executor is None
        z_fmt = f"{state.last_zscore:.2f}" if state.last_zscore is not None else "nan"
        spread_fmt = f"{state.last_spread:.6f}" if state.last_spread is not None else "nan"
        log(
            f"[pairs] {pair.key}: action={action} z={z_fmt} spread={spread_fmt} dry_run={dry_run}",
            level="info",
        )
        if dry_run:
            if action.startswith("enter"):
                state.position_open = True
            elif action == "exit":
                state.position_open = False
            return True
        try:
            result = self.signal_executor(pair, action, price_long, price_short)
            success = result is not False
        except Exception as exc:
            log(f"[pairs] Signaal kon niet uitgevoerd worden voor {pair.key}: {exc}", level="error")
            success = False
        if success:
            if action == "exit":
                state.position_open = False
            elif action.startswith("enter"):
                state.position_open = True
        return success

    # ------------------------------------------------------------------
    def run_forever(self) -> None:
        interval = max(5, int(self.settings.get("poll_interval_seconds", 30)))
        while True:
            self.tick()
            time.sleep(interval)


def load_pairs_config(path: str | Path) -> List[PairDefinition]:
    """Helper for unit tests or other modules that need the parsed definitions."""
    engine = PairsArbitrageEngine(config={"PAIRS_ARBITRAGE": {"enabled": True, "config_file": str(path)}})
    return engine.pairs
