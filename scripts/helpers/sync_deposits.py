#!/usr/bin/env python3
"""
Sync Deposits from Bitvavo API
==============================
Updates config/deposits.json with real deposit history from Bitvavo.

Usage:
    python scripts/helpers/sync_deposits.py
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / '.env')

DEPOSITS_FILE = PROJECT_ROOT / 'config' / 'deposits.json'

def sync_deposits():
    """Fetch deposit history from Bitvavo and update deposits.json"""
    from python_bitvavo_api.bitvavo import Bitvavo
    
    api_key = os.getenv('BITVAVO_API_KEY')
    api_secret = os.getenv('BITVAVO_API_SECRET')
    
    if not api_key or not api_secret:
        print("Error: BITVAVO_API_KEY and BITVAVO_API_SECRET must be set in .env")
        return False
    
    api = Bitvavo({'APIKEY': api_key, 'APISECRET': api_secret})
    
    print("Fetching deposit history from Bitvavo...")
    deposits = api.depositHistory({})
    
    if not isinstance(deposits, list):
        print(f"Error: Unexpected response: {deposits}")
        return False
    
    # Filter EUR deposits only
    eur_deposits = []
    total_eur = 0.0
    
    for d in deposits:
        if d.get('symbol') == 'EUR':
            amount = float(d.get('amount', 0))
            timestamp = d.get('timestamp', 0)
            
            # Convert timestamp to date
            try:
                date_str = datetime.fromtimestamp(timestamp / 1000).strftime('%Y-%m-%d')
            except:
                date_str = 'Unknown'
            
            eur_deposits.append({
                'amount': amount,
                'timestamp': timestamp,
                'date': date_str,
                'note': 'Synced from Bitvavo API'
            })
            total_eur += amount
            print(f"  EUR deposit: €{amount:.2f} on {date_str}")
    
    print(f"\nTotal EUR deposited: €{total_eur:.2f}")
    
    # Create deposits data structure
    deposits_data = {
        '_comment': 'Deposit tracking - used to calculate real P/L excluding deposits',
        'total_deposited_eur': round(total_eur, 2),
        'deposits': eur_deposits,
        'last_synced': datetime.now().isoformat() + 'Z',
        'sync_source': 'bitvavo_api'
    }
    
    # Write to file
    with open(DEPOSITS_FILE, 'w', encoding='utf-8') as f:
        json.dump(deposits_data, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Updated {DEPOSITS_FILE}")
    return True


if __name__ == '__main__':
    success = sync_deposits()
    sys.exit(0 if success else 1)
