import time, json, os

LOG = 'bot_log.txt'
HEART = 'data/heartbeat.json'
ALERT_OUT = os.path.join('logs','last_alert.json')

os.makedirs('logs', exist_ok=True)

def tail_file(path, last_pos=0):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            f.seek(last_pos)
            data = f.read()
            pos = f.tell()
            return data, pos
    except FileNotFoundError:
        return '', last_pos

print('Starting simple monitor: watching', LOG, 'and', HEART)
last_pos = 0
while True:
    data, last_pos = tail_file(LOG, last_pos)
    if data:
        lines = data.splitlines()
        saldo_lines = [l for l in lines if 'saldo_error' in l]
        if saldo_lines:
            alert = {'ts': time.time(), 'count': len(saldo_lines), 'sample': saldo_lines[:5]}
            with open(ALERT_OUT, 'w', encoding='utf-8') as af:
                json.dump(alert, af)
            print('ALERT written:', alert)
    # heartbeat
    try:
        with open(HEART, 'r', encoding='utf-8') as hf:
            hb = json.load(hf)
            print('heartbeat:', hb.get('ts'), 'open_trades:', hb.get('open_trades'))
    except Exception:
        pass
    time.sleep(5)
