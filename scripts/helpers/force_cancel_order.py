from python_bitvavo_api.bitvavo import Bitvavo
import json

bitvavo = Bitvavo()

print("\n=== CANCEL OP-EUR ORDER ===")
order_id = "00000000-0000-0516-0100-0003ebe5b278"
market = "OP-EUR"

print(f"Cancelling order {order_id} on {market}...")

try:
    # Try simple cancel
    response = bitvavo.cancelOrder(market, order_id)
    print("Response:", json.dumps(response, indent=2))
    
    if 'error' not in response:
        print("\n✅ Order successfully cancelled!")
    else:
        print(f"\n❌ Error: {response['error']}")
except Exception as e:
    print(f"\n❌ Exception: {e}")

print("\n=== CHECK REMAINING ORDERS ===")
orders = bitvavo.ordersOpen({})
print(f"Open orders: {len(orders) if isinstance(orders, list) else 'error'}")
