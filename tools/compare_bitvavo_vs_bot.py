"""
Compare real Bitvavo transactions with bot trade_log.json records.
"""
import json
import datetime

# ============================================================
# 1. REAL BITVAVO TRANSACTIONS (from user input)
# ============================================================
real_txns = [
    # Format: (date_str, type, market, amount_crypto, amount_eur)
    # type: "buy" or "sell"
    # For buy: amount_eur = what you paid
    # For sell: amount_eur = what you received
    
    # 5 mrt 2026
    ("2026-03-05 19:25", "buy",  "ADA",    35.138887,       8.15),
    ("2026-03-05 19:24", "buy",  "APT",    11.38829274,     9.68),
    ("2026-03-05 18:50", "buy",  "APT",    7.66280339,      6.45),
    ("2026-03-05 18:36", "sell", "OP",     196.81770623,    20.92),
    ("2026-03-05 17:17", "sell", "SHIB",   5463009.17,      25.81),
    ("2026-03-05 16:28", "buy",  "BTC",    0.00019485,     12.02),
    ("2026-03-05 15:39", "buy",  "SHIB",   1025450.95,      5.00),
    ("2026-03-05 14:45", "sell", "PEPE",   6941892.0,      21.02),
    ("2026-03-05 10:36", "buy",  "ADA",    22.986104,       5.43),
    ("2026-03-05 02:30", "sell", "LINK",   2.71162526,      21.64),
    ("2026-03-05 00:28", "sell", "SOL",    0.27588562,      21.47),
    
    # 4 mrt 2026
    ("2026-03-04 23:25", "sell", "RENDER", 17.64639133,     21.80),
    ("2026-03-04 22:40", "buy",  "SOL",    0.27588562,     22.02),
    ("2026-03-04 22:39", "buy",  "ADA",    91.067791,      21.97),
    ("2026-03-04 22:37", "buy",  "OP",     196.81770623,   22.02),
    ("2026-03-04 22:36", "buy",  "SHIB",   4437558.22,     21.97),
    ("2026-03-04 22:35", "buy",  "PEPE",   6941892.0,      21.97),
    ("2026-03-04 22:34", "buy",  "LINK",   2.71162526,     22.01),
    ("2026-03-04 22:34", "buy",  "AVAX",   2.67945551,     22.02),
    ("2026-03-04 22:22", "buy",  "DOT",    16.47592666,    21.97),
    ("2026-03-04 22:11", "buy",  "APT",    24.77926843,    21.67),
    ("2026-03-04 21:59", "buy",  "RENDER", 17.64639133,    21.78),
    ("2026-03-04 12:57", "sell", "UNI",    4.98054898,     17.01),
    ("2026-03-04 12:43", "sell", "AVAX",   2.81684019,     22.45),
    ("2026-03-04 11:50", "sell", "RENDER", 14.38984324,    17.16),
    ("2026-03-04 10:42", "sell", "UNI",    1.66018299,      5.79),
    ("2026-03-04 10:02", "sell", "RENDER", 4.79661441,      5.83),
    ("2026-03-04 04:36", "sell", "LTC",    0.4752529,      22.21),
    
    # 3 mrt 2026
    ("2026-03-03 17:36", "sell", "XRP",    18.415377,      21.72),
    ("2026-03-03 17:29", "sell", "LINK",   5.961635,       45.62),
    ("2026-03-03 17:15", "sell", "POL",    307.58032999,   26.98),
    ("2026-03-03 17:09", "sell", "BTC",    0.00011677,      6.89),
    ("2026-03-03 15:54", "sell", "SOL",    0.29880996,     21.51),
    ("2026-03-03 11:34", "buy",  "LINK",   0.68944936,      5.14),
    ("2026-03-03 11:00", "buy",  "LINK",   0.68890263,      5.14),
    ("2026-03-03 09:55", "buy",  "BTC",    0.00011677,      6.74),
    ("2026-03-03 08:49", "buy",  "POL",    58.03046016,     5.00),
    ("2026-03-03 06:36", "buy",  "UNI",    6.64073197,     22.10),
    ("2026-03-03 06:35", "buy",  "SOL",    0.29880996,     22.09),
    ("2026-03-03 06:34", "buy",  "AVAX",   2.81684019,     22.10),
    ("2026-03-03 06:33", "buy",  "LTC",    0.4752529,      22.10),
    ("2026-03-03 06:32", "buy",  "RENDER", 19.18645765,    22.09),
    ("2026-03-03 06:19", "buy",  "XRP",    18.415377,      21.75),
    
    # 2 mrt 2026
    ("2026-03-02 19:27", "sell", "BTC",    0.00011364,      6.71),
    ("2026-03-02 19:10", "sell", "ETH",    0.00358585,      6.21),
    ("2026-03-02 19:04", "sell", "ETH",    0.00691132,     11.98),
    ("2026-03-02 18:53", "buy",  "POL",    249.54986983,   21.82),
    ("2026-03-02 18:45", "sell", "XRP",    6.478416,        7.64),
    ("2026-03-02 18:45", "sell", "XRP",    20.722944,      24.46),
    ("2026-03-02 18:44", "sell", "AVAX",   4.10146658,     32.20),
    ("2026-03-02 18:44", "sell", "LTC",    1.09858752,     50.85),
    ("2026-03-02 18:43", "sell", "DOGE",   632.94941006,   51.15),
    ("2026-03-02 18:33", "sell", "SOL",    0.44020764,     32.93),
    ("2026-03-02 16:14", "sell", "BTC",    0.00010628,      6.20),
    ("2026-03-02 16:14", "sell", "ETH",    0.00726572,     12.59),
    ("2026-03-02 16:07", "sell", "BTC",    0.00017939,     10.32),
    ("2026-03-02 16:07", "sell", "BTC",    0.00017351,      9.98),
    ("2026-03-02 04:33", "buy",  "SOL",    0.44020764,     31.82),
    ("2026-03-02 04:31", "buy",  "AVAX",   4.10146658,     31.81),
    ("2026-03-02 04:30", "buy",  "XRP",    27.20136,       31.75),
    
    # 1 mrt 2026
    ("2026-03-01 21:35", "buy",  "ETH",    0.00379009,      6.17),
    ("2026-03-01 20:44", "buy",  "ETH",    0.00726572,     12.02),
    ("2026-03-01 17:51", "buy",  "ETH",    0.00370117,      6.16),
    ("2026-03-01 17:50", "buy",  "BTC",    0.00017939,     10.02),
    ("2026-03-01 17:49", "buy",  "BTC",    0.00011016,      6.17),
    ("2026-03-01 14:35", "sell", "SOL",    0.47830832,     34.24),
    ("2026-03-01 08:13", "buy",  "LTC",    1.09858752,     50.90),
    ("2026-03-01 08:01", "buy",  "DOGE",   528.529386,     42.50),
    ("2026-03-01 08:01", "buy",  "DOGE",   104.42002406,    8.39),
    ("2026-03-01 07:39", "buy",  "SOL",    0.47830832,     35.10),
    ("2026-03-01 07:29", "buy",  "LINK",   4.58328301,     35.03),
    ("2026-03-01 02:50", "sell", "ETH",    0.00365639,      6.20),
    
    # 28 feb 2026
    ("2026-02-28 23:35", "sell", "BTC",    0.00010878,      6.20),
    ("2026-02-28 21:13", "sell", "ETH",    0.00374234,      6.20),
    ("2026-02-28 19:37", "sell", "BTC",    0.00011288,      6.29),
    ("2026-02-28 15:00", "sell", "ETH",    0.00388331,      6.29),
    ("2026-02-28 07:56", "sell", "XRP",    16.841954,      18.48),
    ("2026-02-28 07:41", "sell", "INJ",    12.73466553,    31.67),
    ("2026-02-28 07:30", "buy",  "ETH",    0.00388331,      6.17),
    ("2026-02-28 07:30", "buy",  "BTC",    0.00011288,      6.17),
    ("2026-02-28 07:28", "sell", "BCH",    0.0404391,      15.39),
    ("2026-02-28 07:28", "sell", "BCH",    0.044448,       16.91),
    ("2026-02-28 07:25", "sell", "AAVE",   0.091319,        8.45),
    ("2026-02-28 07:25", "sell", "AAVE",   0.25999601,     24.08),
    ("2026-02-28 07:24", "sell", "DOGE",   417.28510802,   32.20),
    
    # 27 feb 2026
    ("2026-02-27 18:18", "buy",  "ETH",    0.00374234,      6.09),
    ("2026-02-27 15:07", "buy",  "ETH",    0.00300591,      5.01),
    ("2026-02-27 15:07", "buy",  "BTC",    0.00008899,      5.02),
    ("2026-02-27 13:38", "buy",  "AAVE",   0.35131501,     34.48),
    ("2026-02-27 13:19", "buy",  "INJ",    12.73466553,    34.28),
    ("2026-02-27 13:11", "buy",  "BTC",    0.00010878,      6.09),
    ("2026-02-27 12:41", "buy",  "ETH",    0.00365639,      6.09),
    ("2026-02-27 12:36", "sell", "SOL",    0.48034788,     34.05),
    ("2026-02-27 12:24", "sell", "INJ",    9.14482368,     24.92),
    ("2026-02-27 11:59", "buy",  "BCH",    0.041873,       17.03),
    ("2026-02-27 11:59", "buy",  "BCH",    0.0430141,      17.49),
    ("2026-02-27 11:55", "sell", "AVAX",   4.25148302,     32.76),
    ("2026-02-27 11:22", "buy",  "DOGE",   417.28510802,   34.34),
    ("2026-02-27 11:18", "sell", "FET",    248.15868154,   34.24),
]

