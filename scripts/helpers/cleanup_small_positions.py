import os
import time

from modules.trade_store import load_snapshot, save_snapshot

TRADE_LOG = 'data/trade_log.json'

moved = []
if not os.path.exists(TRADE_LOG):
    print('trade_log.json not found')
    raise SystemExit(1)

data = load_snapshot(TRADE_LOG)

open_trades = data.get('open', {})
closed = data.get('closed', [])

for m, t in list(open_trades.items()):
    # try to compute current price if present in trade (use highest_price as proxy) else skip
    price = t.get('highest_price') or t.get('buy_price')
    amount = t.get('amount', 0)
    try:
        value = float(price) * float(amount)
    except Exception:
        continue
    if value < 2:
        closed.append({
            'market': m,
            'buy_price': t.get('buy_price', 0),
            'sell_price': 0.0,
            'amount': t.get('amount', 0),
            'profit': 0.0,
            'timestamp': time.time(),
            'reason': 'manual_force_written_off'
        })
        del open_trades[m]
        moved.append((m, value))

# write back
data['open'] = open_trades
# keep closed list capped
closed = closed[-2000:] + []
data['closed'] = closed
save_snapshot(data, TRADE_LOG, indent=2)

print('Moved', len(moved), 'positions:')
for m, v in moved:
    print('-', m, f'({v:.4f} EUR)')
