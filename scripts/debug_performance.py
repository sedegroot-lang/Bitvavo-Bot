"""Check trade_log data for dashboard debugging"""
import json
import time
from pathlib import Path

trade_log_path = Path("C:/Users/Sedeg/OneDrive/Dokumente/Bitvavo Bot/data/trade_log.json")
data = json.load(open(trade_log_path, encoding='utf-8'))

print("=" * 80)
print("TRADE LOG DATA CHECK")
print("=" * 80)

# Open trades
open_trades = data.get('open', {})
print(f"\n📊 OPEN TRADES: {len(open_trades)}")
for market, trade in open_trades.items():
    invested = trade.get('invested_eur', 0)
    initial = trade.get('initial_invested_eur', invested)
    total = trade.get('total_invested_eur', invested)
    amount = trade.get('amount', 0)
    buy_price = trade.get('buy_price', 0)
    current_value = amount * buy_price  # Simplified - should use current price
    unrealized = current_value - total
    
    print(f"\n  {market}:")
    print(f"    initial_invested_eur: €{initial:.2f}")
    print(f"    total_invested_eur: €{total:.2f}")
    print(f"    invested_eur (avg): €{invested:.2f}")
    print(f"    amount: {amount:.4f}")
    print(f"    buy_price: €{buy_price:.8f}")
    print(f"    value (at buy price): €{current_value:.2f}")
    print(f"    unrealized P/L: €{unrealized:.2f}")

# Closed trades
closed_trades = data.get('closed', [])
print(f"\n📕 CLOSED TRADES: {len(closed_trades)} total")

# Calculate stats
total_profit_closed = sum(t.get('profit', 0) for t in closed_trades)
wins = [t for t in closed_trades if t.get('profit', 0) > 0]
losses = [t for t in closed_trades if t.get('profit', 0) < 0]
win_rate = (len(wins) / len(closed_trades) * 100) if closed_trades else 0

print(f"\n📈 STATS:")
print(f"  Total realized P/L: €{total_profit_closed:.2f}")
print(f"  Wins: {len(wins)} ({win_rate:.1f}%)")
print(f"  Losses: {len(losses)}")
print(f"  Total trades: {len(closed_trades)}")

# Last 10 closed
print(f"\n📋 LAATSTE 10 GESLOTEN TRADES:")
for i, trade in enumerate(closed_trades[-10:], 1):
    market = trade.get('market', 'UNKNOWN')
    profit = trade.get('profit', 0)
    timestamp = trade.get('timestamp', 0)
    reason = trade.get('reason', 'unknown')
    invested_calc = trade.get('total_invested_eur', trade.get('initial_invested_eur', 
                    trade.get('buy_price', 0) * trade.get('amount', 0)))
    
    timestr = time.strftime('%Y-%m-%d %H:%M', time.localtime(timestamp))
    print(f"  {i}. {market}: €{profit:.2f} | invested: €{invested_calc:.2f} | {timestr} | {reason}")

# Calculate total invested from closed trades
total_invested_closed = 0
for trade in closed_trades:
    invested = trade.get('total_invested_eur', trade.get('initial_invested_eur', 
                trade.get('buy_price', 0) * trade.get('amount', 0)))
    if invested >= 0.10:  # Skip dust
        total_invested_closed += invested

print(f"\n💰 INVESTED (closed trades only): €{total_invested_closed:.2f}")

# Total with open trades
total_invested_all = total_invested_closed
for market, trade in open_trades.items():
    total = trade.get('total_invested_eur', trade.get('invested_eur', 0))
    total_invested_all += total

print(f"💰 INVESTED (all trades): €{total_invested_all:.2f}")

print("\n" + "=" * 80)
