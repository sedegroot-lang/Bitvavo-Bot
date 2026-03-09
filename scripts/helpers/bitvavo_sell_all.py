import os
from dotenv import load_dotenv
from python_bitvavo_api.bitvavo import Bitvavo

load_dotenv()
API_KEY = os.getenv("BITVAVO_API_KEY")
API_SECRET = os.getenv("BITVAVO_API_SECRET")
OPERATOR_ID = os.getenv("BITVAVO_OPERATOR_ID") or None
params = {"APIKEY": API_KEY, "APISECRET": API_SECRET}
if OPERATOR_ID:
    params['OPERATORID'] = OPERATOR_ID
bitvavo = Bitvavo(params)

def sell_all():
    balances = bitvavo.balance({})
    for asset in balances:
        symbol = asset.get('symbol')
        available = float(asset.get('available', 0))
        if symbol == 'EUR' or available == 0:
            continue
        market = f"{symbol}-EUR"
        print(f"Verkoop {available} {symbol} op {market}")
        params = {'amount': round(available, 8)}
        if OPERATOR_ID:
            params['operatorId'] = OPERATOR_ID
        resp = bitvavo.placeOrder(market, 'sell', 'market', params)
        print(f"Response: {resp}")

if __name__ == "__main__":
    sell_all()
