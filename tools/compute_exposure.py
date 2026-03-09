import json, os, sys
p = os.path.join(os.path.dirname(__file__), '..', 'data', 'trade_log.json')
try:
    with open(p, 'r', encoding='utf-8') as f:
        d = json.load(f)
except Exception as e:
    print('ERROR reading trade_log.json:', e)
    sys.exit(2)
open_dict = d.get('open', {}) or {}
exposure = 0.0
for v in open_dict.values():
    try:
        bp = float(v.get('buy_price', 0) or 0)
        amt = float(v.get('amount', 0) or 0)
        exposure += bp * amt
    except Exception:
        pass
print('exposure_eur', round(exposure, 2))
# also print number of open trades
print('open_trades', len(open_dict))
