"""
Backtest Engine v2 — Full-fidelity strategy replay
====================================================
Uses the REAL indicators from core/indicators.py and simulates:
  • Signal scoring (SMA cross, RSI, MACD, EMA, BB, Stoch)
  • Trailing stop with stepped tightening
  • Partial take-profit levels
  • Hard stop-loss
  • Fee-aware P&L (maker/taker)
  • Position sizing via Kelly criterion

Usage:
    python scripts/backtest_engine.py --market BTC-EUR --days 30
    python scripts/backtest_engine.py --market ETH-EUR --days 14 --interval 1m
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Allow imports from project root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.indicators import (
    atr,
    bollinger_bands,
    close_prices,
    ema,
    highs,
    lows,
    macd,
    rsi,
    sma,
    stochastic,
    volumes,
    calculate_momentum_score,
)

try:
    from modules.config import load_config
    CONFIG = load_config() or {}
except Exception:
    CONFIG = {}


# ──────────────────────────── Config ──────────────────────────────────

@dataclass
class BacktestConfig:
    """All tunable parameters for a backtest run."""
    # Entry
    min_score: float = float(CONFIG.get("MIN_SCORE_TO_BUY", 6.0))
    rsi_min_buy: float = float(CONFIG.get("RSI_MIN_BUY", 35.0))
    rsi_max_buy: float = float(CONFIG.get("RSI_MAX_BUY", 65.0))
    sma_short: int = int(CONFIG.get("SMA_SHORT", 9))
    sma_long: int = int(CONFIG.get("SMA_LONG", 21))
    ema_window: int = 20
    breakout_lookback: int = int(CONFIG.get("BREAKOUT_LOOKBACK", 20))

    # Position sizing
    base_amount_eur: float = float(CONFIG.get("BASE_AMOUNT_EUR", 10))
    max_open_trades: int = 1  # backtest one market at a time
    fee_taker: float = float(CONFIG.get("FEE_TAKER", 0.0025))
    fee_maker: float = float(CONFIG.get("FEE_MAKER", 0.0015))

    # Trailing stop
    trailing_activation_pct: float = float(CONFIG.get("TRAILING_ACTIVATION_PCT", 0.06))
    default_trailing: float = float(CONFIG.get("DEFAULT_TRAILING", 0.04))
    stepped_trailing: List[Tuple[float, float]] = field(default_factory=lambda: [
        (0.02, 0.012),
        (0.04, 0.008),
        (0.06, 0.006),
        (0.10, 0.005),
        (0.15, 0.004),
        (0.25, 0.003),
    ])

    # Partial TP
    tp_targets: List[float] = field(default_factory=lambda: [
        float(x) / 100 for x in CONFIG.get("TAKE_PROFIT_TARGETS", [5, 8, 12])
    ])
    tp_portions: List[float] = field(default_factory=lambda: [
        float(x) / 100 for x in CONFIG.get("TAKE_PROFIT_PERCENTAGES", [30, 30, 40])
    ])

    # Hard SL
    hard_sl_pct: float = float(CONFIG.get("HARD_SL_ALT_PCT", 0.08))

    # Max age (hours)
    max_age_h: float = float(CONFIG.get("MAX_TRADE_AGE_HOURS", 48))

    # Signal weights
    signal_weights: Dict[str, float] = field(default_factory=lambda: CONFIG.get("SIGNAL_WEIGHTS", {
        "sma_cross": 1.5,
        "price_above_sma": 1.0,
        "rsi_ok": 1.0,
        "macd_ok": 1.2,
        "ema_ok": 1.0,
        "bb_breakout": 1.2,
        "stoch_ok": 0.8,
    }))


# ──────────────────────────── Data ────────────────────────────────────

CACHE_DIR = ROOT / "data" / "candle_cache"


def fetch_candles(market: str, interval: str, days: int) -> List[list]:
    """Fetch candles from Bitvavo API with local disk caching."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{market}_{interval}_{days}d.json"

    # Use cache if < 1 hour old
    if cache_file.exists():
        age_s = time.time() - cache_file.stat().st_mtime
        if age_s < 3600:
            with open(cache_file, "r") as f:
                return json.load(f)

    # Initialize API if needed (for standalone CLI usage)
    from bot import api as _api
    if not hasattr(_api, '_bv') or _api._bv is None:
        try:
            from modules.trading import bitvavo as _bv_client
            _api.init(bitvavo_client=_bv_client, config=CONFIG or {})
        except Exception as e:
            print(f"  ERROR: Could not initialize Bitvavo API: {e}")
            sys.exit(1)
    from bot.api import get_candles as api_get_candles

    all_candles: List[list] = []
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (days * 86400 * 1000)

    # Bitvavo returns max ~1440 candles per request for 1m
    chunk_ms = {
        "1m": 1440 * 60_000,
        "5m": 1440 * 300_000,
        "15m": 1440 * 900_000,
        "1h": 1440 * 3_600_000,
        "4h": 1440 * 14_400_000,
        "1d": 1440 * 86_400_000,
    }.get(interval, 1440 * 60_000)

    cursor = start_ms
    while cursor < end_ms:
        chunk_end = min(cursor + chunk_ms, end_ms)
        # bot/api.get_candles expects seconds (it multiplies by 1000 internally)
        candles = api_get_candles(market, interval, limit=1440, start=cursor / 1000, end=chunk_end / 1000)
        if candles:
            all_candles.extend(candles)
        cursor = chunk_end
        time.sleep(0.15)  # Rate limit

    # Deduplicate by timestamp and sort
    seen = set()
    unique = []
    for c in all_candles:
        ts = c[0] if c else None
        if ts and ts not in seen:
            seen.add(ts)
            unique.append(c)
    unique.sort(key=lambda x: x[0])

    # Cache to disk
    with open(cache_file, "w") as f:
        json.dump(unique, f)

    print(f"  Fetched {len(unique)} candles for {market} ({interval}, {days}d)")
    return unique


