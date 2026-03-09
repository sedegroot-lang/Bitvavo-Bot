import csv
from decimal import Decimal

IN='tools/top10_resell_recommendations.csv'
rows=[]
with open(IN, newline='', encoding='utf-8') as f:
    r=csv.DictReader(f)
    for row in r:
        market=row['market']
        amount=Decimal(row['amount']) if row['amount'] else Decimal('0')
        price=Decimal(row['planned_price']) if row['planned_price'] else Decimal('0')
        eur=amount*price
        rows.append((market,amount,price,eur,row['profit']))

total_eur=sum(r[3] for r in rows)
print('Planned orders:')
for m,a,p,e,prof in rows:
    print(f"- {m}: amount={a} price={p} EUR_value={e:.8f} profit={prof}")
print(f"TOTAL EUR exposure if filled (approx): {total_eur:.8f}")
print(f"ROWS: {len(rows)}")
