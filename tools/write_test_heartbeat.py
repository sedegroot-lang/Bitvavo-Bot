import json, time
try:
    with open('trade_log.json','r',encoding='utf-8') as fh:
        tj = json.load(fh)
        ot = len(tj.get('open',{})) if isinstance(tj.get('open',{}), dict) else 0
except Exception:
    ot = 0
hb = {'ts': int(time.time()), 'open_trades': ot}
with open('heartbeat.json.tmp','w',encoding='utf-8') as fh:
    json.dump(hb, fh)
import os
os.replace('heartbeat.json.tmp','heartbeat.json')
print('wrote', hb)
