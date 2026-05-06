"""Candle replay backtest engine.

Replays historical 1-minute candles through the live signal pack and simulates
the trailing-stop trade lifecycle deterministically. The goal is reproducible
offline evaluation of config / signal changes BEFORE shipping them.

Scope of v1 (intentionally minimal — see roadmap for follow-ups):
- Single-market replay (use ``ab_runner`` for cross-config comparison).
- Score gate uses ``MIN_SCORE_TO_BUY`` from the supplied config.
- One open position per market at a time (no DCA, no partial TP).
- Trailing stop: simple percentage-of-high-water-mark.
- Fees modelled as percent of notional (default Bitvavo taker 0.25%).

Data format
-----------
Candles are Bitvavo-style sequences::

    [timestamp_ms, open, high, low, close, volume]

You can feed them from anywhere: ``scripts/fetch_historical_candles.py``,
in-memory test fixtures, or a JSON file written by the live bot.

Usage::

    from backtest.replay_engine import ReplayConfig, run_replay
    result = run_replay(market="BTC-EUR", candles=candles, cfg=ReplayConfig())
    print(result.summary())
"""
from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ---------- Data structures ----------

@dataclass
class ReplayConfig:
    """Tunable knobs for one replay run."""

    min_score: float = 18.0
    base_invest_eur: float = 100.0
    fee_pct: float = 0.0025                # 0.25%
    trailing_activation_pct: float = 0.012  # +1.2% before trailing arms
    trailing_pct: float = 0.008             # 0.8% below high-water mark
    stop_loss_pct: float = 0.05             # hard stop at -5%
    warmup_candles: int = 60                # need this many bars before scoring
    max_hold_bars: int = 240                # 4h cap
    extra_config: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class SimTrade:
    market: str
    entry_ts: float
    entry_price: float
    amount: float
    invested_eur: float
    score: float
    high_water: float
    activated: bool = False
    exit_ts: float = 0.0
    exit_price: float = 0.0
    pnl_eur: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""


@dataclass
class ReplayResult:
    market: str
    n_candles: int
    n_trades: int
    pnl_eur: float
    pnl_pct: float
    win_rate: float
    avg_pnl_eur: float
    max_drawdown_eur: float
    sharpe_like: float
    equity_curve: List[Dict[str, float]]
    trades: List[SimTrade]
    config: Dict[str, Any]

    def summary(self) -> str:
        lines = [
            f"Replay: {self.market}",
            f"  Candles processed : {self.n_candles}",
            f"  Trades            : {self.n_trades}",
            f"  Total PnL         : €{self.pnl_eur:+.2f}  ({self.pnl_pct:+.2f}%)",
            f"  Win rate          : {self.win_rate*100:.1f}%",
            f"  Avg PnL / trade   : €{self.avg_pnl_eur:+.2f}",
            f"  Max drawdown      : €{self.max_drawdown_eur:.2f}",
            f"  Sharpe-like       : {self.sharpe_like:.2f}",
        ]
        return "\n".join(lines)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "market": self.market,
            "n_candles": self.n_candles,
            "n_trades": self.n_trades,
            "pnl_eur": round(self.pnl_eur, 2),
            "pnl_pct": round(self.pnl_pct, 4),
            "win_rate": round(self.win_rate, 4),
            "avg_pnl_eur": round(self.avg_pnl_eur, 2),
            "max_drawdown_eur": round(self.max_drawdown_eur, 2),
            "sharpe_like": round(self.sharpe_like, 4),
            "config": self.config,
            "trades": [
                {
                    "entry_ts": t.entry_ts, "exit_ts": t.exit_ts,
                    "entry": t.entry_price, "exit": t.exit_price,
                    "amount": t.amount, "score": t.score,
                    "pnl_eur": round(t.pnl_eur, 4),
                    "pnl_pct": round(t.pnl_pct, 6),
                    "reason": t.exit_reason,
                }
                for t in self.trades
            ],
            "equity_curve": self.equity_curve,
        }


# ---------- Helpers ----------

def _candle_close(c: Sequence[Any]) -> float:
    return float(c[4])


def _candle_high(c: Sequence[Any]) -> float:
    return float(c[2])


def _candle_low(c: Sequence[Any]) -> float:
    return float(c[3])


def _candle_volume(c: Sequence[Any]) -> float:
    return float(c[5]) if len(c) > 5 else 0.0


