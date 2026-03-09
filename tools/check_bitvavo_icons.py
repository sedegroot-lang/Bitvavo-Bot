import requests

symbols = ['NEAR','XRP','ETH','DOGE','LINK']
patterns = [
    'https://static.bitvavo.com/images/markets/{s}.png',
    'https://static.bitvavo.com/images/markets/{s}-eur.png',
    'https://static.bitvavo.com/images/markets/{s}-EUR.png',
    'https://static.bitvavo.com/images/coins/{s}.png',
    'https://static.bitvavo.com/images/coins/{s}-eur.png',
    'https://static.bitvavo.com/images/icons/{s}.png',
    'https://static.bitvavo.com/images/logos/{s}.png',
    'https://cdn.bitvavo.com/images/markets/{s}.png',
    'https://cdn.bitvavo.com/images/markets/{s}-eur.png',
]

for s in symbols:
    print('\n===', s, '===')
    for p in patterns:
        url = p.format(s=s.lower())
        try:
            r = requests.head(url, timeout=5)
            status = r.status_code
            ctype = r.headers.get('Content-Type')
            print(f'{url} -> {status} {ctype}')
            if status in (405, 403, 301, 302):
                try:
                    r2 = requests.get(url, timeout=5)
                    print(f'   GET -> {r2.status_code} {r2.headers.get("Content-Type")}')
                except Exception as e:
                    print(f'   GET ERR {e}')
        except Exception as e:
            print(f'{url} -> ERR {e}')
