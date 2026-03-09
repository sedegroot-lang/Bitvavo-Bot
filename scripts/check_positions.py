#!/usr/bin/env python3
"""Check actual Bitvavo positions and calculate correct invested amounts."""
import os
import json
from datetime import datetime
from dotenv import load_dotenv
from pathlib import Path

# Load environment
load_dotenv()

from python_bitvavo_api.bitvavo import Bitvavo

bitvavo = Bitvavo({
    'APIKEY': os.getenv('BITVAVO_API_KEY'),
    'APISECRET': os.getenv('BITVAVO_API_SECRET')
})

def analyze_position(market: str) -> dict:
    """Calculate correct invested amount for a position."""
    symbol = market.split('-')[0]
    
    # Get current balance
    balance = bitvavo.balance({})
    current_amount = 0
    for coin in balance:
        if coin['symbol'] == symbol:
            current_amount = float(coin.get('available', 0) or 0) + float(coin.get('inOrder', 0) or 0)
            break
    
    if current_amount < 0.001:
        return {'market': market, 'status': 'no_position'}
    
    # Get trade history
    trades = bitvavo.trades(market, {'limit': 50})
    
    # Sort by timestamp (oldest first)
    trades.sort(key=lambda x: int(x['timestamp']))
    
    # Calculate running position
    running_amount = 0
    running_invested = 0
    total_bought = 0
    total_sold = 0
    
    for t in trades:
        side = t['side']
        amount = float(t['amount'])
        price = float(t['price'])
        value = amount * price
        ts = datetime.fromtimestamp(int(t['timestamp'])/1000).strftime('%d-%m %H:%M')
        
        if side == 'buy':
            running_amount += amount
            running_invested += value
            total_bought += value
        else:
            # Proportionally reduce invested
            if running_amount > 0:
                sell_ratio = amount / running_amount
                invested_reduction = running_invested * sell_ratio
                running_invested -= invested_reduction
                running_amount -= amount
                total_sold += value
        
        # Check if we've reached current position
        if abs(running_amount - current_amount) < 0.01:
            break
    
    return {
        'market': market,
        'current_amount': round(current_amount, 8),
        'invested_eur': round(running_invested, 2),
        'total_bought': round(total_bought, 2),
        'total_sold': round(total_sold, 2),
        'status': 'calculated'
    }

def main():
    print("=" * 60)
    print("BITVAVO POSITIE ANALYSE - CORRECTE INVESTED BEDRAGEN")
    print("=" * 60)
    print()
    
    # Analyze each position
    for market in ['APT-EUR', 'BREV-EUR', 'FORTH-EUR']:
        result = analyze_position(market)
        print(f"\n{market}:")
        if result['status'] == 'no_position':
            print("  Geen positie")
        else:
            print(f"  Huidig amount: {result['current_amount']}")
            print(f"  CORRECT invested_eur: €{result['invested_eur']}")
            print(f"  Totaal gekocht: €{result['total_bought']}")
            print(f"  Totaal verkocht: €{result['total_sold']}")
    
    print("\n" + "=" * 60)
    
    # Now load trade_log and compare
    trade_log_path = Path('data/trade_log.json')
    with open(trade_log_path) as f:
        trade_log = json.load(f)
    
    print("\nVERGELIJKING MET TRADE_LOG.JSON:")
    print("-" * 60)
    
    corrections_needed = []
    
    for market in ['APT-EUR', 'BREV-EUR', 'FORTH-EUR']:
        result = analyze_position(market)
        if result['status'] == 'no_position':
            continue
            
        if market in trade_log['open']:
            current = trade_log['open'][market]
            log_invested = current.get('invested_eur', 0)
            correct_invested = result['invested_eur']
            diff = abs(log_invested - correct_invested)
            
            print(f"\n{market}:")
            print(f"  trade_log invested_eur: €{log_invested:.2f}")
            print(f"  CORRECT invested_eur:   €{correct_invested:.2f}")
            if diff > 0.50:
                print(f"  ❌ VERSCHIL: €{diff:.2f} - CORRECTIE NODIG!")
                corrections_needed.append({
                    'market': market,
                    'current': log_invested,
                    'correct': correct_invested
                })
            else:
                print(f"  ✅ OK (verschil €{diff:.2f})")
    
    if corrections_needed:
        print("\n" + "=" * 60)
        print("CORRECTIES NODIG:")
        for c in corrections_needed:
            print(f"  {c['market']}: €{c['current']:.2f} → €{c['correct']:.2f}")

if __name__ == '__main__':
    main()
