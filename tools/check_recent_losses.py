#!/usr/bin/env python3
import json
from datetime import datetime
from pathlib import Path

WORKDIR = Path(__file__).resolve().parents[1]
TRADE_LOG = WORKDIR / 'data' / 'trade_log.json'

def analyze_recent_trades(n=20):
    with open(TRADE_LOG, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    closed = data.get('closed', [])
    recent = sorted(closed, key=lambda x: x.get('timestamp', 0), reverse=True)[:n]
    
    print(f'Laatste {n} gesloten trades:\n')
    print(f'{"#":<4} {"Datum/Tijd":<17} {"Market":<12} {"Status":<14} {"Profit (EUR)":<12} {"Reden":<15}')
    print('-' * 90)
    
    losses = []
    wins = []
    breakeven = []
    
    for i, t in enumerate(recent, 1):
        profit = t.get('profit', 0)
        ts = t.get('timestamp', 0)
        dt = datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M') if ts else 'N/A'
        market = t.get('market', 'N/A')
        reason = t.get('reason', 'N/A')
        
        if profit < 0:
            status = '❌ VERLIES'
            losses.append(t)
        elif profit > 0:
            status = '✅ WINST'
            wins.append(t)
        else:
            status = '⚪ BREAKEVEN'
            breakeven.append(t)
        
        print(f'{i:<4} {dt:<17} {market:<12} {status:<14} {profit:>10.4f}   {reason:<15}')
    
    print('\n' + '=' * 90)
    print(f'\nSAMENVATTING:')
    print(f'  Totaal trades:        {len(recent)}')
    print(f'  Winst trades:         {len(wins)} ({len(wins)/len(recent)*100:.1f}%)')
    print(f'  Verlies trades:       {len(losses)} ({len(losses)/len(recent)*100:.1f}%)')
    print(f'  Break-even/removed:   {len(breakeven)} ({len(breakeven)/len(recent)*100:.1f}%)')
    
    if losses:
        total_loss = sum(t.get('profit', 0) for t in losses)
        print(f'\n  Totaal verlies:       {total_loss:.4f} EUR')
        print(f'  Gemiddeld verlies:    {total_loss/len(losses):.4f} EUR')
        
        print(f'\nVERLIES TRADES IN DETAIL:')
        for t in losses:
            dt = datetime.fromtimestamp(t.get('timestamp', 0)).strftime('%Y-%m-%d %H:%M')
            print(f'  • {dt} | {t.get("market", "N/A"):<12} | {t.get("profit", 0):8.4f} EUR | {t.get("reason", "N/A")}')
    
    if wins:
        total_win = sum(t.get('profit', 0) for t in wins)
        print(f'\n  Totaal winst:         {total_win:.4f} EUR')
        print(f'  Gemiddelde winst:     {total_win/len(wins):.4f} EUR')
    
    total_profit = sum(t.get('profit', 0) for t in recent)
    print(f'\n  NETTO P&L (laatste {n}): {total_profit:.4f} EUR')

if __name__ == '__main__':
    analyze_recent_trades(20)