def _candle_ts(c: Sequence[Any]) -> float:
    """Bitvavo timestamps are ms; normalise to seconds."""
    ts = float(c[0])
    return ts / 1000.0 if ts > 1e11 else ts


def _score(window: Sequence[Sequence[Any]], market: str, config: Mapping[str, Any]) -> float:
    """Run the live signal pack against a candle window and return total score."""
    try:
        from modules.signals import evaluate_signal_pack
        from modules.signals.base import SignalContext
    except Exception:  # pragma: no cover — keeps engine usable in stripped envs
        return 0.0
    closes = [_candle_close(c) for c in window]
    highs = [_candle_high(c) for c in window]
    lows = [_candle_low(c) for c in window]
    vols = [_candle_volume(c) for c in window]
    ctx = SignalContext(
        market=market,
        candles_1m=window,
        closes_1m=closes,
        highs_1m=highs,
        lows_1m=lows,
        volumes_1m=vols,
        config=dict(config),  # providers may mutate
    )
    pack = evaluate_signal_pack(ctx)
    return float(pack.total_score)


# ---------- Core engine ----------

def run_replay(
    market: str,
    candles: Sequence[Sequence[Any]],
    cfg: Optional[ReplayConfig] = None,
) -> ReplayResult:
    """Replay ``candles`` for a single market and return the result."""
    cfg = cfg or ReplayConfig()
    candles = list(candles)
    if len(candles) < cfg.warmup_candles + 10:
        return _empty_result(market, len(candles), cfg)

    merged_config: Dict[str, Any] = {
        "MIN_SCORE_TO_BUY": cfg.min_score,
        **dict(cfg.extra_config),
    }

    open_trade: Optional[SimTrade] = None
    completed: List[SimTrade] = []
    equity = 0.0
    equity_curve: List[Dict[str, float]] = []
    peak_equity = 0.0
    max_dd = 0.0
    bars_held = 0

    for i in range(cfg.warmup_candles, len(candles)):
        candle = candles[i]
        price = _candle_close(candle)
        ts = _candle_ts(candle)
        high = _candle_high(candle)
        low = _candle_low(candle)

        # ── Manage open trade ──
        if open_trade is not None:
            bars_held += 1
            # Update high water mark with bar high
            if high > open_trade.high_water:
                open_trade.high_water = high
            # Activation
            if not open_trade.activated and price >= open_trade.entry_price * (1 + cfg.trailing_activation_pct):
                open_trade.activated = True
            exit_reason = ""
            exit_price = 0.0
            # Hard stop loss: triggered if low touches it
            sl_price = open_trade.entry_price * (1 - cfg.stop_loss_pct)
            if low <= sl_price:
                exit_price = sl_price
                exit_reason = "stop_loss"
            elif open_trade.activated:
                trail_price = open_trade.high_water * (1 - cfg.trailing_pct)
                if low <= trail_price:
                    exit_price = trail_price
                    exit_reason = "trailing_stop"
            if not exit_reason and bars_held >= cfg.max_hold_bars:
                exit_price = price
                exit_reason = "max_hold"
            if exit_reason:
                open_trade.exit_ts = ts
                open_trade.exit_price = exit_price
                gross = open_trade.amount * exit_price
                fee_out = gross * cfg.fee_pct
                pnl = (gross - fee_out) - open_trade.invested_eur
                open_trade.pnl_eur = pnl
                open_trade.pnl_pct = pnl / open_trade.invested_eur if open_trade.invested_eur else 0.0
                open_trade.exit_reason = exit_reason
                completed.append(open_trade)
                equity += pnl
                if equity > peak_equity:
                    peak_equity = equity
                dd = peak_equity - equity
                if dd > max_dd:
                    max_dd = dd
                open_trade = None
                bars_held = 0

        # ── Look for new entry ──
        if open_trade is None:
            window = candles[max(0, i - cfg.warmup_candles):i + 1]
            score = _score(window, market, merged_config)
            if score >= cfg.min_score:
                fee_in = cfg.base_invest_eur * cfg.fee_pct
                amount = (cfg.base_invest_eur - fee_in) / price if price > 0 else 0.0
                open_trade = SimTrade(
                    market=market,
                    entry_ts=ts,
                    entry_price=price,
                    amount=amount,
                    invested_eur=cfg.base_invest_eur,  # includes fee for cost basis
                    score=score,
                    high_water=price,
                )

        equity_curve.append({"ts": ts, "equity": round(equity, 2)})

    # Close any dangling trade at last close
    if open_trade is not None:
        last_price = _candle_close(candles[-1])
        gross = open_trade.amount * last_price
        fee_out = gross * cfg.fee_pct
        pnl = (gross - fee_out) - open_trade.invested_eur
        open_trade.exit_ts = _candle_ts(candles[-1])
        open_trade.exit_price = last_price
        open_trade.pnl_eur = pnl
        open_trade.pnl_pct = pnl / open_trade.invested_eur if open_trade.invested_eur else 0.0
        open_trade.exit_reason = "end_of_data"
        completed.append(open_trade)
        equity += pnl

    return _summarise(market, candles, completed, equity, max_dd, equity_curve, cfg)