# ──────────────────────────── Scoring ─────────────────────────────────

def compute_signal_score(
    candles: List[list], cfg: BacktestConfig
) -> Tuple[float, Dict[str, Any]]:
    """Compute entry signal score from candle window (mimics bot/signals.py)."""
    prices = close_prices(candles)
    if len(prices) < cfg.sma_long + 5:
        return 0.0, {}

    h_vals = highs(candles)
    l_vals = lows(candles)
    vol_vals = volumes(candles)

    sma_s = sma(prices, cfg.sma_short)
    sma_l = sma(prices, cfg.sma_long)
    ema_val = ema(prices, cfg.ema_window)
    rsi_val = rsi(prices, 14)
    macd_line, macd_sig, macd_hist = macd(prices)
    bb_upper, bb_mid, bb_lower = bollinger_bands(prices)
    stoch_val = stochastic(prices)
    mom_score = calculate_momentum_score(candles)
    atr_val = atr(h_vals, l_vals, prices) if len(h_vals) > 15 else None

    score = 0.0
    signals = {}
    w = cfg.signal_weights
    price = prices[-1]

    # SMA cross
    if sma_s is not None and sma_l is not None and sma_s > sma_l:
        score += w.get("sma_cross", 1.5)
        signals["sma_cross"] = True

    # Price above SMA(short)
    if sma_s is not None and price > sma_s:
        score += w.get("price_above_sma", 1.0)
        signals["price_above_sma"] = True

    # RSI ok
    if rsi_val is not None and rsi_val < cfg.rsi_max_buy:
        score += w.get("rsi_ok", 1.0)
        signals["rsi_ok"] = True

    # MACD
    if macd_line is not None and macd_sig is not None and macd_line > macd_sig:
        score += w.get("macd_ok", 1.2)
        signals["macd_ok"] = True

    # EMA
    if ema_val is not None and price > ema_val:
        score += w.get("ema_ok", 1.0)
        signals["ema_ok"] = True

    # BB breakout
    if len(prices) >= 2 and prices[-1] > prices[-2] * 1.01:
        score += w.get("bb_breakout", 1.2)
        signals["bb_breakout"] = True

    # Stochastic
    if stoch_val is not None and stoch_val < 80:
        score += w.get("stoch_ok", 0.8)
        signals["stoch_ok"] = True

    # RSI momentum bonus
    if rsi_val is not None:
        if 30 <= rsi_val <= 45:
            score += 1.5
            signals["rsi_momentum"] = "strong"
        elif 45 < rsi_val <= 55:
            score += 0.5
            signals["rsi_momentum"] = "mild"

    # RSI penalty
    if rsi_val is not None:
        if rsi_val < cfg.rsi_min_buy:
            score -= 2.0
        elif rsi_val > cfg.rsi_max_buy:
            score -= 3.0

    # Momentum filter
    if mom_score < -2:
        score -= 3.0
        signals["momentum_block"] = True

    signals["rsi"] = rsi_val
    signals["macd_hist"] = macd_hist
    signals["stoch"] = stoch_val
    signals["atr"] = atr_val
    signals["momentum"] = mom_score

    return score, signals


