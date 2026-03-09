"""
Test script voor nieuwe AI Portfolio functies
"""
import json
import sys
from modules.ai_engine import AIEngine

def main():
    print("=" * 60)
    print("AI PORTFOLIO ANALYSE TEST")
    print("=" * 60)
    
    engine = AIEngine()
    
    # Test 1: Portfolio status
    print("\n📊 TEST 1: Portfolio Status")
    print("-" * 60)
    portfolio = engine.get_portfolio_status()
    if 'error' in portfolio:
        print(f"❌ Error: {portfolio['error']}")
    else:
        print(f"💰 Totale waarde: €{portfolio['total_value_eur']:.2f}")
        print(f"📈 Aantal posities: {portfolio['num_positions']}")
        print(f"💵 Cash %: {portfolio['cash_pct']:.1f}%")
        print(f"\nTop 5 posities:")
        for i, pos in enumerate(portfolio['positions'][:5], 1):
            symbol = pos['symbol']
            value = pos['value_eur']
            alloc = pos['allocation_pct']
            print(f"  {i}. {symbol:6s}: €{value:8.2f} ({alloc:5.1f}%)")
    
    # Test 2: Risk Analysis
    print("\n⚠️  TEST 2: Risk Analysis")
    print("-" * 60)
    if 'error' not in portfolio:
        risk = engine.analyze_portfolio_risk(portfolio)
        print(f"Risk Level: {risk['risk_level'].upper()}")
        print(f"Risk Score: {risk['risk_score']:.1f}")
        if risk['warnings']:
            print(f"\nWaarschuwingen ({len(risk['warnings'])}):")
            for w in risk['warnings']:
                severity = w['severity'].upper()
                msg = w['message']
                print(f"  [{severity}] {msg}")
        else:
            print("\n✅ Geen waarschuwingen")
    
    # Test 3: Position sizing voor top markets
    print("\n💡 TEST 3: Position Sizing voor Top Markets")
    print("-" * 60)
    if 'error' not in portfolio:
        markets = engine.get_whitelist()[:5]
        print(f"Analyseer {len(markets)} markets...")
        for market in markets:
            size_info = engine.calculate_optimal_position_size(market, portfolio)
            if size_info['recommended_eur'] > 0:
                rec_size = size_info['recommended_eur']
                atr = size_info.get('atr_pct', 0)
                reason = size_info.get('reason', '')
                print(f"\n{market}:")
                print(f"  Aanbevolen: €{rec_size:.2f}")
                print(f"  Volatility: {atr:.2f}%")
                print(f"  Reden: {reason}")
    
    # Test 4: Complete Investment Recommendations
    print("\n🎯 TEST 4: Complete Investment Recommendations")
    print("-" * 60)
    recommendations = engine.get_investment_recommendations()
    if 'error' in recommendations:
        print(f"❌ Error: {recommendations['error']}")
    else:
        print("\n" + recommendations.get('summary', 'Geen samenvatting'))
        
        print("\n\nTop 3 Kansen:")
        for i, rec in enumerate(recommendations['recommendations'][:3], 1):
            market = rec['market']
            size = rec['recommended_size_eur']
            score = rec['score']
            vol = rec['volatility_pct']
            print(f"\n{i}. {market}")
            print(f"   Score: {score:.3f}")
            print(f"   Size: €{size:.2f}")
            print(f"   Volatility: {vol:.2f}%")
            if rec.get('factors'):
                print(f"   Factors:")
                for f in rec['factors'][:2]:
                    print(f"     - {f['feature']}: {f['impact']:.3f}")
    
    # Save results
    print("\n" + "=" * 60)
    print("💾 Opslaan resultaten...")
    with open('ai_portfolio_test_results.json', 'w', encoding='utf-8') as f:
        json.dump({
            'portfolio': portfolio,
            'recommendations': recommendations
        }, f, indent=2, ensure_ascii=False)
    print("✅ Opgeslagen in: ai_portfolio_test_results.json")
    
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
