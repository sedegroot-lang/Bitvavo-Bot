"""
Grondige analyse van bot prestaties en identificatie van verbeterpunten voor maximale winst.
"""
import json
from datetime import datetime, timedelta
from collections import defaultdict
import statistics

def load_json(path, default):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return default

def analyze_trades():
    trades = load_json('data/trade_log.json', {'closed_trades': []})
    closed = [t for t in trades.get('closed_trades', []) 
              if t.get('close_reason') not in ['sync_removed', 'manual_close']]
    
    if not closed:
        return {
            'total_trades': 0,
            'error': 'Geen closed trades gevonden'
        }
    
    wins = [t for t in closed if t.get('profit', 0) > 0]
    losses = [t for t in closed if t.get('profit', 0) < 0]
    
    total_profit = sum(t.get('profit', 0) for t in closed)
    avg_win = sum(t['profit'] for t in wins)/len(wins) if wins else 0
    avg_loss = sum(t['profit'] for t in losses)/len(losses) if losses else 0
    
    # DCA effectiviteit
    trades_with_dca = [t for t in closed if t.get('dca_buys', 0) > 0]
    dca_win_rate = len([t for t in trades_with_dca if t['profit'] > 0])/len(trades_with_dca)*100 if trades_with_dca else 0
    
    # Exit redenen analyse
    exit_reasons = defaultdict(int)
    exit_profits = defaultdict(list)
    for t in closed:
        reason = t.get('close_reason', 'unknown')
        exit_reasons[reason] += 1
        exit_profits[reason].append(t.get('profit', 0))
    
    # Tijd tot profit/loss
    hold_times_win = []
    hold_times_loss = []
    for t in closed:
        if 'opened_ts' in t and 'timestamp' in t:
            hold_time = (t['timestamp'] - t['opened_ts']) / 3600  # uren
            if t['profit'] > 0:
                hold_times_win.append(hold_time)
            else:
                hold_times_loss.append(hold_time)
    
    # Market analyse
    market_performance = defaultdict(lambda: {'wins': 0, 'losses': 0, 'profit': 0})
    for t in closed:
        market = t.get('market', 'unknown')
        if t['profit'] > 0:
            market_performance[market]['wins'] += 1
        else:
            market_performance[market]['losses'] += 1
        market_performance[market]['profit'] += t['profit']
    
    return {
        'total_trades': len(closed),
        'win_rate': len(wins)/len(closed)*100,
        'wins': len(wins),
        'losses': len(losses),
        'total_profit': total_profit,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'risk_reward': abs(avg_win/avg_loss) if avg_loss != 0 else 0,
        'trades_with_dca': len(trades_with_dca),
        'dca_win_rate': dca_win_rate,
        'avg_hold_time_win': statistics.mean(hold_times_win) if hold_times_win else 0,
        'avg_hold_time_loss': statistics.mean(hold_times_loss) if hold_times_loss else 0,
        'exit_reasons': dict(exit_reasons),
        'exit_profits': {k: sum(v)/len(v) for k, v in exit_profits.items()},
        'market_performance': dict(market_performance),
        'best_markets': sorted(market_performance.items(), key=lambda x: x[1]['profit'], reverse=True)[:5],
        'worst_markets': sorted(market_performance.items(), key=lambda x: x[1]['profit'])[:5]
    }