# ============================================================
# 2. LOAD BOT DATA
# ============================================================
with open("data/trade_log.json", "r") as f:
    trade_log = json.load(f)

open_trades = trade_log.get("open", {})
closed_trades = trade_log.get("closed", [])

# ============================================================
# 3. BUILD PER-MARKET SUMMARIES FROM REAL DATA
# ============================================================
real_buys = {}  # market -> list of (date, amount, eur)
real_sells = {}  # market -> list of (date, amount, eur)

for date_str, txn_type, market, amount, eur in real_txns:
    if txn_type == "buy":
        real_buys.setdefault(market, []).append((date_str, amount, eur))
    else:
        real_sells.setdefault(market, []).append((date_str, amount, eur))

# ============================================================
# 4. BUILD PER-MARKET SUMMARIES FROM BOT DATA
# ============================================================
# Period: 27 feb - 5 mrt 2026
period_start = datetime.datetime(2026, 2, 27, 0, 0).timestamp()
period_end = datetime.datetime(2026, 3, 6, 0, 0).timestamp()

# Closed trades in period
bot_closed_in_period = []
for t in closed_trades:
    ts = t.get("timestamp", 0)
    if period_start <= ts <= period_end:
        bot_closed_in_period.append(t)

# Open trades
bot_open_in_period = {}
for market, t in open_trades.items():
    ts = t.get("opened_ts", t.get("timestamp", 0))
    if period_start <= ts <= period_end:
        bot_open_in_period[market] = t