# ──────────────────────────── Position ────────────────────────────────

@dataclass
class Position:
    market: str
    buy_price: float
    amount: float
    invested_eur: float
    entry_ts: float  # candle timestamp
    highest_price: float = 0.0
    tp_levels_done: List[bool] = field(default_factory=lambda: [False, False, False])
    partial_returned: float = 0.0
    total_invested: float = 0.0

    def __post_init__(self):
        self.highest_price = self.buy_price
        self.total_invested = self.invested_eur


# ──────────────────────────── Engine ──────────────────────────────────

@dataclass
class TradeResult:
    market: str
    buy_price: float
    sell_price: float
    amount: float
    invested_eur: float
    profit: float
    reason: str
    entry_ts: float
    exit_ts: float
    partial_returned: float = 0.0
    hold_bars: int = 0


def _trailing_pct(profit_pct: float, cfg: BacktestConfig) -> float:
    """Compute effective trailing stop % based on stepped levels."""
    trail = cfg.default_trailing
    for threshold, tighter in cfg.stepped_trailing:
        if profit_pct >= threshold:
            trail = tighter
    return trail


def run_backtest(
    market: str,
    candles: List[list],
    cfg: BacktestConfig,
) -> List[TradeResult]:
    """
    Run a full backtest on a candle series.
    Returns list of completed trades.
    """
    results: List[TradeResult] = []
    position: Optional[Position] = None
    lookback = max(cfg.sma_long + 10, 60)

    for i in range(lookback, len(candles)):
        candle = candles[i]
        ts = float(candle[0])
        o, h, l, c = float(candle[1]), float(candle[2]), float(candle[3]), float(candle[4])
        window = candles[i - lookback : i + 1]
        price = c

        # ── Exit logic (if in position) ──
        if position is not None:
            position.highest_price = max(position.highest_price, h)
            profit_pct = (price / position.buy_price - 1) if position.buy_price > 0 else 0
            age_bars = i - getattr(position, '_entry_bar', i)

            # Hard stop-loss
            if profit_pct <= -cfg.hard_sl_pct:
                sell_fee = price * position.amount * cfg.fee_taker
                net_proceeds = (price * position.amount) - sell_fee
                profit = (net_proceeds + position.partial_returned) - position.total_invested
                results.append(TradeResult(
                    market=market, buy_price=position.buy_price, sell_price=price,
                    amount=position.amount, invested_eur=position.invested_eur,
                    profit=round(profit, 4), reason="hard_sl",
                    entry_ts=position.entry_ts, exit_ts=ts,
                    partial_returned=position.partial_returned, hold_bars=age_bars,
                ))
                position = None
                continue

            # Max age exit (only if in profit)
            if cfg.max_age_h > 0 and age_bars > cfg.max_age_h * 60:  # bars = minutes for 1m
                if profit_pct > 0:
                    sell_fee = price * position.amount * cfg.fee_taker
                    net_proceeds = (price * position.amount) - sell_fee
                    profit = (net_proceeds + position.partial_returned) - position.total_invested
                    results.append(TradeResult(
                        market=market, buy_price=position.buy_price, sell_price=price,
                        amount=position.amount, invested_eur=position.invested_eur,
                        profit=round(profit, 4), reason="max_age",
                        entry_ts=position.entry_ts, exit_ts=ts,
                        partial_returned=position.partial_returned, hold_bars=age_bars,
                    ))
                    position = None
                    continue

            # Partial take-profit
            for level_idx, (target, portion) in enumerate(
                zip(cfg.tp_targets, cfg.tp_portions)
            ):
                if level_idx < len(position.tp_levels_done) and not position.tp_levels_done[level_idx]:
                    if profit_pct >= target:
                        sell_amount = position.amount * portion
                        sell_value = sell_amount * price
                        sell_fee = sell_value * cfg.fee_taker
                        net = sell_value - sell_fee
                        position.partial_returned += net
                        position.amount -= sell_amount
                        position.invested_eur -= position.invested_eur * portion
                        position.tp_levels_done[level_idx] = True

            # Check if fully sold via partial TP
            if position is not None and position.amount <= 0.0001:
                profit = position.partial_returned - position.total_invested
                results.append(TradeResult(
                    market=market, buy_price=position.buy_price, sell_price=price,
                    amount=0, invested_eur=position.total_invested,
                    profit=round(profit, 4), reason="partial_tp_full",
                    entry_ts=position.entry_ts, exit_ts=ts,
                    partial_returned=position.partial_returned, hold_bars=age_bars,
                ))
                position = None
                continue

            # Trailing stop (only after activation)
            if profit_pct >= cfg.trailing_activation_pct:
                trail = _trailing_pct(profit_pct, cfg)
                stop_price = position.highest_price * (1 - trail)
                if price <= stop_price:
                    sell_fee = price * position.amount * cfg.fee_taker
                    net_proceeds = (price * position.amount) - sell_fee
                    profit = (net_proceeds + position.partial_returned) - position.total_invested
                    results.append(TradeResult(
                        market=market, buy_price=position.buy_price, sell_price=price,
                        amount=position.amount, invested_eur=position.invested_eur,
                        profit=round(profit, 4), reason="trailing_stop",
                        entry_ts=position.entry_ts, exit_ts=ts,
                        partial_returned=position.partial_returned, hold_bars=age_bars,
                    ))
                    position = None
                    continue

        # ── Entry logic (only if no position) ──
        if position is None:
            score, signals = compute_signal_score(window, cfg)
            if score >= cfg.min_score:
                buy_price = price
                amount = cfg.base_amount_eur / buy_price
                buy_fee = cfg.base_amount_eur * cfg.fee_taker
                invested = cfg.base_amount_eur + buy_fee
                position = Position(
                    market=market,
                    buy_price=buy_price,
                    amount=amount,
                    invested_eur=invested,
                    entry_ts=ts,
                )
                position._entry_bar = i  # type: ignore[attr-defined]

    # Close any remaining position at the last price
    if position is not None:
        last_price = float(candles[-1][4])
        sell_fee = last_price * position.amount * cfg.fee_taker
        net_proceeds = (last_price * position.amount) - sell_fee
        profit = (net_proceeds + position.partial_returned) - position.total_invested
        results.append(TradeResult(
            market=market, buy_price=position.buy_price, sell_price=last_price,
            amount=position.amount, invested_eur=position.total_invested,
            profit=round(profit, 4), reason="end_of_data",
            entry_ts=position.entry_ts, exit_ts=float(candles[-1][0]),
            partial_returned=position.partial_returned,
            hold_bars=len(candles) - getattr(position, '_entry_bar', len(candles)),
        ))

    return results


