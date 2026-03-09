from python_bitvavo_api.bitvavo import Bitvavo

bitvavo = Bitvavo()

print("\n=== OPEN POSITIONS ===")
balances = bitvavo.balance({})
print(f"Debug: balances type = {type(balances)}")
if isinstance(balances, dict):
    balances = [balances]
crypto = [b for b in balances if isinstance(b, dict) and float(b.get('available', 0)) > 0.01 and b.get('symbol') != 'EUR']

if crypto:
    for c in crypto:
        symbol = c['symbol']
        amount = float(c['available'])
        try:
            ticker = bitvavo.tickerPrice({'market': f"{symbol}-EUR"})
            price = float(ticker['price'])
            value_eur = amount * price
            print(f"  {symbol}: {amount:.4f} (≈€{value_eur:.2f})")
        except:
            print(f"  {symbol}: {amount:.4f}")
else:
    print("  Geen crypto positions")

print("\n=== OPEN ORDERS ===")
orders = bitvavo.ordersOpen({})
print(f"Debug: orders type = {type(orders)}")
if isinstance(orders, dict):
    print(f"  Error: {orders.get('error', 'Unknown')}")
elif isinstance(orders, list) and len(orders) > 0:
    for i, o in enumerate(orders):
        if i >= 10:
            break
        side = o.get('side', '?').upper()
        market = o.get('market', '?')
        amount = o.get('amount', '?')
        price = o.get('price', 'market')
        print(f"  {market}: {side} {amount} @ €{price}")
    if len(orders) > 10:
        print(f"  ... en {len(orders) - 10} meer")
    print(f"\nTotaal orders: {len(orders)}")
else:
    print("  Geen open orders")
    print(f"\nTotaal orders: 0")