def _summarise(
    market: str,
    candles: Sequence[Sequence[Any]],
    trades: List[SimTrade],
    equity: float,
    max_dd: float,
    curve: List[Dict[str, float]],
    cfg: ReplayConfig,
) -> ReplayResult:
    n = len(trades)
    pnls = [t.pnl_eur for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    win_rate = wins / n if n else 0.0
    avg_pnl = statistics.mean(pnls) if pnls else 0.0
    pnl_pct = equity / cfg.base_invest_eur * 100 if cfg.base_invest_eur else 0.0
    if len(pnls) > 1:
        std = statistics.pstdev(pnls)
        sharpe = avg_pnl / std * math.sqrt(len(pnls)) if std > 1e-9 else 0.0
    else:
        sharpe = 0.0
    return ReplayResult(
        market=market,
        n_candles=len(candles),
        n_trades=n,
        pnl_eur=equity,
        pnl_pct=pnl_pct,
        win_rate=win_rate,
        avg_pnl_eur=avg_pnl,
        max_drawdown_eur=max_dd,
        sharpe_like=sharpe,
        equity_curve=curve,
        trades=trades,
        config={
            "min_score": cfg.min_score,
            "base_invest_eur": cfg.base_invest_eur,
            "fee_pct": cfg.fee_pct,
            "trailing_activation_pct": cfg.trailing_activation_pct,
            "trailing_pct": cfg.trailing_pct,
            "stop_loss_pct": cfg.stop_loss_pct,
            "warmup_candles": cfg.warmup_candles,
            "max_hold_bars": cfg.max_hold_bars,
        },
    )


def _empty_result(market: str, n_candles: int, cfg: ReplayConfig) -> ReplayResult:
    return ReplayResult(
        market=market, n_candles=n_candles, n_trades=0,
        pnl_eur=0.0, pnl_pct=0.0, win_rate=0.0, avg_pnl_eur=0.0,
        max_drawdown_eur=0.0, sharpe_like=0.0,
        equity_curve=[], trades=[],
        config={"min_score": cfg.min_score, "warmup_candles": cfg.warmup_candles},
    )


# ---------- I/O helpers ----------

def load_candles_from_json(path: Path | str) -> List[List[Any]]:
    """Load Bitvavo-style candles from a JSON file (list of lists)."""
    p = Path(path)
    with p.open("r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if isinstance(data, dict) and "candles" in data:
        data = data["candles"]
    if not isinstance(data, list):
        raise ValueError(f"unexpected candle file structure: {type(data)}")
    return [list(row) for row in data]


def save_replay_report(result: ReplayResult, path: Path | str) -> Path:
    """Atomically dump a JSON report. Useful for CI artefacts."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(result.as_dict(), f, ensure_ascii=False, indent=2)
    tmp.replace(p)
    return p


# ---------- CLI ----------

def _main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Run a single-market candle replay backtest")
    ap.add_argument("--market", required=True, help="e.g. BTC-EUR (label only)")
    ap.add_argument("--candles", required=True, help="path to JSON candle file")
    ap.add_argument("--min-score", type=float, default=18.0)
    ap.add_argument("--base-invest", type=float, default=100.0)
    ap.add_argument("--out", default="", help="optional report JSON path")
    args = ap.parse_args()

    candles = load_candles_from_json(args.candles)
    cfg = ReplayConfig(min_score=args.min_score, base_invest_eur=args.base_invest)
    result = run_replay(args.market, candles, cfg)
    print(result.summary())
    if args.out:
        out = save_replay_report(result, args.out)
        print(f"saved: {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
