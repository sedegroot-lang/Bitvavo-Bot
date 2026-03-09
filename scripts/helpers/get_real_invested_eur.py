"""
Get real invested EUR from Bitvavo for XRP, LINK, APT, FET
"""
import sys
import os
sys.path.insert(0, os.path.abspath('.'))

import json
from python_bitvavo_api.bitvavo import Bitvavo
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get API credentials from environment
api_key = os.getenv('BITVAVO_API_KEY')
api_secret = os.getenv('BITVAVO_API_SECRET')

if not api_key or not api_secret:
    print("ERROR: No API credentials found in .env")
    sys.exit(1)

# Initialize Bitvavo API
api = Bitvavo({
    'APIKEY': api_key,
    'APISECRET': api_secret,
    'RESTURL': 'https://api.bitvavo.com/v2',
    'WSURL': 'wss://ws.bitvavo.com/v2/',
    'ACCESSWINDOW': 10000,
    'DEBUGGING': False
})

print('\n' + '='*70)
print('BITVAVO REAL INVESTED EUR')
print('='*70)

markets = ['XRP-EUR', 'LINK-EUR', 'APT-EUR', 'FET-EUR']

for market in markets:
    try:
        # Get all fills (trades)
        response = api.trades(market, {})
        
        # Handle error response
        if isinstance(response, dict) and 'error' in response:
            print(f'\n{market}: API Error - {response.get("error")}')
            continue
            
        fills = response if isinstance(response, list) else []
        
        # Process fills chronologically
        position_amount = 0.0
        position_cost = 0.0
        buy_count = 0
        sell_count = 0
        
        for fill in sorted(fills, key=lambda f: float(f.get('timestamp', 0))):
            side = fill.get('side', '')
            price = float(fill.get('price', 0))
            amount = float(fill.get('amount', 0))
            fee = float(fill.get('fee', 0))
            fee_currency = fill.get('feeCurrency', '')
            
            if side == 'buy':
                # Add to position
                eur_cost = price * amount
                if fee_currency == 'EUR':
                    eur_cost += fee
                
                position_cost += eur_cost
                position_amount += amount
                buy_count += 1
                
            elif side == 'sell':
                # Reduce position (FIFO accounting)
                if position_amount > 0:
                    avg_cost_per_unit = position_cost / position_amount
                    sold_amount = min(amount, position_amount)
                    
                    position_amount -= sold_amount
                    position_cost -= avg_cost_per_unit * sold_amount
                    sell_count += 1
        
        print(f'\n{market}:')
        print(f'  Buy fills: {buy_count}')
        print(f'  Sell fills: {sell_count}')
        print(f'  Current position: {position_amount:.8f}')
        print(f'  Invested EUR (remaining): €{position_cost:.2f}')
        
    except Exception as e:
        print(f'\n{market}: ERROR - {e}')

print('\n' + '='*70)
