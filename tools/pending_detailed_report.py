import json, csv, os, datetime

SRC = 'data/pending_saldo.json'
OUT_DIR = 'tools'
OUT = os.path.join(OUT_DIR, 'pending_detailed_top50.csv')

with open(SRC, 'r', encoding='utf-8') as f:
    data = json.load(f)

entries = [e for e in data if isinstance(e.get('profit'), (int,float))]
entries.sort(key=lambda e: e['profit'])

top50 = entries[:50]

os.makedirs(OUT_DIR, exist_ok=True)
with open(OUT, 'w', newline='', encoding='utf-8') as csvf:
    w = csv.writer(csvf)
    headers = ['market','profit','timestamp','iso_ts','buy_price','sell_price','amount','reason','bitvavo_balance','open_trade_buy_price','open_trade_highest_price','open_trade_amount','open_trade_timestamp']
    w.writerow(headers)
    for e in top50:
        ts = e.get('timestamp')
        iso = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat() if ts else ''
        ot = e.get('open_trade') or {}
        row = [e.get('market'), e.get('profit'), ts, iso, e.get('buy_price'), e.get('sell_price'), e.get('amount'), e.get('reason'), e.get('bitvavo_balance'), ot.get('buy_price'), ot.get('highest_price'), ot.get('amount'), ot.get('timestamp')]
        w.writerow(row)
print('WROTE', OUT, 'ROWS', len(top50))