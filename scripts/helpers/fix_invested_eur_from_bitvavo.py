"""
Fix invested_eur in trade_log.json using REAL Bitvavo data
Previous fix was WRONG - used dca_buys count but DCAs failed
"""
import sys
import os
sys.path.insert(0, os.path.abspath('.'))

import json
from python_bitvavo_api.bitvavo import Bitvavo
from dotenv import load_dotenv
from datetime import datetime

# Load environment
load_dotenv()

# Get API credentials
api_key = os.getenv('BITVAVO_API_KEY')
api_secret = os.getenv('BITVAVO_API_SECRET')

if not api_key or not api_secret:
    print("ERROR: No API credentials")
    sys.exit(1)

# Initialize Bitvavo
api = Bitvavo({
    'APIKEY': api_key,
    'APISECRET': api_secret,
})

# Markets to fix based on user report
fixes = {
    'XRP-EUR': 11.64,  # User says €11.64
    'LINK-EUR': 11.45,  # User says €11.45
    'APT-EUR': 25.00,  # User says €25.00
    # FET not mentioned, use Bitvavo data: €15.00
}

print('\n' + '='*70)
print('FIXING INVESTED_EUR FROM BITVAVO')
print('='*70)

# Load trade_log
with open('data/trade_log.json', 'r') as f:
    trade_log = json.load(f)

# Backup first
backup_path = f'data/trade_log.json.backup_{int(datetime.now().timestamp())}'
with open(backup_path, 'w') as f:
    json.dump(trade_log, f, indent=2)
print(f'\n✅ Backup created: {backup_path}')

# Get real invested EUR from Bitvavo for ALL markets
print('\n📊 Getting REAL invested_eur from Bitvavo...')
real_invested = {}

for market in trade_log.get('open', {}).keys():
    try:
        response = api.trades(market, {})
        if isinstance(response, dict) and 'error' in response:
            continue
        fills = response if isinstance(response, list) else []
        
        # Calculate using FIFO accounting
        position_amount = 0.0
        position_cost = 0.0
        
        for fill in sorted(fills, key=lambda f: float(f.get('timestamp', 0))):
            side = fill.get('side', '')
            price = float(fill.get('price', 0))
            amount = float(fill.get('amount', 0))
            fee = float(fill.get('fee', 0))
            fee_currency = fill.get('feeCurrency', '')
            
            if side == 'buy':
                eur_cost = price * amount
                if fee_currency == 'EUR':
                    eur_cost += fee
                position_cost += eur_cost
                position_amount += amount
            elif side == 'sell':
                if position_amount > 0:
                    avg_cost_per_unit = position_cost / position_amount
                    sold_amount = min(amount, position_amount)
                    position_amount -= sold_amount
                    position_cost -= avg_cost_per_unit * sold_amount
        
        real_invested[market] = round(position_cost, 2)
    except:
        pass

print('\n📋 Comparison:')
print(f"{'Market':<15} {'Current €':<12} {'Bitvavo €':<12} {'User Says €':<12} {'Action':<15}")
print('-' * 70)

updates = {}
for market, trade in trade_log.get('open', {}).items():
    current = trade.get('invested_eur', 0.0)
    bitvavo = real_invested.get(market, current)
    user_says = fixes.get(market, None)
    
    # Priority: User reported value > Bitvavo calculated
    final = user_says if user_says is not None else bitvavo
    
    action = '✅ OK' if abs(current - final) < 0.01 else f'🔧 Fix: {current:.2f} → {final:.2f}'
    
    print(f"{market:<15} {current:<12.2f} {bitvavo:<12.2f} {user_says if user_says else '-':<12} {action:<15}")
    
    if abs(current - final) >= 0.01:
        updates[market] = final

# Apply fixes
if updates:
    print(f'\n🔧 Updating {len(updates)} trades...')
    for market, new_invested in updates.items():
        trade_log['open'][market]['invested_eur'] = new_invested
    
    # Save
    with open('data/trade_log.json', 'w') as f:
        json.dump(trade_log, f, indent=2)
    
    print(f'\n✅ Updated {len(updates)} trades in trade_log.json')
    print(f'✅ Backup: {backup_path}')
else:
    print('\n✅ No updates needed - all values correct')

print('\n' + '='*70)
