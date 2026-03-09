import os
import time
import hmac
import hashlib
import requests
from dotenv import load_dotenv

# Load API keys from .env
load_dotenv()
API_KEY = os.getenv('BITVAVO_API_KEY')
API_SECRET = os.getenv('BITVAVO_API_SECRET')

def bitvavo_signed_headers(api_key, api_secret, method, path, body=''):
    timestamp = str(int(time.time() * 1000))
    message = timestamp + method + path + body
    signature = hmac.new(api_secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return {
        'Bitvavo-Access-Key': api_key,
        'Bitvavo-Access-Signature': signature,
        'Bitvavo-Access-Timestamp': timestamp,
        'Bitvavo-Access-Window': '10000',
        'Content-Type': 'application/json'
    }

def get_eur_balance():
    url = 'https://api.bitvavo.com/v2/balance'
    headers = bitvavo_signed_headers(API_KEY, API_SECRET, 'GET', '/v2/balance')
    try:
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        balances = resp.json()
        
        # EUR balance
        eur = next((b for b in balances if b['symbol'] == 'EUR'), None)
        if eur:
            available = float(eur.get('available', 0))
            in_order = float(eur.get('inOrder', 0))
            total = available + in_order
            print(f"Bitvavo EUR saldo:")
            print(f"  Beschikbaar: {available} EUR")
            print(f"  In gebruik (open orders): {in_order} EUR")
            print(f"  Totaal (beschikbaar + in gebruik): {total} EUR")
        else:
            print("Geen EUR saldo gevonden.")
        
        # Crypto balances
        print("\nCrypto balances:")
        crypto = [b for b in balances if b['symbol'] != 'EUR' and (float(b.get('available', 0)) > 0 or float(b.get('inOrder', 0)) > 0)]
        if crypto:
            for b in crypto:
                available = float(b.get('available', 0))
                in_order = float(b.get('inOrder', 0))
                total = available + in_order
                print(f"  {b['symbol']}: {total:.8f} (available: {available:.8f}, in order: {in_order:.8f})")
        else:
            print("  Geen crypto balances gevonden.")
            
    except Exception as e:
        print(f"Fout bij ophalen saldo: {e}")

if __name__ == '__main__':
    get_eur_balance()