print("=" * 80)
print("VERGELIJKING BITVAVO ECHTE TRANSACTIES vs BOT DATA")
print("Periode: 27 feb 2026 - 5 mrt 2026")
print("=" * 80)

# ============================================================
# 5. COMPARE SELLS
# ============================================================
print("\n" + "=" * 80)
print("A. VERKOPEN (SELLS) VERGELIJKING")
print("=" * 80)

# Group real sells
all_real_sell_markets = sorted(set(real_sells.keys()))
all_bot_sell_markets = sorted(set(t["market"].replace("-EUR","") for t in bot_closed_in_period if t.get("sell_price", 0) > 0))

print(f"\nEchte Bitvavo verkopen: {sum(len(v) for v in real_sells.values())} transacties over {len(all_real_sell_markets)} markten")
print(f"Bot gesloten trades (met sell): {len([t for t in bot_closed_in_period if t.get('sell_price',0) > 0])} trades over {len(all_bot_sell_markets)} markten")

# Detailed sell comparison
print("\n--- DETAIL PER MARKT ---")
all_sell_markets = sorted(set(all_real_sell_markets) | set(all_bot_sell_markets))

total_real_sell_eur = 0
total_bot_sell_eur = 0

for market in all_sell_markets:
    print(f"\n  {market}:")
    
    # Real sells
    if market in real_sells:
        for date_str, amount, eur in real_sells[market]:
            price = eur / amount if amount else 0
            print(f"    BITVAVO VERKOOP: {date_str} | {amount:.8f} @ €{price:.6f} = €{eur:.2f}")
            total_real_sell_eur += eur
    else:
        print(f"    BITVAVO: GEEN verkopen")
    
    # Bot sells
    bot_sells_market = [t for t in bot_closed_in_period 
                       if t["market"].replace("-EUR","") == market 
                       and t.get("sell_price", 0) > 0]
    if bot_sells_market:
        for t in bot_sells_market:
            sell_eur = t["sell_price"] * t["amount"]
            profit = t.get("profit", 0)
            reason = t.get("reason", "?")
            ts = t.get("timestamp", 0)
            dt = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "?"
            print(f"    BOT VERKOOP:     {dt} | {t['amount']:.8f} @ €{t['sell_price']:.6f} = €{sell_eur:.2f} | profit=€{profit:.4f} | reason={reason}")
            total_bot_sell_eur += sell_eur
    else:
        print(f"    BOT: GEEN verkopen in deze periode")
    
    # Match analysis
    if market in real_sells and bot_sells_market:
        real_total_amount = sum(a for _,a,_ in real_sells[market])
        bot_total_amount = sum(t["amount"] for t in bot_sells_market)
        real_total_eur = sum(e for _,_,e in real_sells[market])
        bot_total_eur = sum(t["sell_price"] * t["amount"] for t in bot_sells_market)
        
        amount_diff = real_total_amount - bot_total_amount
        eur_diff = real_total_eur - bot_total_eur
        
        if abs(amount_diff) > 0.001 * max(real_total_amount, 0.001) or abs(eur_diff) > 0.10:
            print(f"    ⚠️  VERSCHIL: Bitvavo amt={real_total_amount:.8f} (€{real_total_eur:.2f}) vs Bot amt={bot_total_amount:.8f} (€{bot_total_eur:.2f})")
            print(f"         Diff: {amount_diff:.8f} tokens, €{eur_diff:.2f}")
        else:
            print(f"    ✅ MATCH: Amounts en EUR komen overeen")

