import json, time
from modules.bitvavo_client import get_bitvavo
from pathlib import Path
import sys
cfg_path=Path('config/bot_config.json')
cfg=json.loads(cfg_path.read_text(encoding='utf-8')) if cfg_path.exists() else {}
BV=get_bitvavo(cfg)
if not BV:
    print('NO_CLIENT')
    sys.exit(0)
# get LINK balance
try:
    bals=BV.balance({})
except Exception as e:
    print('ERROR_BALANCE '+str(e))
    sys.exit(0)
link_bal=0.0
for b in (bals or []):
    if str(b.get('symbol')).upper()=='LINK':
        try:
            link_bal=float(b.get('available') or b.get('balance') or 0)
        except Exception:
            link_bal=0.0
        break
# get ticker price
try:
    t=BV.tickerPrice({'market':'LINK-EUR'})
    if isinstance(t, dict):
        price = float(t.get('price') or 0)
    elif isinstance(t, list) and t:
        price = float(t[0].get('price') or 0)
    else:
        price = 0.0
except Exception as e:
    print('ERROR_TICKER '+str(e))
    price=0.0
now=time.time()
DCA_DROP=float(cfg.get('DCA_DROP_PCT',0.06) or 0.06)
DCA_MAX=int(cfg.get('DCA_MAX_BUYS',2) or 2)
next_price=price*(1-DCA_DROP) if price>0 else 0.0
invested=price*link_bal
out={'market':'LINK-EUR','price':price,'amount':link_bal,'invested_eur':invested,'dca_next_price':next_price,'dca_max':DCA_MAX,'ts':now}
print(json.dumps(out))
