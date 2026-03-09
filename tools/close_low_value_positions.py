import os
import json
import time
from decimal import Decimal, ROUND_DOWN
from dotenv import load_dotenv
from python_bitvavo_api.bitvavo import Bitvavo

# Close N lowest-value open positions from trade_log.json by placing market sell orders
# Usage: python tools/close_low_value_positions.py [N]

load_dotenv()

TRADE_LOG = 'data/trade_log.json'
N_DEFAULT = 4

API_KEY = os.getenv('BITVAVO_API_KEY')
API_SECRET = os.getenv('BITVAVO_API_SECRET')
OPERATOR_ID = os.getenv('BITVAVO_OPERATOR_ID') or None
if not API_KEY or not API_SECRET:
    print('ERROR: Missing BITVAVO_API_KEY/SECRET in environment')
    raise SystemExit(1)

bitvavo = Bitvavo({'APIKEY': API_KEY, 'APISECRET': API_SECRET})


def load_trade_log():
    if not os.path.exists(TRADE_LOG):
        return {'open': {}, 'closed': []}
    with open(TRADE_LOG, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_trade_log(data):
    tmp = TRADE_LOG + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, TRADE_LOG)


def get_ticker_price(market):
    try:
        t = bitvavo.tickerPrice({'market': market})
        if isinstance(t, dict) and t.get('price') is not None:
            return float(t['price'])
    except Exception:
        pass
    # fallback to orderbook mid
    try:
        ob = bitvavo.book(market, {'depth': 1})
        ask = float(ob['asks'][0][0]) if ob and ob.get('asks') else None
        bid = float(ob['bids'][0][0]) if ob and ob.get('bids') else None
        if ask is not None and bid is not None:
            return (ask + bid) / 2.0
    except Exception:
        pass
    return None


def get_market_info(market):
    try:
        info = bitvavo.markets({'market': market})
        if isinstance(info, list) and info:
            return info[0]
    except Exception:
        pass
    return None


def normalize_amount(market, amount):
    # Quantize to market step or amountPrecision when available; always enforce <=8 decimals as final guard
    info = get_market_info(market)
    d_amount = Decimal(str(amount))
    quantized = None
    if info:
        try:
            step = info.get('minOrderAmount')
            if step:
                d_step = Decimal(str(step))
                q = (d_amount / d_step).to_integral_value(rounding=ROUND_DOWN) * d_step
                quantized = q.quantize(d_step, rounding=ROUND_DOWN)
        except Exception:
            quantized = None
        if quantized is None:
            try:
                prec = int(info.get('amountPrecision', 8))
                quantized = d_amount.quantize(Decimal('1.' + '0'*prec), rounding=ROUND_DOWN)
            except Exception:
                quantized = None
    if quantized is None:
        # fallback: 8 decimals
        quantized = d_amount.quantize(Decimal('1.00000000'), rounding=ROUND_DOWN)
    # final guard: ensure max 8 decimals
    return float(quantized.quantize(Decimal('1.00000000'), rounding=ROUND_DOWN))


def get_available_base(market):
    base = market.split('-')[0]
    try:
        bals = bitvavo.balance({}) or []
        for b in bals:
            if b.get('symbol') == base:
                return float(b.get('available', 0) or 0)
    except Exception:
        pass
    return 0.0


def is_success(resp: dict) -> bool:
    try:
        if not isinstance(resp, dict):
            return False
        if 'error' in resp or 'errorCode' in resp:
            return False
        return True
    except Exception:
        return False


def close_low_value(n=N_DEFAULT):
    data = load_trade_log()
    open_trades = data.get('open', {}) or {}
    if not open_trades:
        print('No open trades found.')
        return []
    # compute approximate value
    vals = []
    for m, t in open_trades.items():
        amt = float(t.get('amount', 0) or 0)
        buy = float(t.get('buy_price', 0) or 0)
        px = get_ticker_price(m)
        if px is None:
            px = buy
        value = (px or 0.0) * amt
        vals.append((value, m, amt, buy, px))
    # sort ascending by value
    vals.sort(key=lambda x: x[0])
    to_close = vals[:max(0, int(n))]
    print('Planned closures (lowest value first):')
    for v, m, amt, buy, px in to_close:
        print(f" - {m}: value≈{v:.4f} EUR (amt={amt}, last={px})")

    closed = []
    for v, m, amt, buy, last_px in to_close:
        try:
            avail = get_available_base(m)
            if avail <= 0:
                print(f"WARN: No available balance for {m.split('-')[0]}, skipping.")
                continue
            sell_amt = min(avail, amt) * 0.999  # small margin to avoid insufficient
            sell_amt = normalize_amount(m, sell_amt)
            if sell_amt <= 0:
                print(f"WARN: Normalized sell amount is zero for {m}, skipping.")
                continue
            params = {'amount': sell_amt}
            if OPERATOR_ID:
                params['operatorId'] = OPERATOR_ID
            resp = bitvavo.placeOrder(m, 'sell', 'market', params)
            print(f"SELL {m} amount={sell_amt} resp={resp}")
            # if operatorId required or any error, do not mutate trade_log
            if isinstance(resp, dict) and resp.get('errorCode') == 203:
                print("ERROR: operatorId parameter is required by your Bitvavo account. Set BITVAVO_OPERATOR_ID in your .env and retry.")
                break
            if isinstance(resp, dict) and resp.get('errorCode') in (101, 429) and 'decimal' in str(resp.get('error','')).lower():
                # retry tighten to 8 decimals (already), then 6 decimals if needed
                tight = float(Decimal(str(sell_amt)).quantize(Decimal('1.00000000'), rounding=ROUND_DOWN))
                if tight != sell_amt:
                    params['amount'] = tight
                    print(f"Retry {m} with 8-dec amount={tight}")
                    resp = bitvavo.placeOrder(m, 'sell', 'market', params)
                if isinstance(resp, dict) and resp.get('errorCode') in (101, 429) and 'decimal' in str(resp.get('error','')).lower():
                    tighter = float(Decimal(str(sell_amt)).quantize(Decimal('1.000000'), rounding=ROUND_DOWN))
                    params['amount'] = tighter
                    print(f"Retry {m} with 6-dec amount={tighter}")
                    resp = bitvavo.placeOrder(m, 'sell', 'market', params)
            if not is_success(resp):
                print(f"WARN: Sell failed for {m}, not updating trade_log.")
                continue
            # get final price for logging
            px = get_ticker_price(m) or last_px or buy
            profit = (px - buy) * sell_amt
            # update trade log
            if m in open_trades:
                del open_trades[m]
            data['open'] = open_trades
            data.setdefault('closed', []).append({
                'market': m,
                'buy_price': buy,
                'sell_price': px,
                'amount': sell_amt,
                'profit': round(profit, 4),
                'timestamp': time.time(),
                'reason': 'manual_close'
            })
            save_trade_log(data)
            closed.append(m)
        except Exception as e:
            print(f"ERROR closing {m}: {e}")
    return closed


if __name__ == '__main__':
    import sys
    n = N_DEFAULT
    if len(sys.argv) > 1:
        try:
            n = int(sys.argv[1])
        except Exception:
            pass
    res = close_low_value(n)
    print('Closed:', res)