print(f"\n  TOTAAL verkoop-opbrengst Bitvavo: €{total_real_sell_eur:.2f}")
print(f"  TOTAAL verkoop-opbrengst Bot:     €{total_bot_sell_eur:.2f}")

# ============================================================
# 6. COMPARE BUYS
# ============================================================
print("\n" + "=" * 80)
print("B. AANKOPEN (BUYS) VERGELIJKING")
print("=" * 80)

all_real_buy_markets = sorted(set(real_buys.keys()))
total_real_buy_eur = 0

# Check which buys the bot tracks
print("\n--- DETAIL PER MARKT ---")
for market in sorted(set(all_real_buy_markets)):
    print(f"\n  {market}:")
    
    real_buy_total_eur = 0
    real_buy_total_amount = 0
    for date_str, amount, eur in real_buys[market]:
        price = eur / amount if amount else 0
        print(f"    BITVAVO KOOP: {date_str} | {amount:.8f} @ €{price:.6f} = €{eur:.2f}")
        real_buy_total_eur += eur
        real_buy_total_amount += amount
        total_real_buy_eur += eur
    
    # Check in open trades
    bot_key = f"{market}-EUR"
    if bot_key in open_trades:
        ot = open_trades[bot_key]
        bot_invested = ot.get("invested_eur", ot.get("total_invested_eur", 0))
        bot_amount = ot.get("amount", 0)
        bot_buy_price = ot.get("buy_price", 0)
        dca = ot.get("dca_buys", 0)
        opened = ot.get("opened_ts", 0)
        dt = datetime.datetime.fromtimestamp(opened).strftime("%Y-%m-%d %H:%M") if opened else "?"
        print(f"    BOT OPEN:     opened={dt} | amt={bot_amount:.8f} | avg_price=€{bot_buy_price:.6f} | invested=€{bot_invested:.2f} | dca={dca}")
        
        if abs(real_buy_total_amount - bot_amount) > 0.001 * max(real_buy_total_amount, 0.001):
            print(f"    ⚠️  AMOUNT VERSCHIL: Bitvavo={real_buy_total_amount:.8f} vs Bot={bot_amount:.8f}")
        if abs(real_buy_total_eur - bot_invested) > 0.50:
            print(f"    ⚠️  INVEST VERSCHIL: Bitvavo=€{real_buy_total_eur:.2f} vs Bot=€{bot_invested:.2f}")
    
    # Check in closed trades that were bought in period
    bot_closed_market = [t for t in bot_closed_in_period 
                        if t["market"].replace("-EUR","") == market]
    for t in bot_closed_market:
        invested = t.get("invested_eur", t.get("total_invested_eur", 0))
        print(f"    BOT GESLOTEN:  amt={t['amount']:.8f} | buy=€{t['buy_price']:.6f} | sell=€{t.get('sell_price',0):.6f} | invested=€{invested:.2f} | reason={t.get('reason','?')}")

