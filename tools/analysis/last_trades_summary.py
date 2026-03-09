import json, statistics, datetime, sys
from pathlib import Path
p=Path('data')/ 'trade_archive.json'
if not p.exists():
    print('trade_archive.json niet gevonden in data/'); sys.exit(1)
with p.open('r', encoding='utf-8') as f:
    j=json.load(f)
trades=j.get('trades',[])
trades_sorted=sorted(trades, key=lambda t: t.get('archived_at', t.get('timestamp', 0)))
N=50
lastN=trades_sorted[-N:]

profits=[]
for t in lastN:
    try:
        pval = float(t.get('profit') or 0)
    except:
        pval = 0.0
    profits.append(pval)

count=len(profits)
win_count=sum(1 for p in profits if p>0)
loss_count=count-win_count

summary={
    'count': count,
    'total_profit': round(sum(profits),6),
    'avg_profit': round(statistics.mean(profits) if profits else 0,6),
    'median_profit': round(statistics.median(profits) if profits else 0,6),
    'winrate_pct': round(win_count/count*100,2) if count else 0,
    'avg_win': round(statistics.mean([p for p in profits if p>0]) if win_count else 0,6),
    'avg_loss': round(statistics.mean([p for p in profits if p<=0]) if loss_count else 0,6),
    'largest_win': round(max(profits) if profits else 0,6),
    'largest_loss': round(min(profits) if profits else 0,6)
}
from collections import Counter
reasons=Counter([t.get('reason') for t in lastN])
markets=Counter([t.get('market') for t in lastN])

print('--- Samenvatting laatste {} afgesloten trades ---'.format(count))
print('Totaal P&L: {total_profit}  |  Gemiddeld: {avg_profit}  |  Mediaan: {median_profit}'.format(**summary))
print('Winrate: {winrate_pct}%  |  Gem. winst: {avg_win}  |  Gem. verlies: {avg_loss}'.format(**summary))
print('Grootste winst: {largest_win}  |  Grootste verlies: {largest_loss}'.format(**summary))
print('\nTop redenen:', ', '.join(f"{k}:{v}" for k,v in reasons.items()))
print('Top markten:', ', '.join(f"{m}:{c}" for m,c in markets.most_common(8)))
print('\nRecente 10 trades:')
for t in trades_sorted[-10:]:
    at=t.get('archived_at', t.get('timestamp', None))
    try:
        atstr=datetime.datetime.fromtimestamp(at).isoformat(sep=' ', timespec='seconds') if at else ''
    except:
        atstr=str(at)
    print(f"{atstr} | {t.get('market')} | profit={t.get('profit')} | reason={t.get('reason')}")

# exit code 0
