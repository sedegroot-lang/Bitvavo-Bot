"""
A/B Paper Trading Runner
=========================
Runs two strategy configurations side-by-side on LIVE market data
using simulated orders (TEST_MODE=true). Compares performance after
a configurable number of trades or hours.

Usage:
    python scripts/ab_paper_trade.py --hours 24
    python scripts/ab_paper_trade.py --hours 48 --market BTC-EUR

Strategy A = current bot_config.json settings
Strategy B = modified settings (optimized parameters defined below)

Both strategies see the same live price data but trade independently.
Results saved to reports/ab_test_<timestamp>.json
"""

from __future__ import annotations

import copy
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import argparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.indicators import (
    close_prices,
    ema,
    highs,
    lows,
    macd,
    rsi,
    sma,
    stochastic,
    volumes,
)

try:
    from modules.config import load_config
    BASE_CONFIG = load_config() or {}
except Exception:
    BASE_CONFIG = {}

try:
    from bot.api import get_candles, ticker_price
except Exception:
    get_candles = None
    ticker_price = None


# ──────────────────────────── Strategies ──────────────────────────────

def strategy_a_config() -> Dict[str, Any]:
    """Strategy A: Current production config (baseline)."""
    return copy.deepcopy(BASE_CONFIG)


def strategy_b_config() -> Dict[str, Any]:
    """Strategy B: Optimized parameters for comparison.

    Changes from baseline:
    - Tighter trailing (3% instead of 4%)
    - Higher activation (8% instead of 6%)
    - Stricter entry (min_score +1)
    - RSI band narrowed (38-62 instead of 35-65)
    """
    cfg = copy.deepcopy(BASE_CONFIG)
    cfg["DEFAULT_TRAILING"] = 0.03
    cfg["TRAILING_ACTIVATION_PCT"] = 0.08
    cfg["MIN_SCORE_TO_BUY"] = float(cfg.get("MIN_SCORE_TO_BUY", 6.0)) + 1.0
    cfg["RSI_MIN_BUY"] = 38.0
    cfg["RSI_MAX_BUY"] = 62.0
    return cfg


# ──────────────────────────── Paper Engine ────────────────────────────

@dataclass
class PaperPosition:
    market: str
    buy_price: float
    amount: float
    invested_eur: float
    entry_ts: float
    highest_price: float = 0.0
    tp_done: List[bool] = field(default_factory=lambda: [False, False, False])
    partial_returned: float = 0.0


@dataclass
class PaperTrade:
    market: str
    buy_price: float
    sell_price: float
    profit: float
    reason: str
    entry_ts: float
    exit_ts: float