print(f"\n  TOTAAL aankopen Bitvavo: €{total_real_buy_eur:.2f}")

# ============================================================
# 7. PROFIT/LOSS COMPARISON
# ============================================================
print("\n" + "=" * 80)
print("C. WINST/VERLIES VERGELIJKING (gesloten trades in periode)")
print("=" * 80)

# Calculate real P&L per completed round-trip
print("\n--- BOT P&L per gesloten trade ---")
total_bot_profit = 0
total_bot_profit_calc = 0
for t in bot_closed_in_period:
    if t.get("sell_price", 0) > 0 and t.get("reason") not in ("sync_removed", "auto_free_slot"):
        market = t["market"].replace("-EUR", "")
        profit = t.get("profit", 0)
        profit_calc = t.get("profit_calculated", profit)
        invested = t.get("invested_eur", t.get("total_invested_eur", 0))
        sell_revenue = t["sell_price"] * t["amount"]
        actual_profit = sell_revenue - invested
        ts = t.get("timestamp", 0)
        dt = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "?"
        
        print(f"  {market:10s} | {dt} | invested=€{invested:.2f} | revenue=€{sell_revenue:.2f} | bot_profit=€{profit:.4f} | bot_calc=€{profit_calc:.4f} | actual=€{actual_profit:.4f}")
        
        if abs(profit - actual_profit) > 0.50:
            print(f"    ⚠️  PROFIT VERSCHIL: bot zegt €{profit:.4f}, werkelijk €{actual_profit:.4f} (diff €{profit - actual_profit:.4f})")
        
        total_bot_profit += profit
        total_bot_profit_calc += profit_calc

print(f"\n  Bot totaal profit (profit veld):      €{total_bot_profit:.4f}")
print(f"  Bot totaal profit (profit_calculated): €{total_bot_profit_calc:.4f}")

# ============================================================
# 8. REAL P&L CALCULATION
# ============================================================
print("\n" + "=" * 80)
print("D. ECHTE P&L BEREKENING UIT BITVAVO DATA")
print("=" * 80)

# Match buy→sell pairs by market and amount
print("\nPer markt round-trip:")
total_real_profit = 0

# Group by market
all_markets = sorted(set(list(real_buys.keys()) + list(real_sells.keys())))

