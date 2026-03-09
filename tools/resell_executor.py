#!/usr/bin/env python3
import csv, os, argparse, datetime

parser = argparse.ArgumentParser(description='Execute resells (dry-run or live).')
parser.add_argument('--input', '-i', default='tools/top10_resell_recommendations.csv')
parser.add_argument('--dry-run', action='store_true', default=False)
parser.add_argument('--out', '-o', default='tools/resell_execute_dryrun.csv')
args = parser.parse_args()

IN = args.input
OUT = args.out
DRY = args.dry_run

print('DRY RUN:', DRY, 'INPUT:', IN, 'OUT:', OUT)

rows = []
with open(IN, newline='', encoding='utf-8') as f:
    r = csv.DictReader(f)
    for row in r:
        try:
            amount = float(row.get('amount') or 0)
            planned_price = float(row.get('planned_price') or 0)
            profit = float(row.get('profit') or 0)
        except:
            amount = 0
            planned_price = 0
            profit = 0
        market = row.get('market')
        ts = row.get('timestamp')
        iso = ''
        try:
            iso = datetime.datetime.fromtimestamp(float(ts), datetime.timezone.utc).isoformat()
        except:
            pass
        # Build planned order
        order = {
            'market': market,
            'amount': amount,
            'price': planned_price,
            'profit': profit,
            'timestamp': ts,
            'iso_ts': iso,
            'status': 'planned_dryrun' if DRY else 'planned_live'
        }
        rows.append(order)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['market','amount','price','profit','timestamp','iso_ts','status'])
    for r in rows:
        w.writerow([r['market'], r['amount'], r['price'], r['profit'], r['timestamp'], r['iso_ts'], r['status']])

print('WROTE', OUT, 'ROWS', len(rows))

if not DRY:
    # Live execution placeholder: requires manual confirmation and API keys
    print('\nLIVE execution requested but not implemented in this script.\nPlease implement Bitvavo API calls separately and ensure API keys are provided securely.')
