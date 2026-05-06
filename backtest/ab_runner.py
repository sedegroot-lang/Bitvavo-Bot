"""A/B comparison harness for replay_engine.

Runs the same candle data through two ``ReplayConfig`` variants ("base" and
"challenger") and prints / writes a side-by-side report.

Usage::

    from backtest.ab_runner import run_ab
    diff = run_ab(market="BTC-EUR", candles=candles,
                  base=ReplayConfig(), challenger=ReplayConfig(min_score=15.0))
    print(diff.summary())
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Sequence

from backtest.replay_engine import ReplayConfig, ReplayResult, run_replay


@dataclass
class ABResult:
    market: str
    base: ReplayResult
    challenger: ReplayResult

    @property
    def pnl_delta(self) -> float:
        return self.challenger.pnl_eur - self.base.pnl_eur

    @property
    def trades_delta(self) -> int:
        return self.challenger.n_trades - self.base.n_trades

    @property
    def win_rate_delta(self) -> float:
        return self.challenger.win_rate - self.base.win_rate

    def summary(self) -> str:
        b, c = self.base, self.challenger
        return "\n".join([
            f"A/B replay — {self.market}",
            f"                       BASE         CHALLENGER   DELTA",
            f"  Trades            {b.n_trades:>6d}       {c.n_trades:>6d}       {self.trades_delta:+d}",
            f"  PnL (EUR)         €{b.pnl_eur:>+7.2f}     €{c.pnl_eur:>+7.2f}     €{self.pnl_delta:+.2f}",
            f"  Win rate          {b.win_rate*100:>6.1f}%      {c.win_rate*100:>6.1f}%      {self.win_rate_delta*100:+.1f}pp",
            f"  Avg PnL/trade     €{b.avg_pnl_eur:>+7.2f}     €{c.avg_pnl_eur:>+7.2f}     €{c.avg_pnl_eur - b.avg_pnl_eur:+.2f}",
            f"  Max drawdown      €{b.max_drawdown_eur:>7.2f}     €{c.max_drawdown_eur:>7.2f}     €{c.max_drawdown_eur - b.max_drawdown_eur:+.2f}",
            f"  Sharpe-like       {b.sharpe_like:>7.2f}      {c.sharpe_like:>7.2f}      {c.sharpe_like - b.sharpe_like:+.2f}",
        ])

    def as_dict(self) -> Dict[str, Any]:
        return {
            "market": self.market,
            "base": self.base.as_dict(),
            "challenger": self.challenger.as_dict(),
            "delta": {
                "pnl_eur": round(self.pnl_delta, 2),
                "trades": self.trades_delta,
                "win_rate": round(self.win_rate_delta, 4),
            },
        }


def run_ab(
    market: str,
    candles: Sequence[Sequence[Any]],
    base: ReplayConfig,
    challenger: ReplayConfig,
) -> ABResult:
    base_res = run_replay(market, candles, base)
    chal_res = run_replay(market, candles, challenger)
    return ABResult(market=market, base=base_res, challenger=chal_res)


def save_ab_report(result: ABResult, path: Path | str) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(result.as_dict(), f, ensure_ascii=False, indent=2)
    tmp.replace(p)
    return p
