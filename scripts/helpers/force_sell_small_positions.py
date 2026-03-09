import os
import time
from dotenv import load_dotenv
from python_bitvavo_api.bitvavo import Bitvavo
from modules.trade_store import load_snapshot, save_snapshot

load_dotenv()
API_KEY = os.getenv('BITVAVO_API_KEY')
API_SECRET = os.getenv('BITVAVO_API_SECRET')
if not API_KEY or not API_SECRET:
    print('API keys not found in environment; aborting.')
    raise SystemExit(1)

bitvavo = Bitvavo({"APIKEY": API_KEY, "APISECRET": API_SECRET})
OPERATOR_ID = os.getenv('BITVAVO_OPERATOR_ID') or None
if OPERATOR_ID:
    # replace client with operator-aware params
    params = {"APIKEY": API_KEY, "APISECRET": API_SECRET, 'OPERATORID': OPERATOR_ID}
    bitvavo = Bitvavo(params)
TRADE_LOG = 'data/trade_log.json'

if not os.path.exists(TRADE_LOG):
    print('trade_log.json not found')
    raise SystemExit(1)

data = load_snapshot(TRADE_LOG)

open_trades = data.get('open', {})
closed = data.get('closed', [])
moved = []

for m, t in list(open_trades.items()):
    try:
        tick = bitvavo.tickerPrice({'market': m})
        price = float(tick.get('price'))
    except Exception as e:
        print(f'Failed to fetch price for {m}: {e}')
        continue
    amount = float(t.get('amount', 0))
    value = price * amount
    print(f'{m}: price={price}, amount={amount}, value={value:.4f} EUR')
    if value < 2:
        # try sell
        prec = 8
        try:
            info = bitvavo.markets({'market': m})
            if info and isinstance(info, list) and len(info) > 0:
                ap = info[0].get('amountPrecision')
                if ap is not None:
                    prec = int(ap)
        except Exception:
            pass
        amt_str = f"{round(amount, prec)}"
        print(f'Attempting sell {amt_str} {m}...')
        try:
            resp = bitvavo.sell({'market': m, 'amount': amt_str})
            print('Sell response:', resp)
            # consider success when filled or resp contains success
            ok = False
            if isinstance(resp, dict):
                if resp.get('status') == 'filled' or resp.get('success'):
                    ok = True
            if ok:
                closed.append({
                    'market': m,
                    'buy_price': t.get('buy_price', 0),
                    'sell_price': price,
                    'amount': amount,
                    'profit': round((price - t.get('buy_price', 0)) * amount, 4),
                    'timestamp': time.time(),
                    'reason': 'force_sold'
                })
                del open_trades[m]
                moved.append((m, value, 'sold'))
            else:
                closed.append({
                    'market': m,
                    'buy_price': t.get('buy_price', 0),
                    'sell_price': 0.0,
                    'amount': amount,
                    'profit': 0.0,
                    'timestamp': time.time(),
                    'reason': 'manual_force_written_off'
                })
                del open_trades[m]
                moved.append((m, value, 'written_off'))
        except Exception as e:
            print(f'Sell failed for {m}: {e} -> write off')
            closed.append({
                'market': m,
                'buy_price': t.get('buy_price', 0),
                'sell_price': 0.0,
                'amount': amount,
                'profit': 0.0,
                'timestamp': time.time(),
                'reason': 'manual_force_written_off'
            })
            del open_trades[m]
            moved.append((m, value, 'written_off'))

# save
data['open'] = open_trades
# append to closed
closed = closed + data.get('closed', [])
# keep recent
data['closed'] = closed[-2000:]
save_snapshot(data, TRADE_LOG, indent=2)

print('Processed', len(moved), 'positions')
for m, v, status in moved:
    print('-', m, f'({v:.4f} EUR) -> {status}')
