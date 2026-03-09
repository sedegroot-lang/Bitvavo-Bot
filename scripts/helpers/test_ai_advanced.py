"""
Test script voor GEAVANCEERDE AI functies
"""
import json
import sys
from modules.ai_engine import AIEngine

def print_section(title):
    print("\n" + "="*70)
    print(f"  {title}")
    print("="*70)

def main():
    print_section("🧠 GEAVANCEERDE AI ANALYSE TEST")
    
    engine = AIEngine()
    
    # Load trade history
    try:
        with open('data/trade_log.json', 'r', encoding='utf-8') as f:
            trade_log = json.load(f)
        trade_history = trade_log.get('closed_trades', [])
        print(f"\n✅ Trade history geladen: {len(trade_history)} trades")
    except Exception as e:
        print(f"\n⚠️  Geen trade history: {e}")
        trade_history = []
    
    # TEST 1: Correlation Analysis
    print_section("📊 TEST 1: Correlatie Analyse")
    print("Analyseer correlaties tussen assets...")
    
    correlation = engine.calculate_correlation_matrix()
    if 'error' in correlation:
        print(f"❌ Error: {correlation['error']}")
    else:
        print(f"\n✅ Diversificatie Score: {correlation['diversification_score']:.1f}/100")
        print(f"   Gemiddelde correlatie: {correlation['avg_correlation']:.3f}")
        
        if correlation['high_correlation_pairs']:
            print(f"\n⚠️  WAARSCHUWING: Hoge correlatie paren gevonden!")
            for pair in correlation['high_correlation_pairs'][:3]:
                print(f"   {pair['market1']} ↔ {pair['market2']}: {pair['correlation']:.3f}")
        else:
            print("\n✅ Goede diversificatie - geen hoge correlaties")
        
        print("\nTop 5 correlaties:")
        for i, corr in enumerate(correlation['correlations'][:5], 1):
            print(f"  {i}. {corr['market1']} ↔ {corr['market2']}: {corr['correlation']:.3f}")
    
    # TEST 2: Win Probability Predictions
    print_section("🎯 TEST 2: Win Probability Predictions")
    markets = engine.get_whitelist()[:5]
    
    for market in markets:
        pred = engine.predict_trade_success(market, trade_history)
        if 'error' in pred:
            print(f"\n{market}: ❌ {pred['error']}")
            continue
        
        prob = pred['win_probability'] * 100
        hist_wr = pred.get('historical_win_rate', 0) * 100
        confidence = pred['confidence']
        num_trades = pred['num_trades']
        
        print(f"\n{market}:")
        print(f"  Win Probability: {prob:.1f}% ({confidence} confidence)")
        print(f"  Historical Win Rate: {hist_wr:.1f}% ({num_trades} trades)")
        
        if 'avg_profit_eur' in pred:
            print(f"  Avg Profit: €{pred['avg_profit_eur']:.2f}")
            print(f"  Avg Loss: €{pred['avg_loss_eur']:.2f}")
            print(f"  Risk/Reward: {pred['risk_reward_ratio']:.2f}")
        
        if 'adjustments' in pred:
            adj = pred['adjustments']
            print(f"  Adjustments: RSI={adj['rsi']:.0f}, Mom={adj['momentum']:.1f}%, Vol={adj['volatility']:.1f}%")
    
    # TEST 3: Momentum Shift Detection
    print_section("🔄 TEST 3: Momentum Shift Detection")
    
    for market in markets[:3]:
        momentum = engine.detect_momentum_shift(market)
        if 'error' in momentum:
            print(f"\n{market}: ❌ {momentum['error']}")
            continue
        
        detected = momentum['shift_detected']
        direction = momentum['direction']
        confidence = momentum['confidence']
        
        if detected:
            emoji = "🚀" if direction == "bullish" else "📉" if direction == "bearish" else "➡️"
            print(f"\n{emoji} {market}: {direction.upper()} shift (confidence: {confidence:.2f})")
            print(f"   {momentum['recommendation']}")
            
            if momentum['signals']:
                print(f"   Signals:")
                for sig in momentum['signals'][:3]:
                    print(f"     - {sig['indicator']}: {sig['signal']} ({sig['strength']:+.2f})")
        else:
            print(f"\n{market}: Geen shift - neutrale trend")
    
    # TEST 4: DCA Timing Optimization
    print_section("💰 TEST 4: DCA Timing Optimization")
    
    if len(markets) > 0:
        market = markets[0]
        print(f"\nTest market: {market}")
        
        # Simulate scenarios
        scenarios = [
            (100, 96, "4% dip"),
            (100, 94, "6% dip"),
            (100, 98, "2% dip"),
        ]
        
        for entry, current, desc in scenarios:
            dca = engine.optimize_dca_timing(market, entry, current)
            if 'error' not in dca:
                rec = dca['recommendation']
                urgency = dca['urgency']
                score = dca['score']
                
                emoji = "🟢" if urgency == "high" else "🟡" if urgency == "medium" else "⚪"
                print(f"\n{emoji} Scenario: {desc}")
                print(f"   Recommendation: {rec.upper()} (urgency: {urgency})")
                print(f"   Score: {score}")
                print(f"   Reasons: {', '.join(dca['reasons'][:3])}")
    
    # TEST 5: Take-Profit Optimization
    print_section("🎯 TEST 5: Take-Profit Optimization")
    
    if len(markets) > 0 and len(trade_history) > 0:
        market = markets[0]
        entry_price = 100.0  # Example
        
        print(f"\nMarket: {market}")
        print(f"Entry Price: €{entry_price:.2f}")
        
        tp = engine.calculate_optimal_take_profit(market, entry_price, trade_history)
        if 'error' not in tp:
            targets = tp['targets']
            target_pct = tp['target_pct']
            sl = tp['recommended_stop_loss']
            sl_pct = tp['stop_loss_pct']
            rr = tp['risk_reward_ratio']
            
            print(f"\nTake-Profit Targets:")
            print(f"  🟢 Conservative: €{targets['conservative']:.2f} (+{target_pct['conservative']:.2f}%)")
            print(f"  🟡 Moderate:     €{targets['moderate']:.2f} (+{target_pct['moderate']:.2f}%)")
            print(f"  🔴 Aggressive:   €{targets['aggressive']:.2f} (+{target_pct['aggressive']:.2f}%)")
            
            print(f"\n🛑 Stop-Loss: €{sl:.2f} (-{sl_pct:.2f}%)")
            print(f"   Risk/Reward Ratio: {rr:.2f}:1")
            
            print(f"\nBased on:")
            based = tp['based_on']
            print(f"  - {based['historical_trades']} historical trades")
            print(f"  - Avg profit: {based['avg_profit_pct']:.2f}%")
            print(f"  - Volatility: {based['current_volatility']:.2f}%")
            
            print(f"\n💡 {tp['recommendation']}")
    
    # TEST 6: Complete Advanced Recommendations
    print_section("🚀 TEST 6: Complete Advanced Analysis")
    
    advanced = engine.get_advanced_recommendations(trade_history)
    if 'error' in advanced:
        print(f"❌ Error: {advanced['error']}")
    else:
        # Correlation summary
        if 'correlation_analysis' in advanced:
            corr = advanced['correlation_analysis']
            if 'error' not in corr:
                print(f"\n📊 Diversificatie: {corr['diversification_score']:.1f}/100")
        
        # Win predictions summary
        if 'win_predictions' in advanced:
            preds = advanced['win_predictions']
            print(f"\n🎯 Top 3 Win Probabilities:")
            for i, pred in enumerate(preds[:3], 1):
                prob = pred['win_probability'] * 100
                conf = pred['confidence']
                print(f"  {i}. {pred['market']}: {prob:.1f}% ({conf})")
        
        # Momentum shifts summary
        if 'momentum_shifts' in advanced:
            shifts = advanced['momentum_shifts']
            if shifts:
                print(f"\n🔄 Momentum Shifts Detected: {len(shifts)}")
                for shift in shifts[:3]:
                    print(f"  - {shift['market']}: {shift['direction'].upper()}")
                    print(f"    {shift['recommendation']}")
            else:
                print("\n🔄 Geen significante momentum shifts")
        
        # Save results
        print("\n" + "="*70)
        with open('ai_advanced_test_results.json', 'w', encoding='utf-8') as f:
            json.dump(advanced, f, indent=2, ensure_ascii=False)
        print("💾 Resultaten opgeslagen in: ai_advanced_test_results.json")
    
    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Gestopt door gebruiker")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
