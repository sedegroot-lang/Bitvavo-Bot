"""Portfolio diversification helpers for Golf 2 slow-loop workflows."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

from modules.json_compat import write_json_compat


@dataclass
class Exposure:
    market: str
    eur: float
    sector: str
    weight_pct: float


@dataclass
class DiversificationStatus:
    total_value_eur: float
    exposures: List[Exposure] = field(default_factory=list)
    breaches: List[dict] = field(default_factory=list)
    timestamp: float = field(default_factory=lambda: time.time())

    def to_dict(self) -> Dict:
        return {
            "ts": self.timestamp,
            "total_value_eur": self.total_value_eur,
            "exposures": [
                {
                    "market": exp.market,
                    "eur": exp.eur,
                    "sector": exp.sector,
                    "weight_pct": exp.weight_pct,
                }
                for exp in self.exposures
            ],
            "breaches": self.breaches,
        }


class DiversificationRules:
    """Encapsulate diversification thresholds and evaluation helpers."""

    def __init__(self, config: Dict | None = None) -> None:
        cfg = config or {}
        self.rules = cfg.get("DIVERSIFICATION_RULES", {})
        self.account_file = Path(self.rules.get("account_overview_file", "data/account_overview.json"))
        self.max_asset_pct = float(self.rules.get("max_asset_pct", 0.4))
        self.max_sector_pct = float(self.rules.get("max_sector_pct", 0.6))
        self.rebalance_threshold = float(self.rules.get("rebalance_threshold_pct", 0.05))
        self.auto_rebalance = bool(self.rules.get("auto_rebalance", False))
        self.sector_map = {
            sym.upper(): sector for sym, sector in (self.rules.get("sector_map") or {}).items() if isinstance(sym, str)
        }
        self.status_path = Path("data/diversification_status.json")

    # ---------------------------- core helpers ----------------------------
    def _symbol_from_market(self, market: str) -> str:
        try:
            return (market or "").split("-")[0].upper()
        except Exception:
            return market.upper() if isinstance(market, str) else ""

    def _sector_for_market(self, market: str) -> str:
        sym = self._symbol_from_market(market)
        return self.sector_map.get(sym, "unknown")

    def _load_account_value(self) -> float:
        if not self.account_file.exists():
            return 0.0
        try:
            doc = json.loads(self.account_file.read_text(encoding="utf-8"))
            return float(doc.get("total_account_value_eur") or 0.0)
        except Exception:
            return 0.0

    def _calc_total_value(self, exposures: Dict[str, float], fallback: float) -> float:
        total = sum(max(v, 0.0) for v in exposures.values())
        if total <= 0 and fallback > 0:
            return fallback
        if fallback > 0 and total < fallback * 0.5:
            # When snapshot misses EUR cash we still prefer account value
            return fallback
        return total

    def _summarize_exposures(self, trades_snapshot: Dict) -> Tuple[Dict[str, float], List[Exposure], float]:
        open_trades = trades_snapshot.get("open") or {}
        per_market: Dict[str, float] = {}
        for market, trade in open_trades.items():
            try:
                amount = float(trade.get("amount") or 0.0)
                buy_price = float(trade.get("buy_price") or trade.get("average_price") or 0.0)
                invested = max(amount * buy_price, 0.0)
            except Exception:
                invested = 0.0
            per_market[market] = per_market.get(market, 0.0) + invested
        fallback = self._load_account_value()
        total_value = self._calc_total_value(per_market, fallback)
        exposures: List[Exposure] = []
        for market, eur in per_market.items():
            if total_value <= 0:
                weight_pct = 0.0
            else:
                weight_pct = eur / total_value
            exposures.append(
                Exposure(market=market, eur=eur, sector=self._sector_for_market(market), weight_pct=weight_pct)
            )
        exposures.sort(key=lambda e: e.weight_pct, reverse=True)
        return per_market, exposures, total_value

    def evaluate(self, trades_snapshot: Dict) -> DiversificationStatus:
        per_market, exposures, total_value = self._summarize_exposures(trades_snapshot)
        breaches: List[dict] = []
        # Asset-level breaches
        for exp in exposures:
            if self.max_asset_pct > 0 and exp.weight_pct > self.max_asset_pct + self.rebalance_threshold:
                breaches.append(
                    {
                        "type": "asset",
                        "market": exp.market,
                        "weight_pct": exp.weight_pct,
                        "limit": self.max_asset_pct,
                    }
                )
        # Sector-level breaches
        sector_totals: Dict[str, float] = {}
        for exp in exposures:
            sector_totals[exp.sector] = sector_totals.get(exp.sector, 0.0) + exp.weight_pct
        for sector, pct in sector_totals.items():
            if self.max_sector_pct > 0 and pct > self.max_sector_pct + self.rebalance_threshold:
                breaches.append(
                    {
                        "type": "sector",
                        "sector": sector,
                        "weight_pct": pct,
                        "limit": self.max_sector_pct,
                    }
                )
        status = DiversificationStatus(total_value_eur=total_value, exposures=exposures, breaches=breaches)
        try:
            write_json_compat(str(self.status_path), status.to_dict(), indent=2)
        except Exception:
            pass
        return status

    # ---------------------------- public API -----------------------------
    def can_allocate(self, trades_snapshot: Dict, market: str, amount_eur: float) -> Tuple[bool, str]:
        status = self.evaluate(trades_snapshot)
        total = status.total_value_eur if status.total_value_eur > 0 else amount_eur
        projected_weight = 0.0
        if total > 0:
            # include proposed allocation
            existing = next((e.weight_pct for e in status.exposures if e.market == market), 0.0)
            projected_weight = existing + (amount_eur / total)
        if self.max_asset_pct > 0 and projected_weight > self.max_asset_pct + self.rebalance_threshold:
            return False, f"Asset cap voor {market} overschreden ({projected_weight:.1%} > {self.max_asset_pct:.0%})"

        # Check sector level
        sector = self._sector_for_market(market)
        sector_weight = sum(e.weight_pct for e in status.exposures if e.sector == sector)
        if total > 0:
            sector_weight += amount_eur / total
        if self.max_sector_pct > 0 and sector_weight > self.max_sector_pct + self.rebalance_threshold:
            return False, f"Sector cap {sector} overschreden ({sector_weight:.1%} > {self.max_sector_pct:.0%})"
        if status.breaches and self.auto_rebalance:
            return False, "Diversificatiebreuk actief, eerst rebalance uitvoeren"
        return True, "OK"

    def rebalance_targets(self, trades_snapshot: Dict) -> List[dict]:
        status = self.evaluate(trades_snapshot)
        if not status.breaches:
            return []
        targets: List[dict] = []
        total = status.total_value_eur or 0.0
        if total <= 0:
            return targets
        for breach in status.breaches:
            if breach.get("type") == "asset":
                market = breach.get("market")
                over_pct = breach.get("weight_pct", 0.0) - self.max_asset_pct
                if over_pct <= 0:
                    continue
                targets.append(
                    {
                        "action": "reduce",
                        "market": market,
                        "reduce_eur": max(0.0, over_pct * total),
                        "reason": "asset_limit",
                    }
                )
            elif breach.get("type") == "sector":
                sector = breach.get("sector")
                over_pct = breach.get("weight_pct", 0.0) - self.max_sector_pct
                if over_pct <= 0:
                    continue
                affected = [e for e in status.exposures if e.sector == sector]
                if not affected:
                    continue
                per_market = over_pct * total / len(affected)
                for exp in affected:
                    targets.append(
                        {
                            "action": "reduce",
                            "market": exp.market,
                            "reduce_eur": max(0.0, per_market),
                            "reason": f"sector_limit::{sector}",
                        }
                    )
        return targets


__all__ = ["DiversificationRules", "DiversificationStatus", "Exposure"]
