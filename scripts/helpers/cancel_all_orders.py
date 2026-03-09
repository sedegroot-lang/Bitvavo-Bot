from dotenv import load_dotenv
import os, json
from modules.bitvavo_client import get_bitvavo

load_dotenv()
bitvavo = get_bitvavo()
if not bitvavo:
    print('Bitvavo client kon niet worden gemaakt (controleer API keys).')
    raise SystemExit(1)

print('Fetching open orders (ordersOpen)...')
orders = bitvavo.ordersOpen({})
print('Open orders count:', len(orders) if orders else 0)
print(json.dumps(orders, indent=2))

if not orders:
    print('No open orders to cancel.')
else:
    for o in orders:
        order_id = o.get('orderId') or o.get('id') or o.get('orderId')
        market = o.get('market')
        if not order_id or not market:
            print('Skipping order without id/market:', o)
            continue
        print(f'Cancelling {order_id} on {market} ...')
        try:
            # Include operatorId if present in original order
            cancel_params = {}
            if 'operatorId' in o:
                cancel_params['operatorId'] = o['operatorId']
            resp = bitvavo.cancelOrder(market, order_id, cancel_params)
            print('Cancel response:', resp)
        except Exception as e:
            print('Cancel failed for', order_id, e)

print('Done')
