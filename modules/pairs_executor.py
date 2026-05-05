"""Execution layer for Golf 3 spot–spot hedges.

The executor receives entry/exit callbacks from ``PairsArbitrageEngine`` and is
responsible for translating statistical signals into two coordinated Bitvavo
orders (one per leg).  It purposely runs outside of the main trailing bot so it
never touches ``trade_log.json`` nor the global heartbeat counters.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from modules.bitvavo_client import get_bitvavo, place_market_order
from modules.json_compat import write_json_compat
from modules.logging_utils import log
from modules.pairs_arbitrage import PairDefinition


@dataclass
class OrderInstruction:
    market: str
    side: str  # "buy" or "sell"
    amount: float  # base units (Bitvavo expects qty, not EUR)
    eur_value: float  # helper for risk guards


class PairsExecutor:
    """Simple two-leg execution helper for spot–spot hedges."""

    def __init__(self, config: Dict) -> None:
        self.config = config or {}
        self.settings = (self.config.get("PAIRS_EXECUTOR") or {}).copy()
        self.enabled = bool(self.settings.get("enabled"))
        self.dry_run = bool(self.settings.get("dry_run", True))
        self.positions_path = Path(self.settings.get("positions_file", "data/pairs_positions.json"))
        self.log_path = Path(self.settings.get("log_file", "logs/pairs_executor.jsonl"))
        self.max_positions = max(1, int(self.settings.get("max_concurrent_positions", 1)))
        self.leg_notional_eur = float(self.settings.get("leg_notional_eur", 25.0) or 0.0)
        self.min_order_eur = float(self.settings.get("min_order_eur", self.config.get("MIN_ORDER_EUR", 5.0)))
        self.cooldown_seconds = max(0, int(self.settings.get("entry_cooldown_seconds", 300)))
        self.balance_refresh_seconds = max(5, int(self.settings.get("balance_refresh_seconds", 30)))
        self.min_eur_balance_reserve = max(0.0, float(self.settings.get("min_eur_balance_reserve", 0.0)))
        self.slippage_buffer_pct = max(0.0, float(self.settings.get("slippage_buffer_pct", 0.001)))

        self._positions: Dict[str, Dict[str, float]] = self._load_positions()
        self._last_entry_ts: float = 0.0
        self._balances: Dict[str, float] = {}
        self._last_balance_refresh: float = 0.0
        self._client = None

    # ------------------------------------------------------------------
    @property
    def active(self) -> bool:
        return self.enabled and self.leg_notional_eur > 0.0

    def __call__(self, pair: PairDefinition, action: str, price_long: float, price_short: float) -> bool:
        if not self.active:
            raise RuntimeError("PairsExecutor is niet actief (uit of geen notional).")
        if self.dry_run:
            return self._simulate_action(pair, action, price_long, price_short)
        if action.startswith("enter"):
            return self._enter_position(pair, action, price_long, price_short)
        if action == "exit":
            return self._exit_position(pair)
        raise RuntimeError(f"Onbekende pairs-actie: {action}")

    # ------------------------------------------------------------------
    def _load_positions(self) -> Dict[str, Dict[str, float]]:
        if not self.positions_path.exists():
            return {}
        try:
            payload = json.loads(self.positions_path.read_text(encoding="utf-8"))
            positions = payload.get("positions") if isinstance(payload, dict) else None
            return positions or {}
        except Exception:
            return {}

    def _persist_positions(self) -> None:
        try:
            self.positions_path.parent.mkdir(parents=True, exist_ok=True)
            write_json_compat(
                str(self.positions_path),
                {"ts": time.time(), "positions": self._positions},
                indent=2,
            )
        except Exception as exc:
            log(f"[pairs-exec] Kon positions file niet wegschrijven: {exc}", level="warning")

    def _append_log(self, record: Dict) -> None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _simulate_action(self, pair: PairDefinition, action: str, price_long: float, price_short: float) -> bool:
        now = time.time()
        sim_record = {
            "ts": now,
            "pair": pair.key,
            "action": action,
            "mode": "dry-run",
            "price_long": price_long,
            "price_short": price_short,
        }
        self._append_log(sim_record)
        if action.startswith("enter"):
            payload = {
                "direction": "long_spread" if action == "enter_long" else "short_spread",
                "entered_ts": now,
                "notional_eur": self._resolve_leg_notional(pair),
            }
            self._positions[pair.key] = payload
        elif action == "exit":
            self._positions.pop(pair.key, None)
        self._persist_positions()
        return True

    # ------------------------------------------------------------------
    def _enter_position(self, pair: PairDefinition, action: str, price_long: float, price_short: float) -> bool:
        if pair.key in self._positions:
            log(f"[pairs-exec] {pair.key} reeds open, sla nieuwe entry over.", level="warning")
            return False
        if len(self._positions) >= self.max_positions:
            log("[pairs-exec] Maximaal aantal hedges actief, entry overgeslagen.", level="warning")
            return False
        now = time.time()
        if now - self._last_entry_ts < self.cooldown_seconds:
            log("[pairs-exec] Entry cooldown actief, signaal genegeerd.", level="info")
            return False

        leg_notional = self._resolve_leg_notional(pair)
        if leg_notional < max(self.min_order_eur, 1e-6):
            raise RuntimeError("Leg notional te klein voor order plaatsing")

        qty_long = leg_notional / price_long if price_long else 0.0
        qty_short = leg_notional / price_short if price_short else 0.0
        if qty_long <= 0 or qty_short <= 0:
            raise RuntimeError("Kon hoeveelheden niet berekenen voor pair-entry")

        instructions = self._build_entry_instructions(action, pair, qty_long, qty_short, price_long, price_short)
        self._preflight_balances(instructions)
        self._execute_orders(instructions)

        self._positions[pair.key] = {
            "direction": "long_spread" if action == "enter_long" else "short_spread",
            "qty_long": qty_long,
            "qty_short": qty_short,
            "entry_price_long": price_long,
            "entry_price_short": price_short,
            "entered_ts": now,
            "notional_eur": leg_notional,
        }
        self._persist_positions()
        self._last_entry_ts = now
        self._append_log(
            {
                "ts": now,
                "pair": pair.key,
                "action": action,
                "qty_long": qty_long,
                "qty_short": qty_short,
                "notional": leg_notional,
            }
        )
        log(f"[pairs-exec] Entry uitgevoerd voor {pair.key} ({action})", level="info")
        return True

    def _exit_position(self, pair: PairDefinition) -> bool:
        record = self._positions.get(pair.key)
        if not record:
            log(f"[pairs-exec] Geen open positie voor {pair.key} bij exit-signaal", level="warning")
            return False
        direction = record.get("direction") or "long_spread"
        qty_long = float(record.get("qty_long") or 0.0)
        qty_short = float(record.get("qty_short") or 0.0)
        price_long = float(record.get("entry_price_long") or 0.0)
        price_short = float(record.get("entry_price_short") or 0.0)
        instructions = self._build_exit_instructions(direction, pair, qty_long, qty_short, price_long, price_short)
        self._preflight_balances(instructions)
        self._execute_orders(instructions)
        self._positions.pop(pair.key, None)
        self._persist_positions()
        now = time.time()
        self._append_log({"ts": now, "pair": pair.key, "action": "exit"})
        log(f"[pairs-exec] Exit uitgevoerd voor {pair.key}", level="info")
        return True

    # ------------------------------------------------------------------
    def _resolve_leg_notional(self, pair: PairDefinition) -> float:
        cap = float(pair.max_notional_eur or 0.0)
        return min(self.leg_notional_eur, cap) if cap > 0 else self.leg_notional_eur

    def _build_entry_instructions(
        self,
        action: str,
        pair: PairDefinition,
        qty_long: float,
        qty_short: float,
        price_long: float,
        price_short: float,
    ) -> List[OrderInstruction]:
        if action == "enter_long":
            return [
                OrderInstruction(pair.market_long, "buy", qty_long, qty_long * price_long),
                OrderInstruction(pair.market_short, "sell", qty_short, qty_short * price_short),
            ]
        if action == "enter_short":
            return [
                OrderInstruction(pair.market_long, "sell", qty_long, qty_long * price_long),
                OrderInstruction(pair.market_short, "buy", qty_short, qty_short * price_short),
            ]
        raise RuntimeError(f"Onbekende entry-actie: {action}")

    def _build_exit_instructions(
        self,
        direction: str,
        pair: PairDefinition,
        qty_long: float,
        qty_short: float,
        price_long: float,
        price_short: float,
    ) -> List[OrderInstruction]:
        if direction == "long_spread":
            return [
                OrderInstruction(pair.market_long, "sell", qty_long, qty_long * (price_long or 0.0)),
                OrderInstruction(pair.market_short, "buy", qty_short, qty_short * (price_short or 0.0)),
            ]
        return [
            OrderInstruction(pair.market_long, "buy", qty_long, qty_long * (price_long or 0.0)),
            OrderInstruction(pair.market_short, "sell", qty_short, qty_short * (price_short or 0.0)),
        ]

    # ------------------------------------------------------------------
    def _preflight_balances(self, instructions: List[OrderInstruction]) -> None:
        self._refresh_balances()
        eur_needed = 0.0
        sells: Dict[str, float] = {}
        for instr in instructions:
            eur_value = instr.eur_value or 0.0
            if instr.side == "buy":
                eur_needed += eur_value * (1 + self.slippage_buffer_pct)
            else:
                symbol = instr.market.split("-")[0].upper()
                sells[symbol] = sells.get(symbol, 0.0) + instr.amount
        # Check EUR availability
        eur_available = self._balances.get("EUR", 0.0)
        if eur_needed > 0 and (eur_available - eur_needed) < self.min_eur_balance_reserve:
            raise RuntimeError(
                f"Onvoldoende EUR saldo ({eur_available:.2f}) voor pairs-executor (benodigt {eur_needed:.2f})."
            )
        for symbol, qty in sells.items():
            available = self._balances.get(symbol, 0.0)
            if qty > available + 1e-8:
                raise RuntimeError(f"Onvoldoende {symbol} balans ({available:.6f}) voor verkoop van {qty:.6f}")
        # Basic min order check
        for instr in instructions:
            if instr.eur_value and instr.eur_value < self.min_order_eur:
                raise RuntimeError(
                    f"Orderwaarde {instr.eur_value:.2f} EUR voor {instr.market} is lager dan minimum {self.min_order_eur:.2f}"
                )

    def _refresh_balances(self) -> None:
        now = time.time()
        if now - self._last_balance_refresh < self.balance_refresh_seconds:
            return
        client = self._get_client()
        try:
            payload = client.balance({}) or []
        except Exception as exc:
            raise RuntimeError(f"Balances ophalen mislukt: {exc}")
        balances: Dict[str, float] = {}
        for entry in payload:
            symbol = str(entry.get("symbol") or "").upper()
            if not symbol:
                continue
            try:
                available = float(entry.get("available") or entry.get("balance") or 0.0)
            except Exception:
                available = 0.0
            balances[symbol] = available
        self._balances = balances
        self._last_balance_refresh = now

    def _execute_orders(self, instructions: List[OrderInstruction]) -> None:
        completed: List[OrderInstruction] = []
        for instr in instructions:
            if instr.amount <= 0:
                continue
            resp = place_market_order(instr.market, instr.amount, side=instr.side, bv=self._get_client())
            if isinstance(resp, dict) and resp.get("error"):
                raise RuntimeError(resp.get("error"))
            completed.append(instr)
        # Successful execution, force immediate balance refresh to reflect fills
        self._last_balance_refresh = 0.0
        self._refresh_balances()

    def _get_client(self):
        if self._client is None:
            self._client = get_bitvavo(self.config)
        if self._client is None:
            raise RuntimeError("Bitvavo client niet geconfigureerd voor pairs-executor")
        return self._client


__all__ = ["PairsExecutor"]
