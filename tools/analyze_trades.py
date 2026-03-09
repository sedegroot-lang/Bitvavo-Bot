#!/usr/bin/env python3
"""Analyze trade performance"""
import json
from collections import Counter

with open('data/trade_archive.json', 'r') as f:
    data = json.load(f)

trades = data['trades']
recent = trades[-50:]

print(f"📊 TRADE ANALYSIS")
print(f"{'='*60}")
print(f"Total trades all-time: {len(trades)}")
print(f"\nLast 50 trades:")

wins = [t for t in recent if t['profit'] > 0]
losses = [t for t in recent if t['profit'] <= 0]

print(f"  ✅ Wins: {len(wins)} ({len(wins)/len(recent)*100:.1f}%)")
print(f"  ❌ Losses: {len(losses)} ({len(losses)/len(recent)*100:.1f}%)")
print(f"  💰 Avg profit per trade: €{sum(t['profit'] for t in recent)/len(recent):.2f}")
print(f"  📈 Total P/L (last 50): €{sum(t['profit'] for t in recent):.2f}")

if wins:
    avg_win = sum(t['profit'] for t in wins) / len(wins)
    print(f"  🎯 Avg win: €{avg_win:.2f}")
if losses:
    avg_loss = sum(t['profit'] for t in losses) / len(losses)
    print(f"  💢 Avg loss: €{avg_loss:.2f}")

if wins and losses:
    profit_factor = abs(sum(t['profit'] for t in wins) / sum(t['profit'] for t in losses))
    print(f"  📊 Profit factor: {profit_factor:.2f}")

print(f"\n📋 Close reasons (last 50):")
reasons = Counter(t['reason'] for t in recent)
for reason, count in reasons.most_common():
    pct = count/len(recent)*100
    print(f"  {reason}: {count} ({pct:.1f}%)")

print(f"\n🏆 Top 5 profitable markets:")
market_profits = {}
for t in trades:
    market_profits[t['market']] = market_profits.get(t['market'], 0) + t['profit']
for market, profit in sorted(market_profits.items(), key=lambda x: x[1], reverse=True)[:5]:
    print(f"  {market}: €{profit:.2f}")

print(f"\n💸 Top 5 loss-making markets:")
for market, profit in sorted(market_profits.items(), key=lambda x: x[1])[:5]:
    print(f"  {market}: €{profit:.2f}")

print(f"\n📉 Recent losses detail:")
for t in [t for t in recent if t['profit'] < 0][-10:]:
    print(f"  {t['market']}: €{t['profit']:.2f} ({t.get('profit_pct', 0)*100:.1f}%) - {t['reason']}")
