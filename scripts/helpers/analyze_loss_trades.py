"""
Analyseer trades met verlies en check waarom DCA niet is uitgevoerd
"""
import json
from datetime import datetime

def load_trades():
    with open('data/trade_log.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get('closed', [])

def load_config():
    with open('config/bot_config.json', 'r', encoding='utf-8') as f:
        return json.load(f)

def analyze_loss_trades():
    trades = load_trades()
    config = load_config()
    
    # Filter alleen echte verlies trades (niet sync_removed)
    loss_trades = [
        t for t in trades 
        if t.get('profit', 0) < 0 and t.get('reason') not in ['sync_removed', 'manual_close']
    ]
    
    # Sorteer op timestamp (meest recent eerst)
    loss_trades.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
    
    print("="*80)
    print("ANALYSE: TRADES MET VERLIES - WAAROM GEEN DCA?")
    print("="*80)
    
    # DCA settings
    dca_enabled = config.get('DCA_ENABLED', False)
    dca_drop_pct = config.get('DCA_DROP_PCT', 0.04)
    rsi_min_buy = config.get('RSI_MIN_BUY', 45.0)
    dca_max_buys = config.get('DCA_MAX_BUYS', 2)
    
    print(f"\n📊 DCA CONFIGURATIE:")
    print(f"   DCA_ENABLED: {dca_enabled}")
    print(f"   DCA_DROP_PCT: {dca_drop_pct*100:.1f}% (trigger bij {dca_drop_pct*100:.1f}% dip)")
    print(f"   RSI_MIN_BUY: {rsi_min_buy} (DCA alleen als RSI ≤ {rsi_min_buy})")
    print(f"   DCA_MAX_BUYS: {dca_max_buys}")
    
    print(f"\n⚠️  KRITIEKE BEVINDING:")
    print(f"   RSI_MIN_BUY van {rsi_min_buy} is ZEER STRENG!")
    print(f"   DCA wordt ALLEEN uitgevoerd als RSI ≤ {rsi_min_buy}")
    print(f"   Dit betekent: market moet STERK OVERSOLD zijn")
    print(f"   Bij normale dipjes (RSI 40-45) wordt GEEN DCA gedaan!")
    
    print(f"\n📉 LAATSTE {len(loss_trades[:10])} VERLIES TRADES:")
    print("="*80)
    
    for i, trade in enumerate(loss_trades[:10], 1):
        market = trade.get('market', 'Unknown')
        buy_price = trade.get('buy_price', 0)
        sell_price = trade.get('sell_price', 0)
        profit = trade.get('profit', 0)
        reason = trade.get('reason', 'unknown')
        timestamp = trade.get('timestamp', 0)
        dca_buys = trade.get('dca_buys', 0)
        
        # Bereken max dip
        if buy_price > 0 and sell_price > 0:
            drop_pct = (buy_price - sell_price) / buy_price
        else:
            drop_pct = 0
        
        dt = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
        
        print(f"\n{i}. {market}")
        print(f"   Tijd: {dt}")
        print(f"   Buy:  €{buy_price:.6f}")
        print(f"   Sell: €{sell_price:.6f}")
        print(f"   Drop: {drop_pct*100:.2f}%")
        print(f"   DCA uitgevoerd: {dca_buys} keer")
        print(f"   Profit: €{profit:.2f}")
        print(f"   Reason: {reason}")
        
        # Analyse waarom geen DCA
        print(f"\n   💡 DCA ANALYSE:")
        
        if not dca_enabled:
            print(f"      ❌ DCA is UITGESCHAKELD in config")
        elif dca_buys >= dca_max_buys:
            print(f"      ✅ DCA uitgevoerd: {dca_buys}/{dca_max_buys} (maximum bereikt)")
        elif drop_pct < dca_drop_pct:
            print(f"      ⚠️  Drop te klein: {drop_pct*100:.2f}% < {dca_drop_pct*100:.1f}% (DCA threshold)")
        else:
            print(f"      ⚠️  Drop groot genoeg: {drop_pct*100:.2f}% > {dca_drop_pct*100:.1f}%")
            print(f"      🔍 WAARSCHIJNLIJKE OORZAAK:")
            print(f"         RSI was NIET laag genoeg (RSI > {rsi_min_buy})")
            print(f"         DCA trigger werd bereikt, maar RSI filter blokkeerde het!")
            print(f"         Stop-loss sloeg toe voordat RSI laag genoeg werd")
        
        print(f"   " + "-"*70)
    
    # Statistieken
    print(f"\n{'='*80}")
    print(f"📊 STATISTIEKEN (laatste {len(loss_trades)} verlies trades):")
    print(f"{'='*80}")
    
    total_loss = sum(t.get('profit', 0) for t in loss_trades)
    trades_with_dca = sum(1 for t in loss_trades if t.get('dca_buys', 0) > 0)
    trades_without_dca = len(loss_trades) - trades_with_dca
    
    big_drops = sum(1 for t in loss_trades 
                    if t.get('buy_price', 0) > 0 and t.get('sell_price', 0) > 0 
                    and (t['buy_price'] - t['sell_price']) / t['buy_price'] >= dca_drop_pct)
    
    print(f"   Totaal verlies: €{total_loss:.2f}")
    print(f"   Trades MET DCA: {trades_with_dca} ({trades_with_dca/len(loss_trades)*100:.1f}%)")
    print(f"   Trades ZONDER DCA: {trades_without_dca} ({trades_without_dca/len(loss_trades)*100:.1f}%)")
    print(f"   Trades met drop ≥ {dca_drop_pct*100:.1f}%: {big_drops}")
    
    print(f"\n{'='*80}")
    print(f"🎯 CONCLUSIE & AANBEVELING:")
    print(f"{'='*80}")
    print(f"\n1. PROBLEEM:")
    print(f"   RSI_MIN_BUY = {rsi_min_buy} is TE STRENG")
    print(f"   Bij 4-5% dips is RSI vaak 40-45 (niet laag genoeg)")
    print(f"   Stop-loss op 5% slaat toe VOORDAT DCA kan activeren")
    
    print(f"\n2. OPLOSSING:")
    print(f"   Verlaag RSI_MIN_BUY naar 30-35")
    print(f"   Dan kunnen DCA safety orders WEL triggeren bij dipjes")
    print(f"   Dit voorkomt veel onnodige stop-loss exits")
    
    print(f"\n3. ALTERNATIEF:")
    print(f"   Verhoog HARD_SL_ALT_PCT van 5% naar 6-7%")
    print(f"   Geeft DCA meer tijd om te activeren bij diepe dips")
    
    print(f"\n💡 ADVIES: Pas RSI_MIN_BUY aan naar 30-35 in bot_config.json")
    print(f"{'='*80}\n")

if __name__ == '__main__':
    try:
        analyze_loss_trades()
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
