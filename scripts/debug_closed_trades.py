"""Debug closed trades rendering"""
import json
from datetime import datetime

trade_log_path = "C:/Users/Sedeg/OneDrive/Dokumente/Bitvavo Bot/data/trade_log.json"
data = json.load(open(trade_log_path, encoding='utf-8'))

closed_trades_raw = data.get('closed', [])
closed_trades_sorted = sorted(closed_trades_raw, key=lambda x: x.get('timestamp', 0), reverse=True)[:10]

print("=" * 80)
print("CLOSED TRADES PROCESSING DEBUG")
print("=" * 80)

closed_trades = []
for i, trade in enumerate(closed_trades_sorted, 1):
    print(f"\n{i}. Processing trade: {trade.get('market')}")
    
    amount = float(trade.get('amount', 0) or 0)
    buy_price = float(trade.get('buy_price', 0) or 0)
    sell_price = float(trade.get('sell_price', 0) or 0)
    
    # Calculate invested
    invested = float(trade.get('total_invested_eur') or trade.get('initial_invested_eur') or 0)
    if invested == 0 and buy_price > 0 and amount > 0:
        invested = buy_price * amount
    
    print(f"   amount: {amount}")
    print(f"   buy_price: {buy_price}")
    print(f"   sell_price: {sell_price}")
    print(f"   total_invested_eur: {trade.get('total_invested_eur', 'NOT SET')}")
    print(f"   initial_invested_eur: {trade.get('initial_invested_eur', 'NOT SET')}")
    print(f"   invested (calculated): €{invested:.2f}")
    
    # Check dust filter
    if invested < 0.01:
        print(f"   ❌ SKIPPED (dust trade, invested < €0.01)")
        continue
    else:
        print(f"   ✅ INCLUDED (invested >= €0.01)")
    
    sold_for = amount * sell_price if sell_price > 0 else 0
    profit = float(trade.get('profit', 0) or 0)
    
    if profit == 0 and sell_price > 0 and invested > 0:
        profit = sold_for - invested
    
    ts = trade.get('timestamp', 0)
    try:
        closed_date = datetime.fromtimestamp(ts).strftime('%d-%m %H:%M') if ts else 'Onbekend'
    except:
        closed_date = 'Onbekend'
    
    closed_trades.append({
        'market': trade.get('market', 'N/A'),
        'invested': invested,
        'profit': profit,
        'closed_date': closed_date,
    })

print("\n" + "=" * 80)
print(f"RESULT: {len(closed_trades)} trades passed filter")
print("=" * 80)

for i, trade in enumerate(closed_trades, 1):
    print(f"{i}. {trade['market']}: €{trade['invested']:.2f} invested, €{trade['profit']:.2f} profit, {trade['closed_date']}")
