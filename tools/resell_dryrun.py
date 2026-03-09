import json, csv, os, datetime

# This script performs a dry-run plan to re-sell pending_saldo entries where bitvavo_balance is not None.
# It does NOT contact Bitvavo. It prepares a CSV with planned sell amounts and prices for manual review.

SRC = 'data/pending_saldo.json'
OUT_DIR = 'tools'
OUT = os.path.join(OUT_DIR, 'planned_resells_dryrun.csv')

with open(SRC, 'r', encoding='utf-8') as f:
    data = json.load(f)

candidates = []
for e in data:
    # Only consider entries where we have a bitvavo_balance value (not null) or open_trade exists
    if e.get('bitvavo_balance') is not None or e.get('open_trade'):
        ot = e.get('open_trade') or {}
        market = e.get('market')
        amount = e.get('amount') or ot.get('amount')
        # Plan to sell at a conservative price: buy_price * 0.99 if buy_price>0 else use highest_price
        buy_price = e.get('buy_price') or ot.get('buy_price')
        highest = ot.get('highest_price')
        planned_price = None
        if buy_price and buy_price>0:
            planned_price = buy_price * 0.99
        elif highest:
            planned_price = highest * 0.995
        else:
            planned_price = None
        candidates.append({'market':market,'amount':amount,'planned_price':planned_price,'profit':e.get('profit'),'timestamp':e.get('timestamp')})

os.makedirs(OUT_DIR, exist_ok=True)
with open(OUT, 'w', newline='', encoding='utf-8') as csvf:
    w = csv.writer(csvf)
    w.writerow(['market','amount','planned_price','profit','timestamp','iso_ts'])
    for c in candidates:
        ts = c.get('timestamp')
        iso = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat() if ts else ''
        w.writerow([c.get('market'), c.get('amount'), c.get('planned_price'), c.get('profit'), ts, iso])
print('WROTE', OUT, 'ROWS', len(candidates))