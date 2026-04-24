"""
Backtest the Adaptive Capital Council (ACC) idea on the same 60d / 24-market data.

ACC = weekly capital reallocation between 3 arms based on rolling 14d performance.
Arms:
  - ACTIVE  : BOT-TAKER (current bot proxy)
  - DCA     : DCA-BTCETH-70/30 maker
  - CASH    : park EUR (zero return, zero risk)

Allocation rule (weekly rebalance):
  Compute trailing 14d PnL% per arm. Use softmax-of-Sharpe with temp=2 to allocate.
  CASH always gets a baseline 10% (forces some safety even when arms look great).
  Self-Doubt Throttle: if combined Sharpe(14d) < 0, multiply ACTIVE allocation by 0.3
  and divert the difference to CASH.

This simulates the "Council" deciding each Monday based on observed performance.

Comparison with the existing 4 strategies (BOT-TAKER / BOT-MAKER / DCA / BH).

Output: prints table + writes ai/acc_backtest_meta.json
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.train_conformal_supervisor import (  # noqa: E402
    TP_PCT, SL_PCT, HORIZON_BARS, build_dataset,
)
from scripts.train_conformal_signalfilter import trigger_mask  # noqa: E402

CANDLES_DIR = ROOT / "data" / "historical_candles"
START_CAPITAL = 1500.0
TRADE_SIZE_EUR = 35.0
MAX_OPEN_TRADES = 5
TAKER_FEE = 0.0025
MAKER_FEE = 0.0015
WEEK_MS = 7 * 24 * 3600 * 1000
DAY_MS = 24 * 3600 * 1000
LOOKBACK_DAYS = 14
MIN_CASH_FLOOR_PCT = 0.10  # always keep 10% in cash
SOFTMAX_TEMP = 2.0           # higher = more equal allocations
SELF_DOUBT_SHARPE_THRESH = 0.0


def _per_arm_equity_curves(seed: int = 42) -> dict:
    """Run each arm independently on a NORMALISED scale of EUR1000 each so we
    can compute return%-per-day curves. We then apply weekly weights to combine."""

    # ── ACTIVE arm: BOT-TAKER style on EUR1000 with same trade-size ratio ──
    ds = build_dataset()
    mask = trigger_mask(ds)
    ds = ds[mask].reset_index(drop=True).sort_values("ts_ms").reset_index(drop=True)

    base = 1000.0
    trade_size = TRADE_SIZE_EUR  # absolute EUR per trade
    round_trip = TAKER_FEE * 2

    equity = base
    open_until = []
    daily_active = {}  # day_ms_floor -> equity
    for _, row in ds.iterrows():
        ts = int(row["ts_ms"])
        open_until = [t for t in open_until if t > ts]
        if len(open_until) >= MAX_OPEN_TRADES:
            continue
        if equity < trade_size:
            continue
        outcome = TP_PCT if row["label"] == 1 else SL_PCT
        net_pct = outcome - round_trip
        equity += net_pct * trade_size
        open_until.append(ts + HORIZON_BARS * 3600 * 1000)
        day_floor = (ts // DAY_MS) * DAY_MS
        daily_active[day_floor] = equity

    # ── DCA arm: weekly EUR50 of base (so EUR50/EUR1000 = 5%/wk deployment) ──
    btc = pd.read_csv(CANDLES_DIR / "BTC-EUR_1h.csv").sort_values("ts_ms").reset_index(drop=True)
    eth = pd.read_csv(CANDLES_DIR / "ETH-EUR_1h.csv").sort_values("ts_ms").reset_index(drop=True)

    cash_dca = base
    btc_amt = eth_amt = 0.0
    fee = MAKER_FEE
    weekly_invest = base * 0.05  # 5%/wk
    last_inv = int(btc["ts_ms"].iloc[0])
    daily_dca = {}
    for i in range(len(btc)):
        ts = int(btc["ts_ms"].iloc[i])
        if ts - last_inv >= WEEK_MS and cash_dca >= weekly_invest:
            j = (eth["ts_ms"] - ts).abs().idxmin()
            btc_p = float(btc["close"].iloc[i])
            eth_p = float(eth["close"].iloc[j])
            btc_amt += (weekly_invest * 0.7 * (1 - fee)) / btc_p
            eth_amt += (weekly_invest * 0.3 * (1 - fee)) / eth_p
            cash_dca -= weekly_invest
            last_inv = ts
        if i % 24 == 0:
            j = (eth["ts_ms"] - ts).abs().idxmin()
            v = cash_dca + btc_amt * float(btc["close"].iloc[i]) + eth_amt * float(eth["close"].iloc[j])
            day_floor = (ts // DAY_MS) * DAY_MS
            daily_dca[day_floor] = v

    # ── CASH arm: flat EUR1000 ──
    all_days = sorted(set(daily_active.keys()) | set(daily_dca.keys()))
    daily_cash = {d: base for d in all_days}

    # Forward-fill missing days
    def _ff(d_map):
        out = {}
        last = base
        for d in all_days:
            if d in d_map:
                last = d_map[d]
            out[d] = last
        return out

    return {
        "days": all_days,
        "active": _ff(daily_active),
        "dca": _ff(daily_dca),
        "cash": _ff(daily_cash),
    }


def _sharpe(returns: np.ndarray) -> float:
    if len(returns) < 2:
        return 0.0
    mu = returns.mean()
    sd = returns.std(ddof=1)
    if sd <= 1e-12:
        return 0.0
    return float(mu / sd * np.sqrt(252))


def _softmax(x: np.ndarray, temp: float = SOFTMAX_TEMP) -> np.ndarray:
    z = x / max(temp, 1e-6)
    z -= z.max()
    e = np.exp(z)
    return e / e.sum()


def backtest_acc(seed: int = 42) -> dict:
    arms = _per_arm_equity_curves(seed=seed)
    days = arms["days"]
    if len(days) < LOOKBACK_DAYS + 7:
        return {"error": "insufficient data"}

    # Daily returns per arm (% change vs prev day)
    def _to_returns(curve_map):
        vals = np.array([curve_map[d] for d in days], dtype=float)
        rets = np.zeros_like(vals)
        rets[1:] = (vals[1:] / vals[:-1]) - 1.0
        return vals, rets

    v_act, r_act = _to_returns(arms["active"])
    v_dca, r_dca = _to_returns(arms["dca"])
    v_cash, r_cash = _to_returns(arms["cash"])

    # Combined portfolio equity simulation, rebalance weekly
    portfolio = START_CAPITAL
    weights = np.array([0.5, 0.4, 0.1])  # initial: active/dca/cash
    week_anchor = days[0]
    portfolio_curve = []
    weights_history = []
    self_doubt_events = 0

    for i, d in enumerate(days):
        # daily P&L from current weights
        if i > 0:
            day_return = weights[0] * r_act[i] + weights[1] * r_dca[i] + weights[2] * r_cash[i]
            portfolio *= (1.0 + day_return)
        portfolio_curve.append((d, portfolio))

        # Rebalance every 7 days using last 14d arm performance
        if d - week_anchor >= WEEK_MS and i >= LOOKBACK_DAYS:
            lb_start = i - LOOKBACK_DAYS
            sh_act = _sharpe(r_act[lb_start:i])
            sh_dca = _sharpe(r_dca[lb_start:i])
            sh_cash = 0.0  # cash has zero variance & zero return

            sharpes = np.array([sh_act, sh_dca, sh_cash])
            new_w = _softmax(sharpes, temp=SOFTMAX_TEMP)

            # Floor for cash
            if new_w[2] < MIN_CASH_FLOOR_PCT:
                deficit = MIN_CASH_FLOOR_PCT - new_w[2]
                # take proportionally from active+dca
                non_cash = new_w[0] + new_w[1]
                if non_cash > 1e-9:
                    new_w[0] -= deficit * (new_w[0] / non_cash)
                    new_w[1] -= deficit * (new_w[1] / non_cash)
                    new_w[2] = MIN_CASH_FLOOR_PCT

            # Self-Doubt Throttle: combined Sharpe(14d)
            combined_returns = (
                weights[0] * r_act[lb_start:i]
                + weights[1] * r_dca[lb_start:i]
                + weights[2] * r_cash[lb_start:i]
            )
            combined_sharpe = _sharpe(combined_returns)
            if combined_sharpe < SELF_DOUBT_SHARPE_THRESH:
                # cut active by 70%, divert to cash
                divert = new_w[0] * 0.7
                new_w[0] -= divert
                new_w[2] += divert
                self_doubt_events += 1

            # Normalise (paranoid)
            new_w = new_w / new_w.sum()
            weights = new_w
            week_anchor = d
            weights_history.append({
                "day_ms": int(d),
                "active": float(weights[0]),
                "dca": float(weights[1]),
                "cash": float(weights[2]),
                "sh_active": sh_act,
                "sh_dca": sh_dca,
                "sh_combined": combined_sharpe,
            })

    eq_arr = np.array([v for _, v in portfolio_curve])
    peak = np.maximum.accumulate(eq_arr)
    dd = (eq_arr - peak) / peak
    end_eq = float(portfolio_curve[-1][1])
    test_days = (portfolio_curve[-1][0] - portfolio_curve[0][0]) / DAY_MS
    annual = (end_eq - START_CAPITAL) / START_CAPITAL / max(test_days, 1) * 365 * 100

    return {
        "name": "ACC (Bandit + Self-Doubt)",
        "start": START_CAPITAL,
        "end_equity": end_eq,
        "total_pnl": end_eq - START_CAPITAL,
        "roi_pct": (end_eq / START_CAPITAL - 1) * 100,
        "annual_roi_pct": annual,
        "max_drawdown_pct": float(dd.min()) * 100,
        "test_days": test_days,
        "rebalances": len(weights_history),
        "self_doubt_events": self_doubt_events,
        "final_weights": {
            "active": float(weights[0]),
            "dca": float(weights[1]),
            "cash": float(weights[2]),
        },
        "weights_history_first": weights_history[:3],
        "weights_history_last": weights_history[-3:],
    }


def main():
    print("=" * 72)
    print("ACC BACKTEST  vs  current bot strategies (60d / 24 markets)")
    print("=" * 72)

    # Re-import baseline for direct comparison
    from scripts.compare_strategies import backtest_bot, backtest_dca, backtest_bh

    print(">> Baseline: BOT-TAKER ...", flush=True)
    bot = backtest_bot(use_maker=False)
    print(">> Baseline: DCA-BTCETH ...", flush=True)
    dca = backtest_dca()
    print(">> Baseline: BH-BTCETH ...", flush=True)
    bh = backtest_bh()
    print(">> ACC (Bandit + Self-Doubt) ...", flush=True)
    acc = backtest_acc()

    rows = [bot, dca, bh, acc]
    print()
    print(f"{'Strategy':<32} {'End EUR':>10} {'PnL EUR':>9} {'ROI%':>7} {'Annual%':>8} {'MaxDD%':>8}")
    print("-" * 80)
    for r in rows:
        print(f"{r['name']:<32} {r['end_equity']:>10.2f} {r['total_pnl']:>+9.2f} "
              f"{r['roi_pct']:>+7.2f} {r['annual_roi_pct']:>+8.1f} {r['max_drawdown_pct']:>+8.2f}")

    print()
    print("ACC details:")
    print(f"  Rebalances        : {acc['rebalances']}")
    print(f"  Self-Doubt events : {acc['self_doubt_events']}")
    print(f"  Final weights     : ACTIVE={acc['final_weights']['active']:.0%}  "
          f"DCA={acc['final_weights']['dca']:.0%}  CASH={acc['final_weights']['cash']:.0%}")

    out = {
        "baselines": [bot, dca, bh],
        "acc": acc,
    }
    out_path = ROOT / "ai" / "acc_backtest_meta.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nWritten: {out_path}")


if __name__ == "__main__":
    main()
