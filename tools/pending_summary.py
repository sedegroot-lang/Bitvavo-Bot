import json, csv, os
from collections import defaultdict

SRC = 'data/pending_saldo.json'
OUT_DIR = 'tools'
OUT = os.path.join(OUT_DIR, 'pending_summary.csv')

with open(SRC, 'r', encoding='utf-8') as f:
    data = json.load(f)

by_market = defaultdict(list)
for e in data:
    m = e.get('market')
    if m:
        by_market[m].append(e)

rows = []
for m, items in by_market.items():
    profits = [i.get('profit') for i in items if isinstance(i.get('profit'), (int,float))]
    cnt = len(items)
    total = sum(profits) if profits else 0
    avg = total/cnt if cnt else 0
    rows.append((m, cnt, total, avg))

rows.sort(key=lambda x: x[2])

os.makedirs(OUT_DIR, exist_ok=True)
with open(OUT, 'w', newline='', encoding='utf-8') as csvf:
    w = csv.writer(csvf)
    w.writerow(['market','count','sum_profit','avg_profit'])
    for r in rows:
        w.writerow(r)
print('WROTE', OUT, 'ROWS', len(rows))