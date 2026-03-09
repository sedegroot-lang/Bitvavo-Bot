import requests

def check(urls):
    for u in urls:
        try:
            r = requests.head(u, timeout=5)
            print(u, '->', r.status_code)
        except Exception as e:
            print(u, '-> ERROR', e)

urls=[
    'https://static.bitvavo.com/images/markets/near.png',
    'https://static.bitvavo.com/images/coins/near.png',
    'https://static.bitvavo.com/images/icons/near.png',
    'https://static.bitvavo.com/images/coins/NEAR.png',
    'https://static.bitvavo.com/images/markets/NEAR.png',
    'https://static.bitvavo.com/images/coin/near.png',
    'https://static.bitvavo.com/images/coins/near.svg',
    'https://static.bitvavo.com/images/markets/near-eur.png',
    'https://static.bitvavo.com/img/coins/near.png',
    'https://static.bitvavo.com/images/coins/near/64.png'
]

if __name__ == '__main__':
    check(urls)
