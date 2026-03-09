import os
import json
from modules.bitvavo_client import get_bitvavo
import os

# Use central factory; it will load .env automatically
bitvavo = get_bitvavo()
if not bitvavo:
    print('Bitvavo client kon niet worden gemaakt (controleer API keys in .env)')
    exit(1)

# Open trade zoeken
TRADE_LOG = 'trade_log.json'
open_trade = None
for market in ['UNI-EUR', 'RUNE-EUR', 'CAKE-EUR']:
    try:
        with open(TRADE_LOG, encoding='utf-8') as f:
            data = json.load(f)
        trade = data.get('open', {}).get(market)
        if trade:
            open_trade = (market, trade)
            break
    except Exception as e:
        print('Fout bij lezen trade_log.json:', e)
        exit(1)

if not open_trade:
    print('Geen open trade gevonden voor UNI-EUR, RUNE-EUR of CAKE-EUR.')
    exit(1)

market, trade = open_trade
print(f'Probeer DCA-buy op {market}...')
print('Trade details (dca_buys, last_dca_price, dca_next_price):', trade.get('dca_buys'), trade.get('last_dca_price'), trade.get('dca_next_price'))

# Kleine hoeveelheid bepalen (0.01 EUR equivalent)
try:
    price = float(trade.get('buy_price', 0.0))
    # target at least 1 EUR to avoid min-order errors; adjust later using market info
    quote_target = 1.0
    amount = quote_target / price if price > 0 else 0.01
    # try fetch market info to determine min order sizes and precision
    market_info = None
    try:
        mi = bitvavo.markets({'market': market})
        print('Raw markets response for', market, ':', mi)
        # API may return list or dict
        if isinstance(mi, dict):
            market_info = mi
        elif isinstance(mi, list) and len(mi) > 0:
            market_info = mi[0]
        if market_info:
            print('Market info:', market_info)
    except Exception as e:
        print('Failed to fetch market info:', e)
        market_info = None
    if market_info:
        try:
            min_quote = float(market_info.get('minOrderInQuoteAsset') or 0)
        except Exception:
            min_quote = 0
        try:
            min_base = float(market_info.get('minOrderInBaseAsset') or 0)
        except Exception:
            min_base = 0
        try:
            amount_prec = int(market_info.get('amountPrecision') or market_info.get('quantityDecimals') or 8)
        except Exception:
            amount_prec = 8
        # ensure quote_target meets min quote
        if min_quote and quote_target < min_quote:
            quote_target = min_quote
            amount = quote_target / price if price > 0 else amount
        # ensure base amount meets min base
        if min_base and amount < min_base:
            amount = min_base
        # round down to precision
        fmt = '{:.' + str(amount_prec) + 'f}'
        amount = float(fmt.format(amount))
    else:
        amount = round(amount, 6)
except Exception:
    amount = 0.01

order_params = {
    'amount': str(amount),
    'market': market,
    'side': 'buy',
    'orderType': 'market'
}

try:
    print('Plaats order met amount=', amount)
    order_payload = {'amount': str(amount)}
    operator_id = os.getenv('BITVAVO_OPERATOR_ID')
    if operator_id:
        # some Bitvavo clients require operatorId in the per-order params
        order_payload['operatorId'] = operator_id
    resp = bitvavo.placeOrder(market, 'buy', 'market', order_payload)
    print('Order response:', resp)
    if isinstance(resp, dict) and resp.get('orderId'):
        print('✅ DCA-buy succesvol geplaatst!')
    elif isinstance(resp, dict) and resp.get('errorCode'):
        print(f'❌ Fout: {resp.get("error")}, code: {resp.get("errorCode")}')
    else:
        print('Onverwachte response:', resp)
except Exception as e:
    print('Exception bij order plaatsen:', e)