class PaperTrader:
    """Minimal paper trading engine that uses live prices but simulated orders."""

    def __init__(self, name: str, config: Dict[str, Any]):
        self.name = name
        self.config = config
        self.positions: Dict[str, PaperPosition] = {}
        self.closed_trades: List[PaperTrade] = []
        self.fee = float(config.get("FEE_TAKER", 0.0025))

    def _score(self, candles: list) -> float:
        """Simplified signal score using core indicators."""
        prices = close_prices(candles)
        if len(prices) < 30:
            return 0.0
        score = 0.0
        sma_s = sma(prices, 9)
        sma_l = sma(prices, 21)
        ema_val = ema(prices, 20)
        rsi_val = rsi(prices, 14)
        macd_l, macd_s, _ = macd(prices)
        stoch_val = stochastic(prices)
        price = prices[-1]

        if sma_s and sma_l and sma_s > sma_l:
            score += 1.5
        if sma_s and price > sma_s:
            score += 1.0
        if rsi_val and rsi_val < float(self.config.get("RSI_MAX_BUY", 65)):
            score += 1.0
        if macd_l and macd_s and macd_l > macd_s:
            score += 1.2
        if ema_val and price > ema_val:
            score += 1.0
        if stoch_val and stoch_val < 80:
            score += 0.8
        if rsi_val:
            if rsi_val < float(self.config.get("RSI_MIN_BUY", 35)):
                score -= 2.0
            elif rsi_val > float(self.config.get("RSI_MAX_BUY", 65)):
                score -= 3.0
            if 30 <= rsi_val <= 45:
                score += 1.5
        return score

    def tick(self, market: str, candles: list, current_price: float) -> Optional[str]:
        """Process one tick. Returns action description or None."""
        activation = float(self.config.get("TRAILING_ACTIVATION_PCT", 0.06))
        trail_pct = float(self.config.get("DEFAULT_TRAILING", 0.04))
        hard_sl = float(self.config.get("HARD_SL_ALT_PCT", 0.08))
        tp_targets = [x / 100 for x in self.config.get("TAKE_PROFIT_TARGETS", [5, 8, 12])]
        tp_portions = [x / 100 for x in self.config.get("TAKE_PROFIT_PERCENTAGES", [30, 30, 40])]

        # Exit check
        if market in self.positions:
            pos = self.positions[market]
            pos.highest_price = max(pos.highest_price, current_price)
            profit_pct = (current_price / pos.buy_price) - 1

            # Hard SL
            if profit_pct <= -hard_sl:
                sell_fee = current_price * pos.amount * self.fee
                net = (current_price * pos.amount) - sell_fee + pos.partial_returned
                profit = net - pos.invested_eur
                self.closed_trades.append(PaperTrade(
                    market, pos.buy_price, current_price, round(profit, 4),
                    "hard_sl", pos.entry_ts, time.time()
                ))
                del self.positions[market]
                return f"SL {market} profit=€{profit:.2f}"

            # Trailing stop
            if profit_pct >= activation:
                stop = pos.highest_price * (1 - trail_pct)
                if current_price <= stop:
                    sell_fee = current_price * pos.amount * self.fee
                    net = (current_price * pos.amount) - sell_fee + pos.partial_returned
                    profit = net - pos.invested_eur
                    self.closed_trades.append(PaperTrade(
                        market, pos.buy_price, current_price, round(profit, 4),
                        "trailing", pos.entry_ts, time.time()
                    ))
                    del self.positions[market]
                    return f"TRAIL {market} profit=€{profit:.2f}"

            # Partial TP
            for i, (tgt, prt) in enumerate(zip(tp_targets, tp_portions)):
                if i < len(pos.tp_done) and not pos.tp_done[i] and profit_pct >= tgt:
                    sell_amt = pos.amount * prt
                    sell_val = sell_amt * current_price * (1 - self.fee)
                    pos.partial_returned += sell_val
                    pos.amount -= sell_amt
                    pos.tp_done[i] = True

            if pos.amount <= 0.0001 and market in self.positions:
                profit = pos.partial_returned - pos.invested_eur
                self.closed_trades.append(PaperTrade(
                    market, pos.buy_price, current_price, round(profit, 4),
                    "full_tp", pos.entry_ts, time.time()
                ))
                del self.positions[market]
                return f"FULL_TP {market} profit=€{profit:.2f}"

        # Entry check
        if market not in self.positions:
            score = self._score(candles)
            min_score = float(self.config.get("MIN_SCORE_TO_BUY", 6.0))
            max_trades = int(self.config.get("MAX_OPEN_TRADES", 8))
            if score >= min_score and len(self.positions) < max_trades:
                base_eur = float(self.config.get("BASE_AMOUNT_EUR", 10))
                amount = base_eur / current_price
                invested = base_eur * (1 + self.fee)
                self.positions[market] = PaperPosition(
                    market, current_price, amount, invested, time.time(),
                    highest_price=current_price,
                )
                return f"BUY {market} @{current_price:.4f} score={score:.1f}"

        return None

    def report(self) -> Dict[str, Any]:
        """Generate performance summary."""
        trades = self.closed_trades
        if not trades:
            return {"name": self.name, "trades": 0}
        profits = [t.profit for t in trades]
        wins = [p for p in profits if p > 0]
        losses = [p for p in profits if p < 0]
        return {
            "name": self.name,
            "trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0,
            "total_pnl": round(sum(profits), 2),
            "avg_trade": round(sum(profits) / len(profits), 2),
            "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses else float("inf"),
            "open_positions": len(self.positions),
        }


