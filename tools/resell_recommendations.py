import json, csv, os, datetime

SRC = 'tools/planned_resells_dryrun.csv'
OUT = 'tools/resell_recommendations.csv'

# Read the dryrun CSV and score candidates by confidence
rows = []
with open(SRC, 'r', encoding='utf-8') as f:
    import csv as _csv
    r = _csv.DictReader(f)
    for row in r:
        # parse values
        market = row.get('market')
        try:
            profit = float(row.get('profit') or 0)
        except:
            profit = 0
        try:
            planned_price = float(row.get('planned_price') or 0)
        except:
            planned_price = 0
        try:
            amount = float(row.get('amount') or 0)
        except:
            amount = 0
        ts = row.get('timestamp')
        # Confidence heuristics:
        # - prefer entries with smaller abs(loss) (less downside)
        # - prefer entries with planned_price > 0
        # - prefer smaller amounts for quick tests
        score = 0
        if planned_price > 0:
            score += 30
        # smaller absolute loss => higher score
        score += max(0, 20 - abs(profit))
        # smaller amount => higher score (less risk)
        if amount > 0:
            score += max(0, 10 - min(10, amount/100))
        # recency bonus
        try:
            age = datetime.datetime.utcnow().timestamp() - float(ts)
            if age < 60*60*24:
                score += 5
        except:
            pass
        rows.append({'market':market,'amount':amount,'planned_price':planned_price,'profit':profit,'timestamp':ts,'score':score})

rows.sort(key=lambda r: r['score'], reverse=True)

os.makedirs('tools', exist_ok=True)
with open(OUT, 'w', newline='', encoding='utf-8') as csvf:
    w = csv.writer(csvf)
    w.writerow(['market','amount','planned_price','profit','timestamp','score'])
    for r in rows:
        w.writerow([r['market'],r['amount'],r['planned_price'],r['profit'],r['timestamp'],r['score']])

print('WROTE', OUT, 'ROWS', len(rows))
