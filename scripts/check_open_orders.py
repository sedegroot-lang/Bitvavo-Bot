#!/usr/bin/env python3
"""Check open orders on Bitvavo."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
from modules.trading import bitvavo

orders = bitvavo.ordersOpen({})

print("=== OPEN ORDERS ===")
print(f"Total: {len(orders)} orders\n")

now = time.time() * 1000  # Current time in ms

for o in orders:
    market = o.get('market', '?')
    side = o.get('side', '?')
    amount = o.get('amount', '?')
    price = o.get('price', 'market')
    status = o.get('status', '?')
    created = o.get('created', 0)
    order_id = o.get('orderId', '?')
    
    # Calculate age
    age_ms = now - created if created else 0
    age_min = age_ms / 60000
    age_str = f"{age_min:.1f} min" if age_min < 60 else f"{age_min/60:.1f} hr"
    
    print(f"{market}: {side.upper()} {amount} @ €{price}")
    print(f"  Status: {status}, Age: {age_str}, OrderId: {order_id}")
    print()
