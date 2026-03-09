import time
import json
import logging
from modules.bitvavo_client import get_bitvavo

# Configuratie
API_KEY = 'YOUR_API_KEY'
API_SECRET = 'YOUR_API_SECRET'
BASE_CURRENCY = 'EUR'
MARKETS = ['BTC-EUR', 'ETH-EUR']
import os
with open(os.path.join(os.path.dirname(__file__), 'bot_config.json'), encoding='utf-8') as f:
    config = json.load(f)
TRAILING_PERCENT = config.get('DEFAULT_TRAILING', 0.018)
TRAILING_START_THRESHOLD = config.get('TRAILING_START_THRESHOLD', 0.02)
HARD_STOP_PERCENT = 0.05
LOG_FILE = 'bot_log.txt'

# Logging setup
logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
                    format='%(asctime)s %(levelname)s: %(message)s')

def log(msg, level='info'):
    getattr(logging, level)(msg)
    print(msg)

# Bitvavo client (centralized)
bitvavo = get_bitvavo(config)
if not bitvavo:
    log('Bitvavo client kon niet worden gemaakt (controleer API keys).', level='error')
    raise SystemExit(1)

# Helper: trailing/hard stop berekening

def calculate_stop_levels(buy, high):
    try:
        # Trailing pas actief als hoogste prijs >= 2% boven aankoop
        if high >= buy * (1 + TRAILING_START_THRESHOLD):
            trailing = high * (1 - TRAILING_PERCENT)
        else:
            trailing = buy  # trailing niet actief, geen verkoop
        hard = buy * (1 - HARD_STOP_PERCENT) if buy else 0.0
        stop = max(trailing, hard)
        trend_strength = (high - buy) / buy if buy else 0.0
        result = (stop, trailing, hard, trend_strength)
        if not isinstance(result, (list, tuple)) or len(result) != 4:
            log(f"[ERROR] calculate_stop_levels fallback: {result}", level='error')
            return 0, 0, 0, 0
        return result
    except Exception as e:
        log(f"[ERROR] calculate_stop_levels exception: {e}", level='error')
        return 0, 0, 0, 0

# Main trading loop

def main():
    open_trades = {}
    while True:
        for market in MARKETS:
            try:
                ticker = bitvavo.tickerPrice({ 'market': market })
                price = float(ticker['price'])
                # Simuleer een koop
                buy_price = price
                high_price = price * 1.01  # Simuleer hoogste prijs
                stop, trailing, hard, trend_strength = calculate_stop_levels(buy_price, high_price)
                log(f"{market}: prijs {price:.2f}, trailing {trailing:.2f}, hard {hard:.2f}, stop {stop:.2f}, trend {trend_strength:.3f}")
                # Simuleer trade openen
                open_trades[market] = {
                    'buy_price': buy_price,
                    'highest_price': high_price,
                    'stop': stop
                }
            except Exception as e:
                log(f"[ERROR] Fout in trading loop voor {market}: {e}", level='error')
        time.sleep(10)

if __name__ == '__main__':
    log('Bitvavo trailing bot gestart...')
    main()
