"""Send Telegram summary of all fixes applied."""
import sys
sys.path.insert(0, '.')

from modules.telegram_handler import _reload_credentials, send_message
_reload_credentials()

msg = """<b>🔧 BITVAVO BOT - FIX RAPPORT</b>

<b>Aanleiding:</b> Vergelijking echte Bitvavo transacties vs bot records toonde discrepanties in verkoopprijzen bij stop-loss exits.

<b>═══ CODE FIXES (trailing_bot.py) ═══</b>

<b>1. Stop-loss sells</b> ✅
Bot gebruikte ticker prijs (cp) i.p.v. werkelijke Bitvavo uitvoeringsprijs. Nu gebruikt _verify_sell_response() voor echte prijs.

<b>2. Max-age sells</b> ✅
Zelfde fix: uitvoeringsprijs vervanger ticker prijs.

<b>3. Max-drawdown sells</b> ✅
Zelfde fix: uitvoeringsprijs vervangt ticker prijs.

<b>═══ DATA CORRECTIES (trade_log.json) ═══</b>

10 historische stop-loss trades gecorrigeerd:
• SOL-EUR: €71.20→€71.06 (-€0.06)
• DOGE-EUR: €0.0771→€0.0774 (+€0.11)
• AAVE-EUR: €92.95→€92.83 (-€0.04)
• BCH-EUR: €382.29→€381.46 (-€0.07)
• INJ-EUR: €2.489→€2.493 (+€0.05)
• XRP-EUR: €1.099→€1.100 (+€0.01)
• SOL-EUR: €71.35→€72.17 (+€0.24)
• PEPE-EUR: correctie (+€0.06)
• SHIB-EUR: correctie (+€0.12)
• OP-EUR: €0.1068→€0.1066 (-€0.04)

<b>Totaal profit impact: +€0.38</b>
Profits dict herberekend uit 104 trades.

<b>═══ BTC/ETH TRACKING ═══</b>

BTC en ETH trades zijn GRID/HODL systeem (apart van trailing bot). Correct bijgehouden in grid_states.json:
• BTC grid winst: €1.77
• ETH grid winst: €2.39

<b>═══ TRAILING TP &amp; PARTIAL TP ═══</b>

Trailing TP + Partial TP gebruikten al _verify_sell_response() → correcte prijzen ✅
UNI/RENDER partial sells correct verwerkt via partial_tp_returned_eur ✅

<b>═══ TESTS ═══</b>

38/38 relevante tests PASSED ✅
Geen compile errors ✅
Backups gemaakt ✅"""

ok = send_message(msg)
print(f"Telegram sent: {ok}")
