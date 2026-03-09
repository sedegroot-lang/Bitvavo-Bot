import json, csv, os, datetime

SRC = 'data/pending_saldo.json'
OUT_DIR = 'tools'
OUT = os.path.join(OUT_DIR, 'pending_top20.csv')

with open(SRC, 'r', encoding='utf-8') as f:
    data = json.load(f)

# Filter entries with numeric profit and sort ascending (most negative first)
entries = [e for e in data if isinstance(e.get('profit'), (int,float))]
entries.sort(key=lambda e: e['profit'])

top20 = entries[:20]

os.makedirs(OUT_DIR, exist_ok=True)
with open(OUT, 'w', newline='', encoding='utf-8') as csvf:
    w = csv.writer(csvf)
    w.writerow(['market','profit','timestamp','iso_ts','buy_price','amount','reason'])
    for e in top20:
        ts = e.get('timestamp')
        iso = datetime.datetime.utcfromtimestamp(ts).isoformat() + 'Z' if ts else ''
        w.writerow([e.get('market'), e.get('profit'), ts, iso, e.get('buy_price'), e.get('amount'), e.get('reason')])

print('WROTE', OUT, 'ROWS', len(top20))
