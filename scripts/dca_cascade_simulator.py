"""
Cascading DCA Strategy Simulator
=================================
Valideert de cascading DCA configuratie met:
  1. Wiskundige analyse: break-even, ladder, kosten
  2. Scenario-analyse: diverse drawdown-niveaus
  3. Monte Carlo: 10.000 random price paths
  4. Historische replay: echte Bitvavo-data (optioneel)

Usage:
    python scripts/dca_cascade_simulator.py
    python scripts/dca_cascade_simulator.py --historical BTC-EUR --days 90
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ═══════════════════════════ CONFIG ════════════════════════════════════

@dataclass
class DCAConfig:
    base_amount: float = 38.0
    dca_amount: float = 30.4       # BASE * scale (first DCA)
    scale_factor: float = 0.8      # each next DCA = prev * scale
    max_buys: int = 9              # number of DCA levels
    drop_pct: float = 0.02         # 2% drop per DCA level
    step_multiplier: float = 1.0   # gap growth between levels
    fee_pct: float = 0.0025        # Bitvavo taker fee
    trailing_activation: float = 0.015   # 1.5%
    default_trailing: float = 0.025      # 2.5%
    stepped_trailing: List[Tuple[float, float]] = field(default_factory=lambda: [
        (0.015, 0.012), (0.03, 0.01), (0.05, 0.008),
        (0.08, 0.006), (0.12, 0.005), (0.18, 0.004), (0.25, 0.003),
    ])
    tp_targets: List[float] = field(default_factory=lambda: [0.03, 0.06, 0.10])
    tp_portions: List[float] = field(default_factory=lambda: [0.30, 0.35, 0.35])
    max_trades: int = 2


def load_from_bot_config() -> DCAConfig:
    """Load DCA config from bot_config.json + overrides."""
    cfg = DCAConfig()
    try:
        from modules.config import load_config
        bc = load_config() or {}
        cfg.base_amount = float(bc.get('BASE_AMOUNT_EUR', cfg.base_amount))
        cfg.dca_amount = float(bc.get('DCA_AMOUNT_EUR', cfg.dca_amount))
        cfg.scale_factor = float(bc.get('DCA_SIZE_MULTIPLIER', cfg.scale_factor))
        cfg.max_buys = int(bc.get('DCA_MAX_BUYS', cfg.max_buys))
        cfg.drop_pct = float(bc.get('DCA_DROP_PCT', cfg.drop_pct))
        cfg.step_multiplier = float(bc.get('DCA_STEP_MULTIPLIER', cfg.step_multiplier))
        cfg.fee_pct = float(bc.get('FEE_TAKER', cfg.fee_pct))
        cfg.trailing_activation = float(bc.get('TRAILING_ACTIVATION_PCT', cfg.trailing_activation))
        cfg.default_trailing = float(bc.get('DEFAULT_TRAILING', cfg.default_trailing))
        cfg.max_trades = int(bc.get('MAX_OPEN_TRADES', cfg.max_trades))
        tp = bc.get('TAKE_PROFIT_TARGETS', cfg.tp_targets)
        if tp:
            cfg.tp_targets = [float(x) for x in tp]
        pp = bc.get('TAKE_PROFIT_PERCENTAGES', cfg.tp_portions)
        if pp:
            cfg.tp_portions = [float(x) for x in pp]
    except Exception:
        pass
    return cfg


# ═══════════════════════════ DCA LADDER ═══════════════════════════════

def compute_ladder(cfg: DCAConfig) -> List[Dict]:
    """Build the full DCA ladder with amounts, prices, and running totals."""
    ladder = []
    entry_price = 100.0  # normalized to 100 for easy % math

    # Base entry
    base_fee = cfg.base_amount * cfg.fee_pct
    base_coins = cfg.base_amount / entry_price
    ladder.append({
        'level': 'BASE',
        'price': entry_price,
        'drop_pct': 0.0,
        'amount_eur': cfg.base_amount,
        'fee': round(base_fee, 4),
        'coins': base_coins,
        'cum_invested': cfg.base_amount + base_fee,
        'cum_coins': base_coins,
        'avg_price': (cfg.base_amount + base_fee) / base_coins,
        'breakeven_price': (cfg.base_amount + base_fee) / base_coins,
    })

    cum_invested = cfg.base_amount + base_fee
    cum_coins = base_coins

    for i in range(cfg.max_buys):
        # Drop from entry: drop_pct * (i+1) * step_multiplier^i
        cum_drop = sum(cfg.drop_pct * (cfg.step_multiplier ** j) for j in range(i + 1))
        price = entry_price * (1 - cum_drop)

        # DCA amount: dca_amount * scale^i
        amount = cfg.dca_amount * (cfg.scale_factor ** i)
        fee = amount * cfg.fee_pct
        coins = amount / price

        cum_invested += amount + fee
        cum_coins += coins
        avg_price = cum_invested / cum_coins

        # Break-even price (need to sell at this price + fee to recover invested)
        breakeven = cum_invested / (cum_coins * (1 - cfg.fee_pct))

        ladder.append({
            'level': f'DCA{i+1}',
            'price': round(price, 4),
            'drop_pct': round(cum_drop * 100, 2),
            'amount_eur': round(amount, 2),
            'fee': round(fee, 4),
            'coins': round(coins, 6),
            'cum_invested': round(cum_invested, 2),
            'cum_coins': round(cum_coins, 6),
            'avg_price': round(avg_price, 4),
            'breakeven_price': round(breakeven, 4),
        })

    return ladder


def print_ladder(ladder: List[Dict], cfg: DCAConfig):
    """Pretty-print the DCA ladder."""
    print("\n╔═══════════════════════════════════════════════════════════════════════════════╗")
    print("║                    CASCADING DCA LADDER — PER TRADE                         ║")
    print("╠═══════╦═════════╦═══════╦══════════╦═══════════╦══════════╦══════════════════╣")
    print("║ Level ║  Price  ║ Drop  ║ Amount € ║ Invested  ║ Avg Price║ Break-even Price ║")
    print("╠═══════╬═════════╬═══════╬══════════╬═══════════╬══════════╬══════════════════╣")
    for row in ladder:
        print(f"║ {row['level']:>5} ║ {row['price']:>7.2f} ║ {row['drop_pct']:>5.1f}%║ €{row['amount_eur']:>7.2f} "
              f"║ €{row['cum_invested']:>7.2f} ║ {row['avg_price']:>8.4f} ║ {row['breakeven_price']:>14.4f}   ║")
    print("╚═══════╩═════════╩═══════╩══════════╩═══════════╩══════════╩══════════════════╝")

    total = ladder[-1]['cum_invested']
    print(f"\n  Per trade budget:  €{total:.2f}")
    print(f"  Max trades:        {cfg.max_trades}")
    print(f"  Total max budget:  €{total * cfg.max_trades:.2f}")
    print(f"  Max drawdown:      {ladder[-1]['drop_pct']:.1f}%")

    # Break-even bounce from bottom
    bottom_price = ladder[-1]['price']
    be_price = ladder[-1]['breakeven_price']
    bounce_pct = (be_price / bottom_price - 1) * 100
    print(f"  Break-even bounce: {bounce_pct:.2f}% from bottom ({bottom_price:.2f} → {be_price:.4f})")


# ═══════════════════════════ SCENARIO ANALYSIS ════════════════════════

def scenario_analysis(cfg: DCAConfig):
    """Analyze outcomes at different drawdown depths."""
    print("\n╔═══════════════════════════════════════════════════════════════════════════════╗")
    print("║                         SCENARIO ANALYSE                                    ║")
    print("╠════════════════════╦═══════════╦═══════════╦═══════════╦═════════════════════╣")
    print("║ Scenario           ║ DCA Levels║ Invested  ║ Avg Entry ║ Bounce voor BE      ║")
    print("╠════════════════════╬═══════════╬═══════════╬═══════════╬═════════════════════╣")

    ladder = compute_ladder(cfg)

    scenarios = [
        ("Kleine dip -2%", 0.02),
        ("Medium dip -5%", 0.05),
        ("Stevige dip -8%", 0.08),
        ("Correctie -12%", 0.12),
        ("Grote correctie -15%", 0.15),
        ("Max DCA -18%", 0.18),
        ("Beyond DCA -25%", 0.25),
        ("Crash -35%", 0.35),
    ]

    for name, max_drop in scenarios:
        # How many DCA levels fire at this drop?
        entry_price = 100.0
        cum_invested = cfg.base_amount + cfg.base_amount * cfg.fee_pct
        cum_coins = cfg.base_amount / entry_price
        dca_fired = 0

        for i in range(cfg.max_buys):
            cum_drop = sum(cfg.drop_pct * (cfg.step_multiplier ** j) for j in range(i + 1))
            if cum_drop <= max_drop:
                price = entry_price * (1 - cum_drop)
                amount = cfg.dca_amount * (cfg.scale_factor ** i)
                fee = amount * cfg.fee_pct
                cum_invested += amount + fee
                cum_coins += amount / price
                dca_fired += 1
            else:
                break

        avg_price = cum_invested / cum_coins
        bottom_price = entry_price * (1 - max_drop)
        be_price = cum_invested / (cum_coins * (1 - cfg.fee_pct))
        bounce_needed = (be_price / bottom_price - 1) * 100

        print(f"║ {name:<18} ║ {dca_fired:>9} ║ €{cum_invested:>7.2f} ║ {avg_price:>9.4f} ║ {bounce_needed:>7.2f}% van bodem  ║")

    print("╚════════════════════╩═══════════╩═══════════╩═══════════╩═════════════════════╝")


# ═══════════════════════════ TRAILING EXIT SIM ════════════════════════

def simulate_trailing_exit(entry_price: float, bounce_pct: float, cfg: DCAConfig) -> Tuple[float, str]:
    """Simulate where trailing stop would trigger on a V-shaped bounce."""
    peak = entry_price * (1 + bounce_pct)
    profit_pct = bounce_pct

    # Determine effective trailing %
    trail = cfg.default_trailing
    for threshold, tighter in cfg.stepped_trailing:
        if profit_pct >= threshold:
            trail = tighter

    # Only fire if bounce >= activation
    if profit_pct < cfg.trailing_activation:
        return 0.0, "no_activation"

    exit_price = peak * (1 - trail)
    net_profit_pct = (exit_price / entry_price - 1)
    return net_profit_pct, f"trail@{trail*100:.1f}%"


def trailing_exit_table(cfg: DCAConfig):
    """Show trailing exit outcomes for different bounce sizes."""
    print("\n╔═══════════════════════════════════════════════════════════════════════════════╗")
    print("║                   TRAILING EXIT — NÁ BOUNCE                                 ║")
    print("╠════════════╦══════════════╦═══════════════╦═════════════════════════════════╣")
    print("║ Bounce %   ║ Exit Trail % ║ Netto Profit  ║ Op €169.60 invested             ║")
    print("╠════════════╬══════════════╬═══════════════╬═════════════════════════════════╣")

    bounces = [0.01, 0.015, 0.02, 0.025, 0.03, 0.04, 0.05, 0.08, 0.10, 0.15, 0.20, 0.30]
    for b in bounces:
        net, reason = simulate_trailing_exit(100.0, b, cfg)
        eur = net * 169.60
        if net > 0:
            print(f"║ {b*100:>8.1f}%  ║ {reason:>12} ║ {net*100:>+11.2f}%  ║ €{eur:>+7.2f}                        ║")
        else:
            print(f"║ {b*100:>8.1f}%  ║ {'—':>12} ║ {'geen exit':>13} ║ {'trade open':>31} ║")

    print("╚════════════╩══════════════╩═══════════════╩═════════════════════════════════╝")


# ═══════════════════════════ MONTE CARLO ══════════════════════════════

def monte_carlo_simulation(cfg: DCAConfig, n_simulations: int = 10000, periods: int = 720):
    """
    Monte Carlo simulatie met realistische crypto price paths.
    Parameters tuned voor alt-coins: hoge volatiliteit, mean-reverting.
    periods = 720 (= 30 dagen in uur-candles)
    """
    print(f"\n╔═══════════════════════════════════════════════════════════════════════════════╗")
    print(f"║              MONTE CARLO SIMULATIE — {n_simulations} PATHS, {periods}h                      ║")
    print(f"╚═══════════════════════════════════════════════════════════════════════════════╝")

    # Alt-coin parameters (hourly)
    hourly_drift = 0.00005        # slight positive drift (≈ +1.2%/mo)
    hourly_vol = 0.015            # ~1.5% hourly volatility → ~11%/day

    results = []
    random.seed(42)

    for sim in range(n_simulations):
        price = 100.0
        entry_price = price
        highest = price
        cum_invested = cfg.base_amount + cfg.base_amount * cfg.fee_pct
        cum_coins = cfg.base_amount / entry_price
        dca_levels_fired = 0
        exited = False
        exit_reason = ""
        profit = 0.0

        # Track which DCA levels triggered
        dca_triggered = [False] * cfg.max_buys

        for t in range(1, periods + 1):
            # Geometric Brownian Motion with mean reversion
            ret = random.gauss(hourly_drift, hourly_vol)
            # Mean reversion toward entry (weak)
            if price < entry_price * 0.9:
                ret += 0.001  # small upward pull when deeply oversold
            elif price > entry_price * 1.15:
                ret -= 0.0005  # slight downward pull when very overbought

            price *= (1 + ret)
            highest = max(highest, price)

            # Check DCA triggers
            for i in range(cfg.max_buys):
                if dca_triggered[i]:
                    continue
                cum_drop_needed = sum(cfg.drop_pct * (cfg.step_multiplier ** j) for j in range(i + 1))
                trigger_price = entry_price * (1 - cum_drop_needed)
                if price <= trigger_price:
                    amount = cfg.dca_amount * (cfg.scale_factor ** i)
                    fee = amount * cfg.fee_pct
                    cum_invested += amount + fee
                    cum_coins += amount / price
                    dca_triggered[i] = True
                    dca_levels_fired += 1

            # Check trailing exit (from average entry)
            avg_entry = cum_invested / cum_coins if cum_coins > 0 else entry_price
            profit_pct = (price / avg_entry - 1)

            if profit_pct >= cfg.trailing_activation:
                # Determine trail %
                trail = cfg.default_trailing
                for threshold, tighter in cfg.stepped_trailing:
                    if profit_pct >= threshold:
                        trail = tighter

                # Track highest since activation
                stop_price = highest * (1 - trail)
                if price <= stop_price and profit_pct > 0:
                    sell_fee = price * cum_coins * cfg.fee_pct
                    net = (price * cum_coins) - sell_fee
                    profit = net - cum_invested
                    exited = True
                    exit_reason = "trailing"
                    break

            # Check partial TP (simplified: check if any TP target hit)
            for idx, target in enumerate(cfg.tp_targets):
                if profit_pct >= target:
                    pass  # In real bot, partial sell; for Monte Carlo we just track trailing exit

        if not exited:
            # End of simulation — mark to market
            sell_fee = price * cum_coins * cfg.fee_pct
            net = (price * cum_coins) - sell_fee
            profit = net - cum_invested
            exit_reason = "open"

        results.append({
            'profit': profit,
            'invested': cum_invested,
            'dca_levels': dca_levels_fired,
            'exit_reason': exit_reason,
            'exit_price': price,
            'roi_pct': (profit / cum_invested * 100) if cum_invested > 0 else 0,
        })

    # ── Analyze results ──
    profits = [r['profit'] for r in results]
    rois = [r['roi_pct'] for r in results]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p <= 0]

    trailing_exits = [r for r in results if r['exit_reason'] == 'trailing']
    open_exits = [r for r in results if r['exit_reason'] == 'open']

    avg_dca = sum(r['dca_levels'] for r in results) / len(results)
    avg_invested = sum(r['invested'] for r in results) / len(results)

    # Percentiles
    profits_sorted = sorted(profits)
    p5 = profits_sorted[int(len(profits_sorted) * 0.05)]
    p25 = profits_sorted[int(len(profits_sorted) * 0.25)]
    p50 = profits_sorted[int(len(profits_sorted) * 0.50)]
    p75 = profits_sorted[int(len(profits_sorted) * 0.75)]
    p95 = profits_sorted[int(len(profits_sorted) * 0.95)]

    # Max drawdown (worst single-trade loss)
    worst = min(profits)

    print(f"\n  ═══ RESULTATEN ═══")
    print(f"  Simulaties:          {n_simulations}")
    print(f"  Tijdshorizon:        {periods}h ({periods/24:.0f} dagen)")
    print(f"  Win rate:            {len(wins)/len(profits)*100:.1f}%")
    print(f"  Trailing exits:      {len(trailing_exits)} ({len(trailing_exits)/len(results)*100:.1f}%)")
    print(f"  Nog open na {periods}h:   {len(open_exits)} ({len(open_exits)/len(results)*100:.1f}%)")
    print(f"  Gem. DCA levels:     {avg_dca:.1f}")
    print(f"  Gem. geïnvesteerd:   €{avg_invested:.2f}")
    print(f"")
    print(f"  ═══ P&L DISTRIBUTIE ═══")
    print(f"  Gemiddeld:           €{sum(profits)/len(profits):+.2f}")
    print(f"  Mediaan:             €{p50:+.2f}")
    print(f"   5e percentiel:      €{p5:+.2f}  (worst 5%)")
    print(f"  25e percentiel:      €{p25:+.2f}")
    print(f"  75e percentiel:      €{p75:+.2f}")
    print(f"  95e percentiel:      €{p95:+.2f}  (best 5%)")
    print(f"  Slechtste trade:     €{worst:+.2f}")
    print(f"  Beste trade:         €{max(profits):+.2f}")
    print(f"")
    print(f"  ═══ ROI DISTRIBUTIE ═══")
    rois_sorted = sorted(rois)
    print(f"  Gemiddeld ROI:       {sum(rois)/len(rois):+.2f}%")
    print(f"  Mediaan ROI:         {rois_sorted[len(rois)//2]:+.2f}%")
    print(f"  Worst 5% ROI:        {rois_sorted[int(len(rois)*0.05)]:+.2f}%")
    print(f"  Best 5% ROI:         {rois_sorted[int(len(rois)*0.95)]:+.2f}%")

    # DCA level distribution
    print(f"\n  ═══ DCA LEVEL VERDELING ═══")
    dca_hist = {}
    for r in results:
        lvl = r['dca_levels']
        dca_hist[lvl] = dca_hist.get(lvl, 0) + 1
    for lvl in sorted(dca_hist.keys()):
        pct = dca_hist[lvl] / len(results) * 100
        bar = "█" * int(pct / 2)
        print(f"  DCA {lvl}: {dca_hist[lvl]:>5} ({pct:>5.1f}%) {bar}")

    return results


# ═══════════════════════════ HISTORICAL REPLAY ═════════════════════════

def historical_replay(market: str, days: int, cfg: DCAConfig):
    """Replay DCA strategy on real historical data from Bitvavo."""
    print(f"\n╔═══════════════════════════════════════════════════════════════════════════════╗")
    print(f"║           HISTORISCHE REPLAY — {market:<10} {days}d                            ║")
    print(f"╚═══════════════════════════════════════════════════════════════════════════════╝")

    try:
        from scripts.backtest_engine import fetch_candles
        candles = fetch_candles(market, "1h", days)
    except Exception as e:
        print(f"  FOUT: Kon geen historische data laden: {e}")
        print(f"  Tip: Zorg dat Bitvavo API keys geconfigureerd zijn.")
        return None

    if len(candles) < 100:
        print(f"  Te weinig candles ({len(candles)}), minimaal 100 nodig.")
        return None

    # Simulate multiple trades
    trades = []
    position = None
    cooldown = 0

    for i in range(50, len(candles)):
        price = float(candles[i][4])  # close
        ts = float(candles[i][0])

        if cooldown > 0:
            cooldown -= 1
            continue

        # Entry: simple — if no position, enter
        if position is None:
            entry_price = price
            cum_invested = cfg.base_amount + cfg.base_amount * cfg.fee_pct
            cum_coins = cfg.base_amount / price
            highest = price
            dca_triggered = [False] * cfg.max_buys
            dca_count = 0
            position = {'entry_price': entry_price, 'entry_ts': ts, 'entry_bar': i}
            continue

        # Update tracking
        highest = max(highest, price)

        # Check DCA
        for j in range(cfg.max_buys):
            if dca_triggered[j]:
                continue
            cum_drop = sum(cfg.drop_pct * (cfg.step_multiplier ** k) for k in range(j + 1))
            trigger_price = entry_price * (1 - cum_drop)
            if price <= trigger_price:
                amount = cfg.dca_amount * (cfg.scale_factor ** j)
                fee = amount * cfg.fee_pct
                cum_invested += amount + fee
                cum_coins += amount / price
                dca_triggered[j] = True
                dca_count += 1

        # Check exit
        avg_entry = cum_invested / cum_coins if cum_coins > 0 else entry_price
        profit_pct = (price / avg_entry - 1)

        if profit_pct >= cfg.trailing_activation:
            trail = cfg.default_trailing
            for threshold, tighter in cfg.stepped_trailing:
                if profit_pct >= threshold:
                    trail = tighter

            stop_price = highest * (1 - trail)
            if price <= stop_price:
                sell_fee = price * cum_coins * cfg.fee_pct
                net = (price * cum_coins) - sell_fee
                profit = net - cum_invested
                trades.append({
                    'profit': round(profit, 2),
                    'invested': round(cum_invested, 2),
                    'dca_levels': dca_count,
                    'hold_bars': i - position['entry_bar'],
                    'roi_pct': round(profit / cum_invested * 100, 2),
                })
                position = None
                cooldown = 6  # Wait 6 hours before next entry

    # Close open position
    if position is not None:
        price = float(candles[-1][4])
        sell_fee = price * cum_coins * cfg.fee_pct
        net = (price * cum_coins) - sell_fee
        profit = net - cum_invested
        trades.append({
            'profit': round(profit, 2),
            'invested': round(cum_invested, 2),
            'dca_levels': dca_count,
            'hold_bars': len(candles) - position['entry_bar'],
            'roi_pct': round(profit / cum_invested * 100, 2),
        })

    if not trades:
        print("  Geen trades gegenereerd.")
        return None

    wins = [t for t in trades if t['profit'] > 0]
    losses = [t for t in trades if t['profit'] <= 0]
    total_pnl = sum(t['profit'] for t in trades)
    total_invested = sum(t['invested'] for t in trades)

    print(f"\n  ═══ HISTORISCHE RESULTATEN ═══")
    print(f"  Periode:            {days} dagen")
    print(f"  Trades:             {len(trades)}")
    print(f"  Wins:               {len(wins)} ({len(wins)/len(trades)*100:.0f}%)")
    print(f"  Losses:             {len(losses)} ({len(losses)/len(trades)*100:.0f}%)")
    print(f"  Totale P&L:         €{total_pnl:+.2f}")
    print(f"  Totaal invested:    €{total_invested:.2f}")
    print(f"  ROI:                {total_pnl/total_invested*100:+.2f}%" if total_invested > 0 else "  ROI: N/A")
    print(f"  Gem. DCA levels:    {sum(t['dca_levels'] for t in trades)/len(trades):.1f}")
    print(f"  Gem. hold time:     {sum(t['hold_bars'] for t in trades)/len(trades):.0f}h")

    if wins:
        print(f"  Gem. win:           €{sum(t['profit'] for t in wins)/len(wins):+.2f}")
    if losses:
        print(f"  Gem. loss:          €{sum(t['profit'] for t in losses)/len(losses):+.2f}")

    return trades


# ═══════════════════════════ CONFIG VALIDATION ═════════════════════════

def validate_config(cfg: DCAConfig, budget: float = 346.15):
    """Validate the config is mathematically sound."""
    print("\n╔═══════════════════════════════════════════════════════════════════════════════╗")
    print("║                       CONFIG VALIDATIE                                      ║")
    print("╚═══════════════════════════════════════════════════════════════════════════════╝")

    ladder = compute_ladder(cfg)
    per_trade = ladder[-1]['cum_invested']
    total_needed = per_trade * cfg.max_trades
    max_drop = ladder[-1]['drop_pct']

    checks = []

    # 1. Budget check
    ok = total_needed <= budget
    checks.append(('Budget past', ok,
                    f"€{total_needed:.2f} nodig vs €{budget:.2f} beschikbaar ({total_needed/budget*100:.0f}%)"))

    # 2. Scale factor ≤ 1 (decreasing amounts)
    ok = cfg.scale_factor <= 1.0
    checks.append(('DCA bedragen dalen', ok,
                    f"scale={cfg.scale_factor} {'✓ dalend' if ok else '✗ STIJGEND — verhoogt risico!'}"))

    # 3. Minimum DCA amount > €5 (Bitvavo minimum)
    min_dca = cfg.dca_amount * (cfg.scale_factor ** (cfg.max_buys - 1))
    ok = min_dca >= 5.0
    checks.append(('Min DCA ≥ €5', ok,
                    f"kleinste DCA = €{min_dca:.2f} {'✓' if ok else '✗ onder Bitvavo minimum'}"))

    # 4. Break-even bounce realistisch (< 10% van bodem)
    be_bounce = (ladder[-1]['breakeven_price'] / ladder[-1]['price'] - 1) * 100
    ok = be_bounce < 10.0
    checks.append(('Break-even bounce < 10%', ok,
                    f"nodig: {be_bounce:.2f}% {'✓ realistisch' if ok else '✗ te hoog'}"))

    # 5. Max drawdown verdraagbaar
    ok = max_drop <= 25.0
    checks.append(('Max drawdown ≤ 25%', ok,
                    f"{max_drop:.1f}% {'✓' if ok else '✗ te groot risico'}"))

    # 6. Trailing activation < eerste TP target
    ok = cfg.trailing_activation < cfg.tp_targets[0]
    checks.append(('Trail activatie < TP1', ok,
                    f"{cfg.trailing_activation*100:.1f}% < {cfg.tp_targets[0]*100:.1f}% {'✓' if ok else '✗'}"))

    # 7. Fee impact
    total_fees = sum(r['fee'] for r in ladder)
    fee_pct = total_fees / per_trade * 100
    ok = fee_pct < 1.0
    checks.append(('Fees < 1% van investering', ok,
                    f"totale fees = €{total_fees:.2f} ({fee_pct:.2f}%)"))

    print()
    all_ok = True
    for name, ok, detail in checks:
        status = "✓ PASS" if ok else "✗ FAIL"
        print(f"  [{status}] {name}: {detail}")
        if not ok:
            all_ok = False

    print()
    if all_ok:
        print("  ══ ALLE CHECKS GESLAAGD — Config is valide ══")
    else:
        print("  ══ WAARSCHUWING: Sommige checks gefaald — review nodig ══")

    return all_ok


# ═══════════════════════════ MAIN ═════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Cascading DCA Simulator")
    parser.add_argument("--historical", type=str, default=None, help="Market for historical replay (e.g. BTC-EUR)")
    parser.add_argument("--days", type=int, default=90, help="Days for historical replay")
    parser.add_argument("--mc-sims", type=int, default=10000, help="Monte Carlo simulations")
    parser.add_argument("--mc-hours", type=int, default=720, help="Monte Carlo hours per sim")
    parser.add_argument("--budget", type=float, default=346.15, help="Available budget €")
    args = parser.parse_args()

    print("=" * 80)
    print("  CASCADING DCA STRATEGY SIMULATOR v1.0")
    print("=" * 80)

    cfg = load_from_bot_config()

    print(f"\n  Config geladen:")
    print(f"    BASE_AMOUNT_EUR:      €{cfg.base_amount}")
    print(f"    DCA_AMOUNT_EUR:       €{cfg.dca_amount}")
    print(f"    DCA_SIZE_MULTIPLIER:  {cfg.scale_factor}")
    print(f"    DCA_MAX_BUYS:         {cfg.max_buys}")
    print(f"    DCA_DROP_PCT:         {cfg.drop_pct*100:.1f}%")
    print(f"    DCA_STEP_MULTIPLIER:  {cfg.step_multiplier}")
    print(f"    TRAILING_ACTIVATION:  {cfg.trailing_activation*100:.1f}%")
    print(f"    DEFAULT_TRAILING:     {cfg.default_trailing*100:.1f}%")
    print(f"    TP_TARGETS:           {[f'{t*100:.0f}%' for t in cfg.tp_targets]}")
    print(f"    MAX_OPEN_TRADES:      {cfg.max_trades}")

    # 1. Ladder
    ladder = compute_ladder(cfg)
    print_ladder(ladder, cfg)

    # 2. Config validation
    validate_config(cfg, budget=args.budget)

    # 3. Scenario analysis
    scenario_analysis(cfg)

    # 4. Trailing exit table
    trailing_exit_table(cfg)

    # 5. Monte Carlo
    monte_carlo_simulation(cfg, n_simulations=args.mc_sims, periods=args.mc_hours)

    # 6. Historical replay (optional)
    if args.historical:
        historical_replay(args.historical, args.days, cfg)

    print("\n" + "=" * 80)
    print("  SIMULATIE VOLTOOID")
    print("=" * 80)


if __name__ == "__main__":
    main()
