import csv, os

IN = 'tools/resell_recommendations.csv'
OUT = 'tools/top10_resell_recommendations.csv'

seen = set()
rows = []
with open(IN, newline='', encoding='utf-8') as f:
    r = csv.DictReader(f)
    for row in r:
        market = row.get('market')
        if market in seen:
            continue
        seen.add(market)
        rows.append(row)
        if len(rows) >= 10:
            break

os.makedirs('tools', exist_ok=True)
with open(OUT, 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['market','amount','planned_price','profit','timestamp','score'])
    for r in rows:
        w.writerow([r.get('market'), r.get('amount'), r.get('planned_price'), r.get('profit'), r.get('timestamp'), r.get('score')])

print('WROTE', OUT, 'ROWS', len(rows))