for market in all_markets:
    buys = sorted(real_buys.get(market, []), key=lambda x: x[0])
    sells = sorted(real_sells.get(market, []), key=lambda x: x[0])
    
    if not sells:
        total_buy = sum(e for _,_,e in buys)
        print(f"  {market:10s} | Alleen kopen: €{total_buy:.2f} geinvesteerd (nog open of verkocht buiten periode)")
        continue
    
    if not buys:
        total_sell = sum(e for _,_,e in sells)
        print(f"  {market:10s} | Alleen verkopen: €{total_sell:.2f} ontvangen (gekocht voor deze periode)")
        continue
    
    total_buy = sum(e for _,_,e in buys)
    total_sell = sum(e for _,_,e in sells)
    pnl = total_sell - total_buy
    total_real_profit += pnl
    
    status = "WINST" if pnl >= 0 else "VERLIES"
    print(f"  {market:10s} | Gekocht: €{total_buy:.2f} | Verkocht: €{total_sell:.2f} | P&L: €{pnl:.2f} ({status})")

print(f"\n  TOTAAL echte P&L (buy-sell verschil): €{total_real_profit:.2f}")

# ============================================================
# 9. MISSING TRADES
# ============================================================
print("\n" + "=" * 80)
print("E. ONTBREKENDE TRADES")
print("=" * 80)

# Markets in real data but not in bot
real_markets = set(m for _,_,m,_,_ in real_txns)
bot_markets_open = set(k.replace("-EUR","") for k in open_trades.keys())
bot_markets_closed = set(t["market"].replace("-EUR","") for t in bot_closed_in_period)
bot_markets_all = bot_markets_open | bot_markets_closed

missing_in_bot = real_markets - bot_markets_all
extra_in_bot = bot_markets_all - real_markets

if missing_in_bot:
    print(f"\n  Markten in BITVAVO maar NIET in bot: {sorted(missing_in_bot)}")
    for m in sorted(missing_in_bot):
        buys = real_buys.get(m, [])
        sells = real_sells.get(m, [])
        total_buy = sum(e for _,_,e in buys)
        total_sell = sum(e for _,_,e in sells)
        print(f"    {m}: {len(buys)} kopen (€{total_buy:.2f}), {len(sells)} verkopen (€{total_sell:.2f})")

if extra_in_bot:
    print(f"\n  Markten in BOT maar NIET in Bitvavo data: {sorted(extra_in_bot)}")

# ============================================================
# 10. SUMMARY
# ============================================================
print("\n" + "=" * 80)
print("F. SAMENVATTING")
print("=" * 80)

print(f"\n  Bitvavo transacties totaal: {len(real_txns)}")
print(f"    Kopen:    {sum(1 for _,t,_,_,_ in real_txns if t=='buy')} txns, €{sum(e for _,t,_,_,e in real_txns if t=='buy'):.2f}")
print(f"    Verkopen: {sum(1 for _,t,_,_,_ in real_txns if t=='sell')} txns, €{sum(e for _,t,_,_,e in real_txns if t=='sell'):.2f}")

print(f"\n  Bot closed trades in periode: {len(bot_closed_in_period)}")
print(f"    Met verkoop: {len([t for t in bot_closed_in_period if t.get('sell_price',0) > 0 and t.get('reason') not in ('sync_removed','auto_free_slot')])}")
print(f"    sync_removed: {len([t for t in bot_closed_in_period if t.get('reason') == 'sync_removed'])}")
print(f"    auto_free_slot: {len([t for t in bot_closed_in_period if t.get('reason') == 'auto_free_slot'])}")

print(f"\n  Bot open trades: {len(open_trades)}")
for k, v in open_trades.items():
    print(f"    {k}: amt={v.get('amount',0):.8f}, invested=€{v.get('invested_eur',0):.2f}")

print(f"\n  Bot totaal winst (profit veld):       €{total_bot_profit:.4f}")
print(f"  Echte P&L (Bitvavo buy-sell verschil): €{total_real_profit:.2f}")
print(f"  VERSCHIL:                              €{total_bot_profit - total_real_profit:.2f}")

if __name__ == "__main__":
    pass
