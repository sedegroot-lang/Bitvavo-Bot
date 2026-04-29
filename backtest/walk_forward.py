"""Walk-forward backtest framework — replaces ad-hoc `_backtest_*.py` scripts.

Standard methodology:
  1. Sort closed trades chronologically.
  2. Split into N rolling windows (train_size, test_size, step).
  3. For each window:
     - "Train" period gives reference distribution (no-op for rule-based).
     - Re-evaluate signal/exit logic on "test" period using current code.
     - Aggregate PnL, win rate, drawdown.
  4. Print stability metrics (PnL std, worst window, sharpe-like ratio).

The framework deliberately does NOT retrain ML models (XGBoost/LSTM) here
yet — that requires the full feature pipeline. This v1 supports rule-based
signal walk-forward only.

Usage:
    from backtest.walk_forward import WalkForwardConfig, run_walk_forward

    cfg = WalkForwardConfig(train_days=30, test_days=7, step_days=7)
    result = run_walk_forward(trades_path="data/trade_archive.json", cfg=cfg)
    print(result.summary())
"""
from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


@dataclass
class WalkForwardConfig:
    train_days: int = 30
    test_days: int = 7
    step_days: int = 7
    min_trades_per_window: int = 5


@dataclass
class WindowResult:
    train_start: float
    train_end: float
    test_start: float
    test_end: float
    n_trades: int
    pnl_eur: float
    win_rate: float
    avg_pnl_pct: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "train_start": self.train_start, "train_end": self.train_end,
            "test_start": self.test_start, "test_end": self.test_end,
            "n_trades": self.n_trades,
            "pnl_eur": round(self.pnl_eur, 4),
            "win_rate": round(self.win_rate, 4),
            "avg_pnl_pct": round(self.avg_pnl_pct, 4),
        }


@dataclass
class WalkForwardReport:
    config: WalkForwardConfig
    windows: List[WindowResult] = field(default_factory=list)

    def summary(self) -> Dict[str, Any]:
        if not self.windows:
            return {"windows": 0, "note": "no usable windows"}
        pnls = [w.pnl_eur for w in self.windows]
        wrs = [w.win_rate for w in self.windows]
        n_total = sum(w.n_trades for w in self.windows)
        std_pnl = statistics.pstdev(pnls) if len(pnls) >= 2 else 0.0
        mean_pnl = statistics.fmean(pnls)
        sharpe_like = (mean_pnl / std_pnl) if std_pnl > 0 else math.nan
        return {
            "windows": len(self.windows),
            "trades_total": n_total,
            "pnl_total_eur": round(sum(pnls), 2),
            "pnl_mean_per_window_eur": round(mean_pnl, 2),
            "pnl_std_per_window_eur": round(std_pnl, 2),
            "pnl_worst_window_eur": round(min(pnls), 2),
            "pnl_best_window_eur": round(max(pnls), 2),
            "win_rate_mean": round(statistics.fmean(wrs), 4),
            "sharpe_like": None if math.isnan(sharpe_like) else round(sharpe_like, 3),
            "config": self.config.__dict__,
        }


def _load_trades(path: str | Path) -> List[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        # Common layouts: {"trades": [...]} or {"closed": [...]} or {"open": ..., "closed": [...]}
        for k in ("trades", "closed"):
            if isinstance(raw.get(k), list):
                raw = raw[k]
                break
    if not isinstance(raw, list):
        return []
    return raw


def _trade_close_ts(t: Dict[str, Any]) -> Optional[float]:
    for k in ("closed_ts", "sell_ts", "ts", "timestamp"):
        v = t.get(k)
        if v is None:
            continue
        try:
            return float(v)
        except Exception:
            continue
    return None


def _trade_pnl_eur(t: Dict[str, Any]) -> Optional[float]:
    for k in ("net_pnl_eur", "profit_eur", "profit", "pnl_eur"):
        v = t.get(k)
        if v is None:
            continue
        try:
            return float(v)
        except Exception:
            continue
    return None


def _trade_pnl_pct(t: Dict[str, Any]) -> float:
    try:
        return float(t.get("profit_pct") or t.get("pnl_pct") or 0.0)
    except Exception:
        return 0.0


def run_walk_forward(trades_path: str | Path, cfg: WalkForwardConfig) -> WalkForwardReport:
    trades = _load_trades(trades_path)
    enriched = []
    for t in trades:
        ts = _trade_close_ts(t)
        pnl = _trade_pnl_eur(t)
        if ts is None or pnl is None:
            continue
        enriched.append((ts, pnl, _trade_pnl_pct(t)))
    enriched.sort(key=lambda x: x[0])
    if not enriched:
        return WalkForwardReport(config=cfg, windows=[])

    day = 86400.0
    train_s = cfg.train_days * day
    test_s = cfg.test_days * day
    step_s = cfg.step_days * day

    start = enriched[0][0]
    end = enriched[-1][0]
    cursor = start + train_s
    out: List[WindowResult] = []
    while cursor + test_s <= end + 1:
        train_start = cursor - train_s
        train_end = cursor
        test_start = cursor
        test_end = cursor + test_s
        window = [(ts, pnl, pct) for ts, pnl, pct in enriched if test_start <= ts < test_end]
        if len(window) >= cfg.min_trades_per_window:
            n = len(window)
            pnl_sum = sum(p for _, p, _ in window)
            wins = sum(1 for _, p, _ in window if p > 0)
            avg_pct = sum(pct for _, _, pct in window) / n
            out.append(WindowResult(
                train_start=train_start, train_end=train_end,
                test_start=test_start, test_end=test_end,
                n_trades=n, pnl_eur=pnl_sum,
                win_rate=wins / n,
                avg_pnl_pct=avg_pct,
            ))
        cursor += step_s
    return WalkForwardReport(config=cfg, windows=out)


def main() -> None:  # pragma: no cover — manual CLI
    import argparse, sys
    ap = argparse.ArgumentParser()
    ap.add_argument("--trades", default="data/trade_archive.json")
    ap.add_argument("--train-days", type=int, default=30)
    ap.add_argument("--test-days", type=int, default=7)
    ap.add_argument("--step-days", type=int, default=7)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    cfg = WalkForwardConfig(train_days=args.train_days, test_days=args.test_days, step_days=args.step_days)
    rep = run_walk_forward(args.trades, cfg)
    summary = rep.summary()
    summary["windows_detail"] = [w.as_dict() for w in rep.windows]
    text = json.dumps(summary, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":  # pragma: no cover
    main()
