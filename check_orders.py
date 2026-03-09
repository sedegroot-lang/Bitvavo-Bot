#!/usr/bin/env python3
"""Check and cancel orphaned open orders"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.bitvavo_client import get_bitvavo

def check_open_orders():
    print("Checking open orders on Bitvavo...")
    bitvavo = get_bitvavo()
    if not bitvavo:
        print("[X] Could not connect to Bitvavo")
        return
    
    orders = bitvavo.ordersOpen({})
    print(f"\nFound {len(orders)} open order(s):\n")
    
    for order in orders:
        print(f"  Market: {order.get('market')}")
        print(f"  Side: {order.get('side')}")
        print(f"  Type: {order.get('orderType')}")
        print(f"  Amount: {order.get('amount')}")
        print(f"  Price: {order.get('price')}")
        print(f"  OrderId: {order.get('orderId')}")
        print("-" * 40)
        
        # Ask to cancel
        answer = input(f"Cancel this order? (y/n): ")
        if answer.lower() == 'y':
            result = bitvavo.cancelOrder(order.get('market'), order.get('orderId'))
            print(f"  Cancelled: {result}")
        print()

if __name__ == "__main__":
    check_open_orders()
