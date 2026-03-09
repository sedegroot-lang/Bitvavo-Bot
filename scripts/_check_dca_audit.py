import json, time, os

dca_path = 'data/dca_audit.log'
if os.path.exists(dca_path):
    with open(dca_path, 'r') as f:
        lines = f.readlines()
    print(f'DCA AUDIT: {len(lines)} entries, last 20:')
    for l in lines[-20:]:
        try:
            ev = json.loads(l.strip())
            ts = time.strftime('%m-%d %H:%M', time.localtime(ev.get('ts', 0)))
            m = ev.get('market','?')
            st = ev.get('status','?')
            reason = ev.get('reason','?')
            dcb = ev.get('dca_buys','?')
            nxt = ev.get('dca_next_price','?')
            bp = ev.get('buy_price','?')
            rsi_val = ev.get('rsi', '')
            thresh = ev.get('rsi_threshold', '')
            extra = f' rsi={rsi_val}/{thresh}' if rsi_val != '' else ''
            price = ev.get('price', '')
            target = ev.get('target', '')
            extra2 = f' price={price} target={target}' if price else ''
            print(f'{ts} {m} {st} {reason} dca={dcb} next={nxt} bp={bp}{extra}{extra2}')
        except Exception as e:
            print(f'parse error: {e}')
else:
    print('No DCA audit log found')

print()
print('=== OPEN TRADES DCA STATE ===')
with open('data/trade_log.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
for m, t in data.get('open', {}).items():
    dcb = t.get('dca_buys', 0)
    dm = t.get('dca_max', '?')
    nxt = t.get('dca_next_price', '?')
    bp = t.get('buy_price', '?')
    invested = t.get('invested_eur', '?')
    print(f'{m}: dca={dcb}/{dm}, next_price={nxt}, buy_price={bp}, invested={invested}')