# ──────────────────────────── Runner ──────────────────────────────────

def run_ab_test(markets: List[str], hours: float, interval_sec: int = 60):
    """Run A/B test for the specified duration."""
    trader_a = PaperTrader("Strategy_A_baseline", strategy_a_config())
    trader_b = PaperTrader("Strategy_B_optimized", strategy_b_config())

    end_time = time.time() + hours * 3600
    tick_count = 0

    print(f"╔══════════════════════════════════════════╗")
    print(f"║  A/B Paper Trading — {len(markets)} markets         ║")
    print(f"║  Duration: {hours:.0f} hours                        ║")
    print(f"╚══════════════════════════════════════════╝\n")

    try:
        while time.time() < end_time:
            tick_count += 1
            for market in markets:
                try:
                    candles = get_candles(market, "1m", 120) if get_candles else []
                    if not candles:
                        continue
                    price = float(candles[-1][4]) if candles else 0
                    if price <= 0:
                        continue

                    action_a = trader_a.tick(market, candles, price)
                    action_b = trader_b.tick(market, candles, price)

                    if action_a:
                        print(f"  [A] {action_a}")
                    if action_b:
                        print(f"  [B] {action_b}")
                except Exception as e:
                    pass  # Skip failed ticks

            if tick_count % 10 == 0:
                elapsed_h = (time.time() - (end_time - hours * 3600)) / 3600
                print(f"  --- Tick {tick_count} ({elapsed_h:.1f}h) | "
                      f"A: {len(trader_a.closed_trades)} trades, "
                      f"B: {len(trader_b.closed_trades)} trades ---")

            time.sleep(interval_sec)

    except KeyboardInterrupt:
        print("\n  Interrupted by user.")

    # Final report
    report_a = trader_a.report()
    report_b = trader_b.report()
    comparison = {
        "timestamp": datetime.now().isoformat(),
        "duration_hours": hours,
        "markets": markets,
        "ticks": tick_count,
        "strategy_a": report_a,
        "strategy_b": report_b,
        "winner": report_a["name"] if report_a.get("total_pnl", 0) >= report_b.get("total_pnl", 0) else report_b["name"],
    }

    # Save
    out_dir = ROOT / "reports" / "ab_tests"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"ab_test_{ts}.json"
    with open(out_path, "w") as f:
        json.dump(comparison, f, indent=2, default=str)

    print(f"\n  ═══ A/B TEST RESULTS ═══")
    print(f"  Strategy A ({report_a['name']}):")
    print(f"    Trades: {report_a.get('trades', 0)}, Win Rate: {report_a.get('win_rate', 0)}%")
    print(f"    P&L: €{report_a.get('total_pnl', 0):.2f}, PF: {report_a.get('profit_factor', 0)}")
    print(f"  Strategy B ({report_b['name']}):")
    print(f"    Trades: {report_b.get('trades', 0)}, Win Rate: {report_b.get('win_rate', 0)}%")
    print(f"    P&L: €{report_b.get('total_pnl', 0):.2f}, PF: {report_b.get('profit_factor', 0)}")
    print(f"\n  Winner: {comparison['winner']}")
    print(f"  Report: {out_path}")

    return comparison


def main():
    parser = argparse.ArgumentParser(description="A/B Paper Trading Runner")
    parser.add_argument("--hours", type=float, default=24, help="Test duration in hours")
    parser.add_argument("--market", type=str, default=None, help="Single market (default: whitelist)")
    parser.add_argument("--interval", type=int, default=60, help="Tick interval in seconds")
    args = parser.parse_args()

    if args.market:
        markets = [args.market]
    else:
        markets = BASE_CONFIG.get("WHITELIST", ["BTC-EUR", "ETH-EUR"])[:5]

    run_ab_test(markets, args.hours, args.interval)


if __name__ == "__main__":
    main()
