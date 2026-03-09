from modules.bitvavo_client import get_bitvavo
import json

bitvavo = get_bitvavo()

print("\n=== CANCEL ALL ORDERS VIA MODULE ===")

orders = bitvavo.ordersOpen({})
print(f"Found {len(orders)} open order(s)")

if orders:
    for order in orders:
        order_id = order['orderId']
        market = order['market']
        print(f"\nCancelling {market} order {order_id}...")
        
        # Cancel without extra params
        result = bitvavo.cancelOrder(market, order_id, {})
        
        if 'error' in result:
            print(f"  ❌ Error: {result['error']}")
        else:
            print(f"  ✅ Cancelled!")
            
print("\n=== VERIFY ===")
remaining = bitvavo.ordersOpen({})
print(f"Remaining orders: {len(remaining)}")

# Check balance
balance = bitvavo.balance({})
if isinstance(balance, list):
    eur = [b for b in balance if b.get('symbol') == 'EUR']
    if eur:
        print(f"\nEUR balance:")
        print(f"  Available: €{eur[0].get('available', 0)}")
        print(f"  In order: €{eur[0].get('inOrder', 0)}")
