import os
import sys
import json
from dotenv import load_dotenv

from modules.bitvavo_client import get_bitvavo, inspect_client_methods

load_dotenv()
bv = get_bitvavo()
if not bv:
    print('Bitvavo client kon niet worden gemaakt (controleer API keys).')
    sys.exit(1)

def try_call(client, name, params=None):
    func = getattr(client, name, None)
    if not callable(func):
        return (False, f'No attribute {name}')
    try:
        if params is None:
            return (True, func())
        return (True, func(params))
    except TypeError:
        # try calling without params
        try:
            return (True, func())
        except Exception as e:
            return (False, str(e))
    except Exception as e:
        return (False, str(e))
import os
import sys
import json
from dotenv import load_dotenv

from modules.bitvavo_client import get_bitvavo, inspect_client_methods

load_dotenv()
bv = get_bitvavo()
if not bv:
    print('Bitvavo client kon niet worden gemaakt (controleer API keys).')
    sys.exit(1)

def try_call(client, name, params=None):
    func = getattr(client, name, None)
    if not callable(func):
        return (False, f'No attribute {name}')
    try:
        if params is None:
            return (True, func())
        return (True, func(params))
    except TypeError:
        # try calling without params
        try:
            return (True, func())
        except Exception as e:
            return (False, str(e))
    except Exception as e:
        return (False, str(e))

print('Inspecting Bitvavo client...')
try:
    info = inspect_client_methods(bv)
    print(json.dumps(info, indent=2))
except Exception as e:
    print('Failed to inspect client methods:', e)

print('\nFetching balances...')
balance_candidates = ['balance', 'balances', 'getBalances', 'get_balance']
found = False
for cand in balance_candidates:
    ok, res = try_call(bv, cand, {})
    if ok:
        print(f'Balances (via {cand}):')
        try:
            print(json.dumps(res, indent=2))
        except Exception:
            print(res)
        found = True
        break
    else:
        print(f'Tried {cand}: {res}')
if not found:
    print('No balance method succeeded.')

print('\nFetching open orders (first 200)...')
order_candidates = ['orders', 'getOrders', 'get_orders', 'openOrders', 'getOpenOrders']
found = False
for cand in order_candidates:
    ok, res = try_call(bv, cand, {})
    if ok:
        print(f'Open orders (via {cand}):')
        try:
            print(json.dumps(res, indent=2))
        except Exception:
            print(res)
        found = True
        break
    else:
        print(f'Tried {cand}: {res}')

if not found:
    # Try a generic POST if provided by client
    post = getattr(bv, 'post', None)
    if callable(post):
        try:
            print('Trying post(/v2/orders)')
            res = post('/v2/orders', {'limit': 200})
            print('Open orders (via post):')
            try:
                print(json.dumps(res, indent=2))
            except Exception:
                print(res)
            found = True
        except Exception as e:
            print('post(/v2/orders) failed:', e)

if not found:
    print('No orders method succeeded.')

print('\nFinished diagnostics.')
