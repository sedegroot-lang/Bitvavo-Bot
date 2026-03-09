import json, os, time
BASE = os.path.dirname(os.path.dirname(__file__))
trade_file = os.path.join(BASE, 'data', 'trade_log.json')
pend_file = os.path.join(BASE, 'data', 'pending_saldo.json')
cfg_file = os.path.join(BASE, 'config', 'bot_config.json')

def load_json(p):
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

cfg = load_json(cfg_file) or {}
tr = load_json(trade_file) or {}
pend = load_json(pend_file) or []

# exposure
open_trades = tr.get('open', {}) or {}
exposure = 0.0
for v in open_trades.values():
    try:
        exposure += float(v.get('buy_price',0) or 0) * float(v.get('amount',0) or 0)
    except Exception:
        pass

# pending saldo sum
pending_sum = sum(float(t.get('profit',0) or 0) for t in pend if t.get('reason')=='saldo_error')
pending_count = len([t for t in pend if t.get('reason')=='saldo_error'])

# closed saldo_error sum (recent window)
window_days = int(cfg.get('SALDO_QUARANTINE_WINDOW_DAYS', 14))
cutoff = time.time() - window_days*24*3600
closed = tr.get('closed', []) or []
closed_recent = [t for t in closed if t.get('reason')=='saldo_error' and t.get('timestamp',0) >= cutoff]
closed_sum = sum(float(t.get('profit',0) or 0) for t in closed_recent)

# top markets by saldo_error occurrences
counts = {}
for t in pend:
    if t.get('reason')=='saldo_error' and t.get('timestamp',0) >= cutoff:
        counts[t.get('market')] = counts.get(t.get('market'),0)+1
for t in closed_recent:
    counts[t.get('market')] = counts.get(t.get('market'),0)+1

sorted_counts = sorted(counts.items(), key=lambda x: x[1], reverse=True)

print('exposure_eur', round(exposure,2))
print('pending_saldo_count', pending_count, 'pending_saldo_sum', round(pending_sum,2))
print('closed_recent_count', len(closed_recent), 'closed_recent_sum', round(closed_sum,2))
print('top_saldo_markets', sorted_counts[:15])

# compute quarantine set per config
thresh = int(cfg.get('SALDO_QUARANTINE_THRESHOLD', 2))
quarantine = [m for m,c in counts.items() if c>=thresh]
print('quarantine_markets', quarantine)