# ──────────────────────────── Reporting ───────────────────────────────

def generate_report(results: List[TradeResult], market: str) -> Dict[str, Any]:
    """Generate comprehensive backtest report."""
    if not results:
        return {"market": market, "total_trades": 0, "note": "No trades generated"}

    profits = [r.profit for r in results]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p < 0]

    total_pnl = sum(profits)
    win_rate = len(wins) / len(profits) * 100 if profits else 0

    # Max drawdown
    cumulative = 0
    peak = 0
    max_dd = 0
    for p in profits:
        cumulative += p
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    # Sharpe ratio (per-trade)
    import numpy as np
    returns = np.array(profits)
    sharpe = float(np.mean(returns) / np.std(returns) * np.sqrt(252)) if len(returns) > 1 and np.std(returns) > 0 else 0

    # By reason
    by_reason: Dict[str, int] = {}
    for r in results:
        by_reason[r.reason] = by_reason.get(r.reason, 0) + 1

    avg_hold = sum(r.hold_bars for r in results) / len(results) if results else 0

    total_invested = sum(r.invested_eur for r in results)
    roi_pct = (total_pnl / total_invested * 100) if total_invested > 0 else 0

    return {
        "market": market,
        "total_trades": len(results),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(win_rate, 1),
        "total_pnl_eur": round(total_pnl, 2),
        "avg_profit": round(sum(profits) / len(profits), 2) if profits else 0,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
        "max_drawdown_eur": round(max_dd, 2),
        "sharpe_ratio": round(sharpe, 2),
        "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses else float("inf"),
        "roi_pct": round(roi_pct, 2),
        "avg_hold_bars": round(avg_hold, 0),
        "by_exit_reason": by_reason,
        "total_invested": round(total_invested, 2),
    }


