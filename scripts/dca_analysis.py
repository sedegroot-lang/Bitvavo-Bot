"""Quick DCA analysis script for historical trades."""
import json
from datetime import datetime
from collections import Counter

with open("data/trade_archive.json") as f:
    trades = json.load(f).get("trades", [])

print(f"=== TRADE ARCHIVE ANALYSIS ({len(trades)} trades) ===\n")

# Monthly breakdown
months = {}
for t in trades:
    ts = t.get("timestamp", 0)
    if not ts:
        continue
    m = datetime.fromtimestamp(ts).strftime("%Y-%m")
    if m not in months:
        months[m] = {"count": 0, "pnl": 0.0, "wins": 0, "stops": 0, "tp": 0}
    months[m]["count"] += 1
    p = float(t.get("profit", 0) or 0)
    months[m]["pnl"] += p
    if p > 0:
        months[m]["wins"] += 1
    if t.get("reason") == "stop":
        months[m]["stops"] += 1
    if t.get("reason") == "trailing_tp":
        months[m]["tp"] += 1

print("Month      Trades    P&L       WR%    Stops   TP")
print("-" * 60)
for m in sorted(months):
    d = months[m]
    wr = d["wins"] / d["count"] * 100 if d["count"] else 0
    print(f"{m}   {d['count']:5d}   {d['pnl']:+9.2f}   {wr:5.1f}%   {d['stops']:4d}   {d['tp']:4d}")

# Overall stats
profits = [float(t.get("profit", 0) or 0) for t in trades]
wins_p = [p for p in profits if p > 0]
loss_p = [p for p in profits if p <= 0]
print(f"\nAvg win:  EUR {sum(wins_p)/len(wins_p):.3f}" if wins_p else "")
print(f"Avg loss: EUR {sum(loss_p)/len(loss_p):.3f}" if loss_p else "")
print(f"Profit factor: {sum(wins_p)/abs(sum(loss_p)):.2f}" if loss_p and sum(loss_p) != 0 else "")

# Exit reason P&L
print("\n=== EXIT REASON BREAKDOWN ===")
reasons = Counter(t.get("reason", "?") for t in trades)
for reason, count in reasons.most_common():
    subset = [t for t in trades if t.get("reason") == reason]
    pnl = sum(float(t.get("profit", 0) or 0) for t in subset)
    avg = pnl / count if count else 0
    print(f"  {reason:25s}: {count:4d} trades, EUR {pnl:+9.2f} (avg {avg:+.2f})")

# Hard SL analysis - how much would DCA have saved?
stops = [t for t in trades if t.get("reason") == "stop"]
print(f"\n=== HARD SL TRADES ({len(stops)}) ===")
stop_losses = [float(t.get("profit", 0) or 0) for t in stops]
print(f"Total SL loss: EUR {sum(stop_losses):.2f}")
print(f"Avg SL loss:   EUR {sum(stop_losses)/len(stop_losses):.2f}" if stops else "")

# Check: how many SL trades had price recover above buy?
# (Would DCA have helped?)
recoverable = 0
for t in stops:
    bp = float(t.get("buy_price", 0) or 0)
    sp = float(t.get("sell_price", 0) or 0)
    loss_pct = (sp - bp) / bp if bp > 0 else 0
    # If loss was < 5%, DCA might have saved it
    if -0.05 < loss_pct < 0:
        recoverable += 1
print(f"SL trades with <5% drawdown (DCA-recoverable): {recoverable}/{len(stops)}")

# Flood guard analysis
flood = [t for t in trades if t.get("reason") == "saldo_flood_guard"]
print(f"\n=== FLOOD GUARD EXITS ({len(flood)}) ===")
flood_pnl = sum(float(t.get("profit", 0) or 0) for t in flood)
print(f"Total P&L: EUR {flood_pnl:.2f}")
flood_wins = sum(1 for t in flood if float(t.get("profit", 0) or 0) > 0)
print(f"Win rate:  {flood_wins/len(flood)*100:.1f}%" if flood else "")

# Trailing TP analysis
tp = [t for t in trades if t.get("reason") == "trailing_tp"]
print(f"\n=== TRAILING TP EXITS ({len(tp)}) ===")
tp_pnl = sum(float(t.get("profit", 0) or 0) for t in tp)
tp_wins = sum(1 for t in tp if float(t.get("profit", 0) or 0) > 0)
print(f"Total P&L:  EUR {tp_pnl:.2f}")
print(f"Win rate:   {tp_wins/len(tp)*100:.1f}%" if tp else "")
print(f"Avg profit: EUR {tp_pnl/len(tp):.3f}" if tp else "")

# DCA audit log
try:
    with open("data/dca_audit.log") as f:
        lines = f.readlines()
    print(f"\n=== DCA AUDIT LOG ({len(lines)} entries) ===")
    for line in lines[-10:]:
        print(f"  {line.strip()}")
except FileNotFoundError:
    print("\nNo DCA audit log found")

# Current open trades
try:
    with open("data/trade_log.json") as f:
        tl = json.load(f)
    open_trades = {}
    if isinstance(tl, dict):
        open_trades = tl
    print(f"\n=== OPEN TRADES ({len(open_trades)}) ===")
    for m, t in open_trades.items():
        if isinstance(t, dict):
            bp = float(t.get("buy_price", 0) or 0)
            dca = t.get("dca_buys", 0) or t.get("dca_count", 0) or 0
            invested = float(t.get("invested_eur", 0) or 0)
            print(f"  {m}: buy={bp:.4f}, dca={dca}, invested=EUR {invested:.2f}")
except Exception as e:
    print(f"\nCould not read open trades: {e}")