def analyze_config():
    cfg = load_json('config/bot_config.json', {})
    
    issues = []
    recommendations = []
    
    # Trailing stop analyse
    trailing = cfg.get('DEFAULT_TRAILING', 0.04)
    if trailing > 0.05:
        issues.append("⚠️ DEFAULT_TRAILING te breed (>5%) - laat te veel winst liggen")
        recommendations.append("→ Verlaag naar 3-4% voor snellere wins")
    elif trailing < 0.02:
        issues.append("⚠️ DEFAULT_TRAILING te krap (<2%) - te vroeg verkopen")
        recommendations.append("→ Verhoog naar 3-4% voor grotere wins")
    
    # DCA analyse
    dca_enabled = cfg.get('DCA_ENABLED', False)
    dca_max = cfg.get('DCA_MAX_BUYS', 0)
    dca_drop = cfg.get('DCA_DROP_PCT', 0.04)
    
    if not dca_enabled:
        issues.append("⚠️ DCA uitgeschakeld - geen recovery mogelijk bij dips")
        recommendations.append("→ Schakel DCA in met 2-3 max buys")
    elif dca_max < 2:
        issues.append("⚠️ DCA_MAX_BUYS te laag - onvoldoende recovery power")
        recommendations.append("→ Verhoog naar 2-3 voor betere recovery")
    
    if dca_drop < 0.03:
        issues.append("⚠️ DCA_DROP_PCT te laag (<3%) - te snel DCA triggeren")
        recommendations.append("→ Verhoog naar 4-5% voor echte dips")
    
    # Position sizing
    base_amount = cfg.get('BASE_AMOUNT_EUR', 10)
    max_exposure = cfg.get('MAX_TOTAL_EXPOSURE_EUR', 100)
    max_trades = cfg.get('MAX_OPEN_TRADES', 3)
    
    if base_amount * max_trades > max_exposure * 0.8:
        issues.append("⚠️ Te groot risico per trade vs max exposure")
        recommendations.append("→ Verlaag BASE_AMOUNT_EUR of verhoog MAX_TOTAL_EXPOSURE_EUR")
    
    # RSI filters
    rsi_min = cfg.get('RSI_MIN_BUY', 30)
    rsi_max = cfg.get('RSI_MAX_BUY', 70)
    
    if rsi_max - rsi_min < 20:
        issues.append("⚠️ RSI range te smal - te weinig trade opportunities")
        recommendations.append("→ Verbreed RSI range voor meer kansen")
    
    # Stop loss
    hard_sl = cfg.get('HARD_SL_ALT_PCT', 0.1)
    if hard_sl > 0.08:
        issues.append("⚠️ HARD_SL_ALT_PCT te groot (>8%) - te veel verlies per trade")
        recommendations.append("→ Verlaag naar 5-6% voor betere risk control")
    
    return {
        'config': {
            'trailing': trailing,
            'dca_enabled': dca_enabled,
            'dca_max': dca_max,
            'dca_drop': dca_drop,
            'base_amount': base_amount,
            'max_exposure': max_exposure,
            'max_trades': max_trades,
            'rsi_range': (rsi_min, rsi_max),
            'hard_sl': hard_sl
        },
        'issues': issues,
        'recommendations': recommendations
    }

def analyze_ai_performance():
    changes = load_json('ai/ai_changes.json', [])
    suggestions = load_json('ai/ai_suggestions.json', {})
    
    # Welke parameters past AI het meest aan?
    param_counts = defaultdict(int)
    for change in changes:
        param_counts[change['param']] += 1
    
    # Check of AI recent actief is
    latest_ts = changes[0]['ts'] if changes else 0
    minutes_ago = (time.time() - latest_ts) / 60 if latest_ts else 999
    
    return {
        'total_changes': len(changes),
        'most_changed': sorted(param_counts.items(), key=lambda x: x[1], reverse=True)[:5],
        'minutes_since_last': minutes_ago,
        'is_active': minutes_ago < 10
    }

