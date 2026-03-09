import os
import json
import time
from dotenv import load_dotenv
from python_bitvavo_api.bitvavo import Bitvavo

"""
Heuristic rollback: if recent 'manual_close' entries exist in trade_log but the corresponding base asset is still in balance, move them back to open.
Usage: python tools/rollback_failed_manual_closes.py [max_age_seconds]
Default max_age_seconds: 900 (15 minutes)
Note: this does not guarantee exact amounts, but tries to restore if sell likely failed.
"""

load_dotenv()
API_KEY = os.getenv('BITVAVO_API_KEY')
API_SECRET = os.getenv('BITVAVO_API_SECRET')
bitvavo = Bitvavo({'APIKEY': API_KEY, 'APISECRET': API_SECRET})
TRADE_LOG = 'data/trade_log.json'


def load_trade_log():
    with open(TRADE_LOG, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_trade_log(data):
    tmp = TRADE_LOG + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, TRADE_LOG)


def get_available(symbol: str) -> float:
    bals = bitvavo.balance({}) or []
    for b in bals:
        if b.get('symbol') == symbol:
            try:
                return float(b.get('available', 0) or 0)
            except Exception:
                return 0.0
    return 0.0


def rollback(max_age_seconds=900):
    data = load_trade_log()
    now = time.time()
    closed = data.get('closed', [])
    open_map = data.get('open', {})
    to_restore_idx = []
    for idx in range(len(closed) - 1, -1, -1):
        c = closed[idx]
        if c.get('reason') != 'manual_close':
            continue
        ts = c.get('timestamp', 0)
        if now - ts > max_age_seconds:
            continue
        market = c.get('market')
        symbol = market.split('-')[0]
        avail = get_available(symbol)
        if avail > 0:
            # Likely not sold; restore
            print(f"Restore {market} to open (balance {avail} > 0)")
            open_map[market] = {
                'buy_price': c.get('buy_price', 0.0),
                'highest_price': c.get('buy_price', 0.0),
                'amount': c.get('amount', 0.0),
                'timestamp': ts
            }
            to_restore_idx.append(idx)
    if to_restore_idx:
        for idx in to_restore_idx:
            closed.pop(idx)
        data['open'] = open_map
        data['closed'] = closed
        save_trade_log(data)
        print(f"Restored {len(to_restore_idx)} entries.")
    else:
        print("No recent manual_close entries to restore.")


if __name__ == '__main__':
    import sys
    max_age = 900
    if len(sys.argv) > 1:
        try:
            max_age = int(sys.argv[1])
        except Exception:
            pass
    rollback(max_age)
