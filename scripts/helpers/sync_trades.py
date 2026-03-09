import os, json, time
from dotenv import load_dotenv
from python_bitvavo_api.bitvavo import Bitvavo

from modules.trade_store import save_snapshot as save_trade_snapshot

# Import archive_trade for permanent trade storage
try:
    from modules.trade_archive import archive_trade
except ImportError:
    archive_trade = None

# === CONFIG ===
load_dotenv()
API_KEY = os.getenv("BITVAVO_API_KEY")
API_SECRET = os.getenv("BITVAVO_API_SECRET")
TRADE_LOG = "trade_log.json"

from modules.bitvavo_client import get_bitvavo

bitvavo = get_bitvavo()
if not bitvavo:
    print('Bitvavo client kon niet worden gemaakt (controleer API keys).')
    raise SystemExit(1)

# === HELPERS ===
def log(msg):
    print(f"[SYNC] {msg}")

def safe_call(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception as e:
        log(f"API error: {e}")
        return None

def get_current_price(market):
    t = safe_call(bitvavo.tickerPrice, {'market': market})
    return float(t['price']) if t and 'price' in t else None

def load_local_trades():
    if os.path.exists(TRADE_LOG):
        try:
            with open(TRADE_LOG, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {"open": {}, "closed": [], "profits": {}}

def save_trades(data):
    save_trade_snapshot(data, TRADE_LOG, indent=2)

# === SYNC ===
def sync_trades():
    data = load_local_trades()
    open_trades = data.get("open", {})
    closed_trades = data.get("closed", [])
    market_profits = data.get("profits", {})

    balances = safe_call(bitvavo.balance, {}) or []
    bitvavo_positions = {b['symbol']: float(b['available']) for b in balances if float(b.get('available',0)) > 0}

    # 1. Spooktrades verwijderen
    for market in list(open_trades.keys()):
        sym = market.split('-')[0]
        if sym not in bitvavo_positions:
            log(f"⚠️ {market} staat in JSON maar niet bij Bitvavo → verwijderen")
            sell_price = get_current_price(market) or 0
            buy_price = open_trades[market]['buy_price']
            amount = open_trades[market]['amount']
            profit = (sell_price - buy_price) * amount
            closed_entry = {
                'market': market,
                'buy_price': buy_price,
                'sell_price': sell_price,
                'amount': amount,
                'profit': profit,
                'timestamp': time.time(),
                'reason': 'sync-cleanup'
            }
            # Archive trade permanently
            if archive_trade:
                try:
                    archive_trade(**closed_entry)
                except Exception:
                    pass
            closed_trades.append(closed_entry)
            del open_trades[market]

    # 2. Ontbrekende posities toevoegen
    for sym, amt in bitvavo_positions.items():
        if sym == "EUR":
            continue
        market = f"{sym}-EUR"
        if market not in open_trades:
            price_now = get_current_price(market)
            if not price_now:
                continue
            log(f"⚠️ {market} staat bij Bitvavo ({amt}) maar niet in JSON → toevoegen")
            open_trades[market] = {
                'buy_price': price_now,
                'highest_price': price_now,
                'amount': amt,
                'timestamp': time.time(),
                # No partial TPs in this bot: keep DCA tracking keys consistent
                'dca_buys': 0,
                'dca_max': int(__import__('json').loads(open('bot_config.json').read()).get('DCA_MAX_BUYS', 3) if __import__('os').path.exists('bot_config.json') else 3),
                'last_dca_price': price_now,
            }

    # opslaan
    data["open"] = open_trades
    data["closed"] = closed_trades
    data["profits"] = market_profits
    save_trades(data)
    log("✅ Sync voltooid: JSON en Bitvavo zijn gelijkgetrokken.")

if __name__ == "__main__":
    sync_trades()