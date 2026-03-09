import json, statistics, datetime, sys
from pathlib import Path
p=Path('data')/ 'trade_archive.json'
if not p.exists():
    print('trade_archive.json niet gevonden in data/'); sys.exit(1)
with p.open('r', encoding='utf-8') as f:
    j=json.load(f)
trades=j.get('trades',[])
stops=[t for t in trades if t.get('reason')=='stop']
if not stops:
    print('Geen trades met reason=="stop" gevonden.'); sys.exit(0)
# sort by archived_at
stops_sorted=sorted(stops, key=lambda t: t.get('archived_at', t.get('timestamp',0)))

# profits and durations
profits=[]
durations=[]
for t in stops_sorted:
    try:
        pval=float(t.get('profit') or 0)
    except:
        pval=0.0
    profits.append(pval)
    a=t.get('archived_at')
    ts=t.get('timestamp')
    try:
        if a and ts:
            durations.append(float(a)-float(ts))
    except:
        pass

count=len(profits)
total=sum(profits)
avg=statistics.mean(profits) if profits else 0
med=statistics.median(profits) if profits else 0
largest_loss=min(profits)
largest_win=max(profits)
std=statistics.pstdev(profits) if len(profits)>1 else 0

from collections import Counter
markets=Counter([t.get('market') for t in stops_sorted])

# worst stops (most negative profit)
worst=sorted(zip(stops_sorted,profits), key=lambda x: x[1])[:20]

# recent 10 stops
recent10=[{
    'market':t.get('market'),
    'profit':t.get('profit'),
    'timestamp': datetime.datetime.fromtimestamp(t.get('timestamp')).isoformat(sep=' ', timespec='seconds') if t.get('timestamp') else None,
    'archived_at': datetime.datetime.fromtimestamp(t.get('archived_at')).isoformat(sep=' ', timespec='seconds') if t.get('archived_at') else None,
    'buy_price': t.get('buy_price'), 'sell_price': t.get('sell_price')
} for t in stops_sorted[-10:]]

print('--- Analyse van alle trades met reason=="stop" ---')
print(f'Aantal stops: {count}')
print(f'Totaal P&L (stops): {total:.6f} EUR')
print(f'Gemiddelde profit (stops): {avg:.6f} | Mediaan: {med:.6f} | Std: {std:.6f}')
print(f'Grootste verlies (stop): {largest_loss} | Grootste winst (stop): {largest_win}')
if durations:
    print(f'Gemiddelde duur (secs): {statistics.mean(durations):.1f} | Mediaan duur: {statistics.median(durations):.1f}')
print('\nTop markten bij stops:')
for m,c in markets.most_common(12):
    print(f'  {m}: {c}')

print('\nTop 20 grootste verliezen (stop):')
for t,p in worst:
    at=t.get('archived_at', t.get('timestamp'))
    try:
        atstr=datetime.datetime.fromtimestamp(at).isoformat(sep=' ', timespec='seconds')
    except:
        atstr=str(at)
    print(f"{atstr} | {t.get('market')} | profit={p} | buy={t.get('buy_price')} | sell={t.get('sell_price')} | amount={t.get('amount')}")

print('\nRecente 10 stops:')
for r in recent10:
    print(r)

# exit
