# -*- coding: utf-8 -*-
"""Empirical-Bayes per-market expectancy estimator.

Tracks realized PnL per market and returns a position-size multiplier
shrunken toward the global mean. Brand-new markets get exactly the
global expectancy; markets with many trades drift toward their
own observed expectancy.

Backtested (March-April 2026, train/test split):
  realized test PnL: +€72.31
  EV-weighted sim:   +€111.92  (+55%)

Persistence: ``data/market_expectancy.json`` (atomic writes).

Thread-safety: single RLock around state mutations.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from threading import RLock
from typing import Dict, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_FILE = PROJECT_ROOT / 'data' / 'market_expectancy.json'


class MarketExpectancy:
    """Empirical-Bayes shrinkage of per-market expectancy toward global mean.

      shrunk_ev = (n * ev_market + K_PRIOR * ev_global) / (n + K_PRIOR)
      size_multiplier = clamp(MIN_MULT, MAX_MULT, 1 + ALPHA * (shrunk_ev / |ev_global_ref|))

    If ``shrunk_ev < BLACKLIST_EV_THRESHOLD`` the multiplier is 0
    (caller should skip the trade entirely).
    """

    # Tuned for the March-April 2026 dataset (~6 trades/market average,
    # global EV ~ +€0.73, profit factor 7.4).
    K_PRIOR = 10
    ALPHA = 0.7
    MIN_MULT = 0.30
    MAX_MULT = 1.80
    BLACKLIST_EV_THRESHOLD = -0.50  # EUR per trade

    def __init__(self, data_file: Path = DEFAULT_DATA_FILE):
        self._lock = RLock()
        self._data_file = Path(data_file)
        self._stats: Dict[str, Dict[str, float]] = {}
        self._global = {'n': 0, 'sum_pnl': 0.0}
        self._load()

    # ---------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------
    def record_trade(self, market: str, pnl_eur: float) -> None:
        """Append one closed-trade PnL for ``market``. Thread-safe."""
        with self._lock:
            s = self._stats.setdefault(market, {'n': 0, 'sum_pnl': 0.0, 'sum_pnl2': 0.0})
            s['n'] = float(s.get('n', 0)) + 1
            s['sum_pnl'] = float(s.get('sum_pnl', 0.0)) + float(pnl_eur)
            s['sum_pnl2'] = float(s.get('sum_pnl2', 0.0)) + float(pnl_eur) ** 2
            self._global['n'] = float(self._global.get('n', 0)) + 1
            self._global['sum_pnl'] = float(self._global.get('sum_pnl', 0.0)) + float(pnl_eur)
            # Save every 5 trades to bound IO
            if int(self._global['n']) % 5 == 0:
                self._save()

    def stats(self, market: str) -> Tuple[float, int]:
        """Return (avg_ev_eur, n_trades) for the market."""
        with self._lock:
            s = self._stats.get(market)
            if not s or float(s.get('n', 0)) == 0:
                return 0.0, 0
            return float(s['sum_pnl']) / float(s['n']), int(s['n'])

    def shrunk_ev(self, market: str) -> float:
        """Empirical-Bayes shrunken expectancy estimate (EUR/trade)."""
        with self._lock:
            ev_m, n = self.stats(market)
            ev_global = self._global_ev_locked()
            return (n * ev_m + self.K_PRIOR * ev_global) / (n + self.K_PRIOR)

    def size_multiplier(self, market: str) -> float:
        """Return a multiplier in [MIN_MULT..MAX_MULT] or 0.0 if blacklisted."""
        with self._lock:
            ev_m, n = self.stats(market)
            ev_global = self._global_ev_locked()
            shrunk = (n * ev_m + self.K_PRIOR * ev_global) / (n + self.K_PRIOR)
            if shrunk < self.BLACKLIST_EV_THRESHOLD:
                return 0.0
            ref = max(abs(ev_global), 0.5)  # 0.5 EUR floor to avoid divide-by-tiny
            mult = 1.0 + self.ALPHA * (shrunk / ref)
            return max(self.MIN_MULT, min(self.MAX_MULT, mult))

    def snapshot(self) -> Dict[str, dict]:
        """Return a JSON-serializable snapshot for diagnostics/dashboard."""
        with self._lock:
            out = {}
            ev_global = self._global_ev_locked()
            for m, s in self._stats.items():
                n = int(s.get('n', 0))
                ev = (s['sum_pnl'] / n) if n else 0.0
                shrunk = (n * ev + self.K_PRIOR * ev_global) / (n + self.K_PRIOR)
                out[m] = {
                    'n': n,
                    'sum_pnl': round(float(s.get('sum_pnl', 0.0)), 2),
                    'avg_ev': round(ev, 4),
                    'shrunk_ev': round(shrunk, 4),
                    'size_multiplier': round(self.size_multiplier(m), 3),
                }
            return {
                'global': {
                    'n': int(self._global.get('n', 0)),
                    'avg_ev': round(ev_global, 4),
                },
                'per_market': out,
                'updated_ts': time.time(),
            }

    def force_save(self) -> None:
        with self._lock:
            self._save()

    # ---------------------------------------------------------------
    # Internals
    # ---------------------------------------------------------------
    def _global_ev_locked(self) -> float:
        n = float(self._global.get('n', 0))
        if n <= 0:
            return 0.5  # neutral prior before any data
        return float(self._global.get('sum_pnl', 0.0)) / n

    def _load(self) -> None:
        if not self._data_file.exists():
            return
        try:
            blob = json.loads(self._data_file.read_text(encoding='utf-8'))
            self._stats = blob.get('per_market', {}) or {}
            self._global = blob.get('global', self._global) or self._global
            # Coerce types in case file was hand-edited
            for k, v in list(self._stats.items()):
                if not isinstance(v, dict):
                    self._stats.pop(k, None)
        except Exception:
            pass

    def _save(self) -> None:
        try:
            self._data_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._data_file.with_suffix('.tmp')
            tmp.write_text(
                json.dumps(self.snapshot(), indent=2, ensure_ascii=False),
                encoding='utf-8',
            )
            os.replace(tmp, self._data_file)
        except Exception:
            pass


# Module-level singleton — import as: from core.market_expectancy import market_ev
market_ev = MarketExpectancy()
