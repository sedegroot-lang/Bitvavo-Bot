# Analyze last 110 closed trades from data/trade_log.json (trailing bot format)
# Run with: .\.venv\Scripts\python.exe tools\analysis\last_trades_summary_trailing.py

import json
import statistics
import collections
import sys
from pathlib import Path

DATA_PATH = Path('data/trade_log.json')


def load_trades(path):
    try:
        with path.open('r', encoding='utf-8') as f:
            j = json.load(f)
    except Exception as e:
        print('ERROR: could not load {}: {}'.format(path, e))
        sys.exit(2)
    if isinstance(j, dict):
        closed = j.get('closed', []) or []
    elif isinstance(j, list):
        closed = j
    else:
        print('Unexpected trade_log format:', type(j))
        sys.exit(2)
    return closed


def safe_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        try:
            return float(str(v))
        except Exception:
            return default


def analyze(trades):
    t = list(trades)[-110:]
    if not t:
        print('No closed trades found.')
        return
    profits = []
    markets = []
    durations = []
    keys_counter = collections.Counter()
    for x in t:
        if not isinstance(x, dict):
            # skip malformed entries
            continue
        p = safe_float(x.get('profit'))
        profits.append(p)
        markets.append(x.get('market') or 'unknown')
        for k in list(x.keys()):
            keys_counter[k] += 1
        a = x.get('timestamp') or x.get('opened_ts') or x.get('opened') or x.get('created') or x.get('created_ts')
        b = x.get('closed_timestamp') or x.get('closed_ts') or x.get('closed_at') or x.get('closed') or x.get('closed_ts_iso')
        try:
            if a is not None and b is not None:
                durations.append(float(b) - float(a))
        except Exception:
            pass
    cnt = len(profits)
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p <= 0]
    win_rate = (len(wins) / cnt * 100) if cnt else 0
    avg_profit = (sum(profits) / cnt) if cnt else 0
    median_profit = statistics.median(profits) if profits else 0
    avg_win = (sum(wins) / len(wins)) if wins else 0
    avg_loss = (sum(losses) / len(losses)) if losses else 0
    total = sum(profits)
    by_market = collections.Counter(markets).most_common(10)
    avg_hold = (sum(durations) / len(durations)) if durations else None

    print('=== Last {} closed trades analysis ==='.format(cnt))
    print('Win rate: {:0.1f}% ({} wins / {} trades)'.format(win_rate, len(wins), cnt))
    print('Total profit across these trades: {:.2f} EUR'.format(total))
    print('Average profit per trade: {:.4f} EUR'.format(avg_profit))
    print('Median profit: {:.4f} EUR'.format(median_profit))
    print('Average WIN: {:.4f} EUR  |  Average LOSS: {:.4f} EUR'.format(avg_win, avg_loss))
    if avg_hold is not None:
        print('Average holding time: {:.1f} seconds (~{:.2f} minutes) based on {} entries'.format(avg_hold, avg_hold / 60 if avg_hold else 0, len(durations)))
    else:
        print('Holding time: insufficient timestamp data to compute averages')
    print('\nTop markets (by trade count):')
    for m, c in by_market:
        print(' - {:<12} {:>3d} trades'.format(m, c))
    print('\nMost common trade fields (sample schema insight):')
    for k, c in keys_counter.most_common(20):
        print(' - {:<30} {:>4d}'.format(k, c))
    print('\nExample first trade:')
    import json as _json
    print(_json.dumps(t[0], indent=2, ensure_ascii=False)[:1000])
    print('\n...')
    print('\nExample last trade:')
    print(_json.dumps(t[-1], indent=2, ensure_ascii=False)[:1000])


if __name__ == '__main__':
    trades = load_trades(DATA_PATH)
    analyze(trades)
