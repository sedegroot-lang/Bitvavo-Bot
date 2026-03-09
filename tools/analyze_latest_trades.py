#!/usr/bin/env python3
import json
import csv
import statistics
from datetime import datetime
from pathlib import Path

WORKDIR = Path(__file__).resolve().parents[1]
TRADE_LOG = WORKDIR / 'data' / 'trade_log.json'
OUT_CSV = WORKDIR / 'tools' / 'latest_trades_summary.csv'

N = 50  # last N closed trades

def load_trades(path):
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    open_trades = data.get('open', {})
    closed_trades = data.get('closed', [])
    return open_trades, closed_trades


def safe_float(v):
    try:
        return float(v)
    except Exception:
        return None


def analyze(closed, open_trades, n=N):
    closed_sorted = sorted(closed, key=lambda x: x.get('timestamp', 0), reverse=True)
    last = closed_sorted[:n]

    stats = {
        'count': len(last),
        'valid_count': 0,
        'wins': 0,
        'losses': 0,
        'total_profit': 0.0,
        'profits': [],
        'returns_pct': [],
    }
    per_market = {}

    for t in last:
        market = t.get('market')
        buy = safe_float(t.get('buy_price'))
        sell = safe_float(t.get('sell_price'))
        amount = safe_float(t.get('amount')) or 0.0
        profit = safe_float(t.get('profit'))
        reason = t.get('reason')
        ts = t.get('timestamp')

        # Initialize market bucket
        m = per_market.setdefault(market, {
            'count': 0, 'wins': 0, 'losses': 0, 'total_profit': 0.0, 'profits': []
        })
        m['count'] += 1

        # Determine validity: we consider profit values that aren't the sentinel -10.0 as valid
        valid_profit = profit is not None and profit > -9.0
        if valid_profit:
            stats['valid_count'] += 1
            stats['total_profit'] += profit
            stats['profits'].append(profit)
            m['total_profit'] += profit
            m['profits'].append(profit)
            if profit > 0:
                stats['wins'] += 1
                m['wins'] += 1
            elif profit < 0:
                stats['losses'] += 1
                m['losses'] += 1

        # compute return pct if both buy and sell present and buy>0
        if buy and sell and buy > 0:
            ret = (sell - buy) / buy
            stats['returns_pct'].append(ret)

    # aggregate
    avg_profit = statistics.mean(stats['profits']) if stats['profits'] else 0.0
    median_profit = statistics.median(stats['profits']) if stats['profits'] else 0.0
    avg_return_pct = statistics.mean(stats['returns_pct']) if stats['returns_pct'] else 0.0

    # per-market summaries
    market_rows = []
    for market, v in sorted(per_market.items(), key=lambda x: -x[1]['count']):
        avg_m = statistics.mean(v['profits']) if v['profits'] else 0.0
        market_rows.append({
            'market': market,
            'count': v['count'],
            'wins': v['wins'],
            'losses': v['losses'],
            'total_profit': round(v['total_profit'], 6),
            'avg_profit': round(avg_m, 6)
        })

    # open trades summary
    open_count = len(open_trades)
    open_invested = 0.0
    for k, v in open_trades.items():
        invested = safe_float(v.get('invested_eur'))
        if invested:
            open_invested += invested

    result = {
        'last_n': n,
        'analyzed_count': stats['count'],
        'valid_count': stats['valid_count'],
        'wins': stats['wins'],
        'losses': stats['losses'],
        'win_rate_valid_pct': round(100.0 * stats['wins'] / stats['valid_count'], 2) if stats['valid_count'] else None,
        'total_profit': round(stats['total_profit'], 6),
        'avg_profit': round(avg_profit, 6),
        'median_profit': round(median_profit, 6),
        'avg_return_pct': round(100.0 * avg_return_pct, 3),
        'open_count': open_count,
        'open_invested_eur': round(open_invested, 6),
        'market_rows': market_rows
    }
    return result


def write_csv(rows, path):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['market','count','wins','losses','total_profit','avg_profit'])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def format_ts(ts):
    try:
        return datetime.utcfromtimestamp(ts).isoformat() + 'Z'
    except Exception:
        return ''


def main():
    open_trades, closed_trades = load_trades(TRADE_LOG)
    result = analyze(closed_trades, open_trades, n=N)

    # Print summary in Dutch
    print('Analyse van laatste', result['last_n'], 'gesloten trades')
    print('Totaal geanalyseerd:', result['analyzed_count'])
    print('Geldige (met profit):', result['valid_count'])
    print('Winst trades:', result['wins'], 'Verlies trades:', result['losses'])
    if result['win_rate_valid_pct'] is not None:
        print('Win-rate (van geldige):', f"{result['win_rate_valid_pct']}%")
    print('Totaal profit (EUR):', result['total_profit'])
    print('Gemiddelde profit (EUR):', result['avg_profit'])
    print('Mediaan profit (EUR):', result['median_profit'])
    print('Gemiddelde return (%):', f"{result['avg_return_pct']}%")
    print('Open posities:', result['open_count'], 'Totaal geïnvesteerd (EUR) in open posities:', result['open_invested_eur'])
    print('\nPer-market samenvatting (meest voorkomende eerst):')
    for r in result['market_rows']:
        print(f"{r['market']}: count={r['count']} wins={r['wins']} losses={r['losses']} total_profit={r['total_profit']} avg_profit={r['avg_profit']}")

    # write csv
    try:
        write_csv(result['market_rows'], OUT_CSV)
        print('\nPer-market CSV weggeschreven naar:', OUT_CSV)
    except Exception as e:
        print('Kon CSV niet schrijven:', e)

if __name__ == '__main__':
    main()
