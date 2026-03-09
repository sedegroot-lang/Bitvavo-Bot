"""Sell all assets except BTC, ETH, EUR - direct API with operatorId."""
import sys, time
sys.path.insert(0, '.')

from modules.config import load_config
CONFIG = load_config()

from modules.trading import bitvavo

OPERATOR_ID = CONFIG.get('OPERATOR_ID', '1')

balances = bitvavo.balance({})
to_sell = []
for b in balances:
    sym = b['symbol']
    avail = float(b.get('available', 0))
    if avail > 0 and sym not in ('EUR', 'BTC', 'ETH'):
        to_sell.append((sym, avail))

print(f"Selling {len(to_sell)} assets (operatorId={OPERATOR_ID})...")
results = []

for sym, amount in to_sell:
    market = f"{sym}-EUR"
    try:
        ticker = bitvavo.tickerPrice({'market': market})
        price = float(ticker.get('price', 0)) if isinstance(ticker, dict) else 0
        value_eur = amount * price

        if value_eur < 0.50:
            print(f"  SKIP {sym}: dust (EUR {value_eur:.4f})")
            results.append((sym, 'skip_dust', 0))
            continue

        params = {
            'amount': str(amount),
            'operatorId': OPERATOR_ID,
        }
        resp = bitvavo.placeOrder(market, 'sell', 'market', params)

        if isinstance(resp, dict) and resp.get('orderId'):
            filled = float(resp.get('filledAmountQuote', 0) or 0)
            print(f"  SOLD {sym}: {amount} = EUR {filled:.2f}")
            results.append((sym, 'sold', filled))
        else:
            err = resp if isinstance(resp, dict) else str(resp)
            print(f"  FAIL {sym} (EUR {value_eur:.2f}): {err}")
            results.append((sym, 'fail', 0))
    except Exception as e:
        print(f"  ERROR {sym}: {e}")
        results.append((sym, 'error', 0))

    time.sleep(0.3)

total_eur = sum(r[2] for r in results if r[1] == 'sold')
sold_count = sum(1 for r in results if r[1] == 'sold')
print(f"\nDone: {sold_count}/{len(to_sell)} sold, total EUR {total_eur:.2f}")
