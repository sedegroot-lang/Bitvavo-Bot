"""
Compare 4 strategies on the same historical 1h candle dataset (24 markets, ~60d).

A) BOT-TAKER     : current bot proxy (4-of-6 trigger), TP+1.5/SL-2, taker 0.25% round-trip
B) BOT-MAKER     : same signals, but maker limit orders 0.05% below ask
                   - assumed fill rate p_fill = 0.65 within 5 min (calibrated conservatively)
                   - if filled: maker fee 0.15% buy-side + 0.25% taker on exit (TP/SL = market) = 0.40% round-trip
                   - if not filled: skip trade
C) DCA-BTCETH    : weekly EUR50 DCA into BTC (70%) + ETH (30%), maker buy 0.15%, never sell
D) BH-BTCETH     : single buy at start in BTC (70%) + ETH (30%), hold to end (taker 0.25% one-side)

All strategies start with EUR 1500 capital. Test window = full dataset (~60d).

Reports: end equity, total PnL, ROI, annualised ROI, max drawdown.
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.train_conformal_supervisor import (  # noqa: E402
    TP_PCT, SL_PCT, HORIZON_BARS, FEATURE_NAMES, build_dataset,
)
from scripts.train_conformal_signalfilter import trigger_mask  # noqa: E402

CANDLES_DIR = ROOT / "data" / "historical_candles"
START_CAPITAL = 1500.0
TRADE_SIZE_EUR = 35.0
MAX_OPEN_TRADES = 5
TAKER_FEE = 0.0025
MAKER_FEE = 0.0015
MAKER_FILL_RATE = 0.65  # conservative: 65% of maker limit-buys get filled within 5 min

# ─── A & B: Bot-style backtest ──────────────────────────────────────────
def backtest_bot(use_maker: bool, seed: int = 42) -> dict:
    ds = build_dataset()
    mask = trigger_mask(ds)
    ds = ds[mask].reset_index(drop=True).sort_values("ts_ms").reset_index(drop=True)

    rng = np.random.default_rng(seed)
    if use_maker:
        # randomly drop trades that wouldn't have filled
        fill_mask = rng.random(len(ds)) < MAKER_FILL_RATE
        ds = ds[fill_mask].reset_index(drop=True)
        round_trip = MAKER_FEE + TAKER_FEE  # buy maker, exit market
    else:
        round_trip = TAKER_FEE * 2  # both sides taker

    equity = START_CAPITAL
    open_slots = 0
    pnl_per_trade = []
    equity_curve = []
    skipped_no_capital = 0
    skipped_full_slots = 0

    # Iterate chronologically. Each row is independent (already labeled with TP/SL outcome).
    # We approximate slot occupancy: each trade locks TRADE_SIZE_EUR for HORIZON_BARS.
    open_trades_until = []  # list of unlock timestamps (ms)

    for _, row in ds.iterrows():
        ts = row["ts_ms"]
        # Free up slots whose horizon has passed
        open_trades_until = [t for t in open_trades_until if t > ts]
        open_slots = len(open_trades_until)

        if open_slots >= MAX_OPEN_TRADES:
            skipped_full_slots += 1
            continue
        if equity < TRADE_SIZE_EUR:
            skipped_no_capital += 1
            continue

        # Take the trade
        outcome = TP_PCT if row["label"] == 1 else SL_PCT
        net_pct = outcome - round_trip
        pnl_eur = net_pct * TRADE_SIZE_EUR
        equity += pnl_eur
        pnl_per_trade.append(pnl_eur)
        equity_curve.append((ts, equity))
        # Lock slot for HORIZON_BARS hours
        open_trades_until.append(ts + HORIZON_BARS * 3600 * 1000)

    # Stats
    eq_arr = np.array([e for _, e in equity_curve]) if equity_curve else np.array([START_CAPITAL])
    peak = np.maximum.accumulate(eq_arr)
    dd = (eq_arr - peak) / peak
    max_dd = float(dd.min())
    total_pnl = equity - START_CAPITAL
    n_trades = len(pnl_per_trade)
    wins = sum(1 for p in pnl_per_trade if p > 0)
    days = (ds["ts_ms"].max() - ds["ts_ms"].min()) / 86_400_000 if len(ds) else 0
    annual_roi = (total_pnl / START_CAPITAL) / max(days, 1) * 365 * 100 if days > 0 else 0
    return {
        "name": "BOT-MAKER" if use_maker else "BOT-TAKER",
        "round_trip_fee_pct": round_trip * 100,
        "trades": n_trades,
        "wins": wins,
        "win_rate": wins / n_trades if n_trades else 0,
        "end_equity": equity,
        "total_pnl": total_pnl,
        "roi_pct": (equity / START_CAPITAL - 1) * 100,
        "annual_roi_pct": annual_roi,
        "max_drawdown_pct": max_dd * 100,
        "skipped_full_slots": skipped_full_slots,
        "skipped_no_capital": skipped_no_capital,
        "test_days": days,
    }


# ─── C: DCA BTC+ETH ─────────────────────────────────────────────────────
def backtest_dca() -> dict:
    btc = pd.read_csv(CANDLES_DIR / "BTC-EUR_1h.csv").sort_values("ts_ms").reset_index(drop=True)
    eth = pd.read_csv(CANDLES_DIR / "ETH-EUR_1h.csv").sort_values("ts_ms").reset_index(drop=True)
    # Weekly DCA: every 168h, allocate 70/30
    cash = START_CAPITAL
    btc_amt = 0.0
    eth_amt = 0.0
    fee = MAKER_FEE
    weekly_invest = 50.0  # EUR per week
    last_invest_ts = btc["ts_ms"].iloc[0]
    equity_curve = []
    for i in range(len(btc)):
        ts = btc["ts_ms"].iloc[i]
        if ts - last_invest_ts >= 7 * 24 * 3600 * 1000 and cash >= weekly_invest:
            # Find ETH row at same timestamp (or nearest)
            j = (eth["ts_ms"] - ts).abs().idxmin()
            eth_price = eth["close"].iloc[j]
            btc_price = btc["close"].iloc[i]
            buy_btc_eur = weekly_invest * 0.7
            buy_eth_eur = weekly_invest * 0.3
            # apply maker fee
            btc_amt += (buy_btc_eur * (1 - fee)) / btc_price
            eth_amt += (buy_eth_eur * (1 - fee)) / eth_price
            cash -= weekly_invest
            last_invest_ts = ts
        # mark equity
        if i % 24 == 0:  # daily snapshot
            j = (eth["ts_ms"] - ts).abs().idxmin()
            value = cash + btc_amt * btc["close"].iloc[i] + eth_amt * eth["close"].iloc[j]
            equity_curve.append((ts, value))

    end_value = cash + btc_amt * btc["close"].iloc[-1] + eth_amt * eth["close"].iloc[-1]
    eq_arr = np.array([v for _, v in equity_curve])
    peak = np.maximum.accumulate(eq_arr)
    dd = (eq_arr - peak) / peak
    max_dd = float(dd.min()) if len(dd) else 0.0
    days = (btc["ts_ms"].iloc[-1] - btc["ts_ms"].iloc[0]) / 86_400_000
    annual_roi = (end_value - START_CAPITAL) / START_CAPITAL / max(days, 1) * 365 * 100
    return {
        "name": "DCA-BTCETH-70/30",
        "weekly_invest_eur": weekly_invest,
        "fee_pct": fee * 100,
        "deployed_capital": START_CAPITAL - cash,
        "btc_amount": btc_amt,
        "eth_amount": eth_amt,
        "cash_left": cash,
        "end_equity": end_value,
        "total_pnl": end_value - START_CAPITAL,
        "roi_pct": (end_value / START_CAPITAL - 1) * 100,
        "annual_roi_pct": annual_roi,
        "max_drawdown_pct": max_dd * 100,
        "test_days": days,
    }


# ─── D: Buy & Hold ──────────────────────────────────────────────────────
def backtest_bh() -> dict:
    btc = pd.read_csv(CANDLES_DIR / "BTC-EUR_1h.csv").sort_values("ts_ms").reset_index(drop=True)
    eth = pd.read_csv(CANDLES_DIR / "ETH-EUR_1h.csv").sort_values("ts_ms").reset_index(drop=True)
    btc_buy = btc["close"].iloc[0]
    eth_buy = eth["close"].iloc[0]
    fee = TAKER_FEE
    btc_eur = START_CAPITAL * 0.7
    eth_eur = START_CAPITAL * 0.3
    btc_amt = btc_eur * (1 - fee) / btc_buy
    eth_amt = eth_eur * (1 - fee) / eth_buy
    # equity curve
    n = min(len(btc), len(eth))
    equity_curve = []
    for i in range(0, n, 24):
        v = btc_amt * btc["close"].iloc[i] + eth_amt * eth["close"].iloc[i]
        equity_curve.append((btc["ts_ms"].iloc[i], v))
    end_value = btc_amt * btc["close"].iloc[n - 1] + eth_amt * eth["close"].iloc[n - 1]
    eq_arr = np.array([v for _, v in equity_curve])
    peak = np.maximum.accumulate(eq_arr)
    dd = (eq_arr - peak) / peak
    max_dd = float(dd.min())
    days = (btc["ts_ms"].iloc[n - 1] - btc["ts_ms"].iloc[0]) / 86_400_000
    annual_roi = (end_value - START_CAPITAL) / START_CAPITAL / max(days, 1) * 365 * 100
    return {
        "name": "BH-BTCETH-70/30",
        "fee_pct": fee * 100,
        "btc_buy_price": btc_buy,
        "eth_buy_price": eth_buy,
        "btc_end_price": btc["close"].iloc[n - 1],
        "eth_end_price": eth["close"].iloc[n - 1],
        "end_equity": end_value,
        "total_pnl": end_value - START_CAPITAL,
        "roi_pct": (end_value / START_CAPITAL - 1) * 100,
        "annual_roi_pct": annual_roi,
        "max_drawdown_pct": max_dd * 100,
        "test_days": days,
    }


def main():
    print("Comparing 4 strategies on identical 60d / 24-market 1h data")
    print(f"Starting capital: EUR{START_CAPITAL:.0f}")
    print()

    results = []
    print(">> A) Backtesting BOT-TAKER (current bot proxy) ...", flush=True)
    results.append(backtest_bot(use_maker=False))
    print(">> B) Backtesting BOT-MAKER (limit orders, 65% fill) ...", flush=True)
    results.append(backtest_bot(use_maker=True))
    print(">> C) Backtesting DCA-BTCETH (70/30 weekly, maker) ...", flush=True)
    results.append(backtest_dca())
    print(">> D) Backtesting BH-BTCETH (70/30 hold) ...", flush=True)
    results.append(backtest_bh())

    print("\n" + "=" * 92)
    print(f"{'Strategy':<22}{'Trades':>8}{'Win%':>7}{'EndEUR':>10}{'PnL EUR':>10}{'ROI':>8}{'AnnROI':>9}{'MaxDD':>8}")
    print("-" * 92)
    for r in results:
        trades = r.get("trades", "-")
        wr = f"{r.get('win_rate', 0)*100:.1f}" if "win_rate" in r else "-"
        print(
            f"{r['name']:<22}"
            f"{str(trades):>8}"
            f"{wr:>7}"
            f"{r['end_equity']:>10.2f}"
            f"{r['total_pnl']:>+10.2f}"
            f"{r['roi_pct']:>+7.2f}%"
            f"{r['annual_roi_pct']:>+8.1f}%"
            f"{r['max_drawdown_pct']:>+7.1f}%"
        )
    print()
    out = ROOT / "ai" / "strategy_comparison_meta.json"
    with out.open("w", encoding="utf-8") as f:
        json.dump({"start_capital": START_CAPITAL, "results": results}, f, indent=2)
    print(f"Meta saved: {out.name}")


if __name__ == "__main__":
    main()