def save_results(
    results: List[TradeResult], report: Dict[str, Any], market: str, days: int
) -> Tuple[str, str]:
    """Save trade log CSV and report JSON."""
    out_dir = ROOT / "reports" / "backtest"
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = out_dir / f"bt_{market}_{days}d_{ts}.csv"
    json_path = out_dir / f"bt_{market}_{days}d_{ts}.json"

    # CSV
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "market", "buy_price", "sell_price", "amount", "invested_eur",
            "profit", "reason", "entry_ts", "exit_ts", "hold_bars", "partial_returned",
        ])
        writer.writeheader()
        for r in results:
            writer.writerow({
                "market": r.market, "buy_price": r.buy_price,
                "sell_price": r.sell_price, "amount": round(r.amount, 8),
                "invested_eur": r.invested_eur, "profit": r.profit,
                "reason": r.reason,
                "entry_ts": datetime.utcfromtimestamp(r.entry_ts / 1000).isoformat() if r.entry_ts > 1e12 else r.entry_ts,
                "exit_ts": datetime.utcfromtimestamp(r.exit_ts / 1000).isoformat() if r.exit_ts > 1e12 else r.exit_ts,
                "hold_bars": r.hold_bars, "partial_returned": r.partial_returned,
            })

    # JSON
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    return str(csv_path), str(json_path)


# ──────────────────────────── CLI ─────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Backtest Engine v2")
    parser.add_argument("--market", default="BTC-EUR", help="Market to backtest")
    parser.add_argument("--days", type=int, default=14, help="Days of history")
    parser.add_argument("--interval", default="1m", help="Candle interval")
    parser.add_argument("--min-score", type=float, default=None, help="Override min score")
    parser.add_argument("--sl", type=float, default=None, help="Override hard SL %")
    parser.add_argument("--trailing", type=float, default=None, help="Override trailing %")
    parser.add_argument("--activation", type=float, default=None, help="Override trailing activation %")
    args = parser.parse_args()

    cfg = BacktestConfig()
    if args.min_score is not None:
        cfg.min_score = args.min_score
    if args.sl is not None:
        cfg.hard_sl_pct = args.sl
    if args.trailing is not None:
        cfg.default_trailing = args.trailing
    if args.activation is not None:
        cfg.trailing_activation_pct = args.activation

    print(f"╔══════════════════════════════════════════╗")
    print(f"║  Backtest Engine v2 — {args.market:<18} ║")
    print(f"╠══════════════════════════════════════════╣")
    print(f"║  Period:    {args.days} days                        ║")
    print(f"║  Interval:  {args.interval:<28}  ║")
    print(f"║  Min Score: {cfg.min_score:<28}  ║")
    print(f"║  Trailing:  {cfg.trailing_activation_pct*100:.1f}% act / {cfg.default_trailing*100:.1f}% trail     ║")
    print(f"║  Hard SL:   {cfg.hard_sl_pct*100:.1f}%                         ║")
    print(f"║  Fee:       {cfg.fee_taker*100:.2f}% taker                 ║")
    print(f"╚══════════════════════════════════════════╝")

    print(f"\n  Fetching candles...")
    candles = fetch_candles(args.market, args.interval, args.days)
    if len(candles) < 100:
        print(f"  ERROR: Only {len(candles)} candles — not enough data")
        sys.exit(1)

    print(f"  Running backtest on {len(candles)} candles...")
    results = run_backtest(args.market, candles, cfg)
    report = generate_report(results, args.market)

    csv_p, json_p = save_results(results, report, args.market, args.days)

    print(f"\n  ═══ RESULTS ═══")
    print(f"  Trades:       {report['total_trades']}")
    print(f"  Win Rate:     {report.get('win_rate_pct', 0)}%")
    print(f"  Total P&L:    €{report.get('total_pnl_eur', 0):.2f}")
    print(f"  ROI:          {report.get('roi_pct', 0):.2f}%")
    print(f"  Profit Factor:{report.get('profit_factor', 0):.2f}")
    print(f"  Sharpe:       {report.get('sharpe_ratio', 0):.2f}")
    print(f"  Max DD:       €{report.get('max_drawdown_eur', 0):.2f}")
    print(f"  Avg Hold:     {report.get('avg_hold_bars', 0):.0f} bars")
    print(f"  Exit Reasons: {report.get('by_exit_reason', {})}")
    print(f"\n  CSV:  {csv_p}")
    print(f"  JSON: {json_p}")


if __name__ == "__main__":
    main()