def generate_optimization_plan(trade_stats, config_analysis, ai_stats):
    """Genereer concrete actieplan voor maximale winst."""
    
    print("\n" + "="*80)
    print("🎯 BOT OPTIMALISATIE PLAN - MAXIMALE WINST")
    print("="*80)
    
    # Prioriteit 1: Critical Issues
    print("\n🔴 PRIORITEIT 1 - CRITICAL (Direct implementeren)")
    print("-" * 80)
    
    if trade_stats.get('error'):
        print(f"❌ {trade_stats['error']}")
        print("   → Geen data voor analyse, bot nog niet actief geweest")
    else:
        # Win rate analyse
        if trade_stats['win_rate'] < 50:
            print(f"❌ Win rate te laag: {trade_stats['win_rate']:.1f}%")
            print("   → Target: >55% voor winstgevend systeem")
            print("   → Actie: Scherper entry filters (hogere MIN_SCORE_TO_BUY)")
        
        # Risk/Reward analyse
        if trade_stats['risk_reward'] < 1.5:
            print(f"❌ Risk/Reward ratio te laag: {trade_stats['risk_reward']:.2f}")
            print("   → Target: >2.0 voor gezonde groei")
            print("   → Actie: Wijdere trailing stop of strenger stop-loss")
        
        # DCA effectiviteit
        if trade_stats['trades_with_dca'] > 0:
            if trade_stats['dca_win_rate'] < 60:
                print(f"❌ DCA win rate te laag: {trade_stats['dca_win_rate']:.1f}%")
                print("   → Target: >70% voor effectieve DCA")
                print("   → Actie: Hogere DCA_DROP_PCT of betere timing")
    
    for issue in config_analysis['issues']:
        print(f"{issue}")
    
    # Prioriteit 2: Performance Verbeteringen
    print("\n🟡 PRIORITEIT 2 - PERFORMANCE (Verhoogt winst)")
    print("-" * 80)
    
    for rec in config_analysis['recommendations']:
        print(f"{rec}")
    
    if not trade_stats.get('error'):
        # Exit strategie optimalisatie
        exit_analysis = trade_stats.get('exit_profits', {})
        if 'trailing' in exit_analysis and 'hard_sl' in exit_analysis:
            trailing_profit = exit_analysis.get('trailing', 0)
            sl_profit = exit_analysis.get('hard_sl', 0)
            
            if abs(sl_profit) > abs(trailing_profit):
                print("⚠️ Meer verlies via stop-loss dan winst via trailing")
                print("   → Actie: Optimaliseer entry timing of verlaag stop-loss")
        
        # Hold time analyse
        if trade_stats['avg_hold_time_loss'] > trade_stats['avg_hold_time_win'] * 2:
            print("⚠️ Verliezende trades duren 2x langer dan winners")
            print("   → Actie: Snellere stop-loss of time-based exit")
    
    # Prioriteit 3: AI Optimalisatie
    print("\n🔵 PRIORITEIT 3 - AI OPTIMALISATIE (Lang termijn)")
    print("-" * 80)
    
    if not ai_stats['is_active']:
        print("❌ AI Supervisor niet actief!")
        print("   → Start ai_supervisor.py voor automatische optimalisatie")
    else:
        print(f"✅ AI actief (laatste wijziging {ai_stats['minutes_since_last']:.0f} min geleden)")
        print(f"   Totaal wijzigingen: {ai_stats['total_changes']}")
        print("   Meest aangepaste parameters:")
        for param, count in ai_stats['most_changed'][:3]:
            print(f"      • {param}: {count}x")
    
    # Market selectie optimalisatie
    if not trade_stats.get('error'):
        print("\n📊 Market Performance:")
        print("   Top 3 performers:")
        for market, stats in trade_stats['best_markets'][:3]:
            wr = stats['wins'] / (stats['wins'] + stats['losses']) * 100 if (stats['wins'] + stats['losses']) > 0 else 0
            print(f"      • {market}: €{stats['profit']:.2f} ({wr:.0f}% WR)")
        
        print("   Slechtste performers (overweeg uitsluiten):")
        for market, stats in trade_stats['worst_markets'][:3]:
            if stats['profit'] < -5:
                wr = stats['wins'] / (stats['wins'] + stats['losses']) * 100 if (stats['wins'] + stats['losses']) > 0 else 0
                print(f"      • {market}: €{stats['profit']:.2f} ({wr:.0f}% WR) ❌")
    
    # Concrete configuratie voorstellen
    print("\n" + "="*80)
    print("⚙️  VOORGESTELDE CONFIG AANPASSINGEN")
    print("="*80)
    
    cfg = config_analysis['config']
    
    print("\nOPTIMALE SETTINGS voor maximale winst:")
    print(f"""
    # Risk Management (Conservatief maar winstgevend)
    "HARD_SL_ALT_PCT": 0.05,           # 5% max loss (was: {cfg['hard_sl']})
    "HARD_SL_BTCETH_PCT": 0.025,       # 2.5% voor BTC/ETH
    
    # Trailing Stop (Balans tussen vasthouden en zekerheid)
    "DEFAULT_TRAILING": 0.035,         # 3.5% trailing (was: {cfg['trailing']})
    "TRAILING_ACTIVATION_PCT": 0.02,   # Activeer bij 2% winst
    
    # DCA (Agressieve recovery)
    "DCA_ENABLED": true,               # (was: {cfg['dca_enabled']})
    "DCA_MAX_BUYS": 3,                 # 3 DCA levels (was: {cfg['dca_max']})
    "DCA_DROP_PCT": 0.04,              # Bij 4% dip (was: {cfg['dca_drop']})
    "DCA_SIZE_MULTIPLIER": 1.5,        # Elke DCA 1.5x groter
    
    # Position Sizing (Gebalanceerd)
    "BASE_AMOUNT_EUR": 15,             # Start positie (was: {cfg['base_amount']})
    "MAX_OPEN_TRADES": 4,              # Meer spreiding (was: {cfg['max_trades']})
    "MAX_TOTAL_EXPOSURE_EUR": 150,     # Hogere limiet (was: {cfg['max_exposure']})
    
    # Entry Filters (Selectiever = hoger win rate)
    "MIN_SCORE_TO_BUY": 12,            # Hogere drempel
    "RSI_MIN_BUY": 35,                 # RSI range 35-45
    "RSI_MAX_BUY": 45,
    
    # AI Optimalisatie
    "AI_AUTO_APPLY": true,             # Laat AI optimaliseren
    "AI_APPLY_COOLDOWN_MIN": 60,       # Sneller reageren (was: 120)
    """)
    
    print("\n" + "="*80)
    print("💡 EXTRA VERBETERINGEN")
    print("="*80)
    print("""
    1. VOLUME FILTERING
       → Verhoog MIN_AVG_VOLUME_1M voor betere liquiditeit
       → Voorkomt slechte fills en hoge spreads
    
    2. TIME-BASED FILTERS
       → Implementeer "beste uren" filtering
       → Handel alleen tijdens hoge volume periodes
    
    3. CORRELATION FILTERING
       → Gebruik AI correlation matrix
       → Voorkom te veel gecorreleerde posities
    
    4. DYNAMIC POSITION SIZING
       → Grotere posities bij hoge confidence
       → Kleinere posities bij onzekerheid
    
    5. PARTIAL TAKE-PROFIT
       → Verkoop 50% bij 3% winst
       → Laat 50% lopen met trailing stop
       → Best of both worlds!
    
    6. BLACKLIST FUNCTIONALITEIT
       → Voeg markets toe die consistent verliezen
       → Automatisch via AI na X losses
    """)

if __name__ == '__main__':
    import time
    
    print("\n🔍 Analyseren van bot prestaties...")
    trade_stats = analyze_trades()
    
    print("📋 Analyseren van configuratie...")
    config_analysis = analyze_config()
    
    print("🤖 Analyseren van AI performance...")
    ai_stats = analyze_ai_performance()
    
    # Genereer optimalisatie plan
    generate_optimization_plan(trade_stats, config_analysis, ai_stats)
    
    print("\n" + "="*80)
    print("✅ ANALYSE COMPLEET")
    print("="*80)
    print("\nVolgende stappen:")
    print("1. Review de voorgestelde aanpassingen")
    print("2. Implementeer prioriteit 1 items eerst")
    print("3. Test met kleine posities")
    print("4. Monitor resultaten 48 uur")
    print("5. Pas bij positieve resultaten aan")
