import os, json, time, shutil
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(__file__))
TRADE_LOG = os.path.join(ROOT, 'data', 'trade_log.json')
PENDING = os.path.join(ROOT, 'data', 'pending_saldo.json')
REPORT = os.path.join(ROOT, 'tools', 'reconcile_report.json')
BACKUP_DIR = os.path.join(ROOT, 'tools', 'backups')

os.makedirs(BACKUP_DIR, exist_ok=True)

def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def backup(path):
    if not os.path.exists(path):
        return None
    ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    base = os.path.basename(path)
    dest = os.path.join(BACKUP_DIR, f"{base}.{ts}.bak")
    shutil.copy2(path, dest)
    return dest


def find_match(pending_item, closed_list):
    """Try to find a matching real sell for a pending saldo_error entry.
    Matching heuristics:
    - same market
    - sell_price > 0 in closed trade
    - amount approximately equal (+-1%)
    - timestamp after pending's timestamp
    """
    pm = pending_item.get('market')
    pamt = float(pending_item.get('amount', 0) or 0)
    pts = pending_item.get('timestamp', 0)
    candidates = []
    for t in closed_list:
        try:
            if t.get('market') != pm:
                continue
            sp = float(t.get('sell_price', 0) or 0)
            if sp <= 0:
                continue
            amt = float(t.get('amount', 0) or 0)
            if amt <= 0:
                continue
            tts = t.get('timestamp', 0)
            # prefer sells after pending timestamp
            if tts and pts and tts < pts:
                continue
            if pamt == 0:
                # match by market and positive sell only
                candidates.append((abs(amt - pamt), t))
            else:
                rel = abs(amt - pamt) / max(pamt, 1e-9)
                if rel <= 0.02:  # within 2%
                    candidates.append((rel, t))
        except Exception:
            continue
    if not candidates:
        return None
    # return best candidate
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def reconcile():
    data = load_json(TRADE_LOG) or {'open': {}, 'closed': [], 'profits': {}}
    closed = data.get('closed', [])
    pending = load_json(PENDING) or []

    # backup files
    b1 = backup(TRADE_LOG)
    b2 = backup(PENDING)

    report = {
        'timestamp': int(time.time()),
        'backup_trade_log': b1,
        'backup_pending': b2,
        'pending_count': len(pending),
        'matches': [],
        'kept_pending': []
    }

    if not pending:
        with open(REPORT, 'w', encoding='utf-8') as fh:
            json.dump(report, fh, indent=2)
        print('No pending entries found; nothing to do.')
        return report

    # attempt to match each pending to a closed real sell
    for p in pending:
        match = find_match(p, closed)
        if match:
            # If match found, we'll mark pending as reconciled and remove artificial entry
            report['matches'].append({'pending': p, 'matched_to': match})
        else:
            report['kept_pending'].append(p)

    # Build new closed list excluding artificial saldo_error entries that were matched
    matched_ids = set()
    for m in report['matches']:
        # identify matched closed trade by tuple key
        t = m['matched_to']
        key = (t.get('market'), float(t.get('sell_price', 0) or 0), float(t.get('amount', 0) or 0), int(t.get('timestamp', 0) or 0))
        matched_ids.add(key)

    new_closed = []
    for t in closed:
        key = (t.get('market'), float(t.get('sell_price', 0) or 0), float(t.get('amount', 0) or 0), int(t.get('timestamp', 0) or 0))
        # detect artificial saldo_error (sell_price==0.0 and reason==saldo_error)
        if t.get('reason') == 'saldo_error' and float(t.get('sell_price', 0) or 0) == 0.0:
            # if there is a matched real sell for same market/amount, drop this artificial entry
            # else keep it
            keep = True
            for mk in matched_ids:
                if mk[0] == t.get('market') and abs(mk[2] - float(t.get('amount', 0) or 0)) <= 1e-6:
                    keep = False
                    break
            if keep:
                new_closed.append(t)
            else:
                # skip artificial
                continue
        else:
            new_closed.append(t)

    data['closed'] = new_closed

    # write updated trade log (atomic)
    tmp = TRADE_LOG + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, TRADE_LOG)

    # write pending kept list
    with open(PENDING, 'w', encoding='utf-8') as fh:
        json.dump(report['kept_pending'], fh, indent=2)

    with open(REPORT, 'w', encoding='utf-8') as fh:
        json.dump(report, fh, indent=2)

    print('Reconciliation complete. Report written to', REPORT)
    return report

if __name__ == '__main__':
    reconcile()
