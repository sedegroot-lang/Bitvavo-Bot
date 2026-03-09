"""
Visualiseer AI impact - welke parameters zijn aangepast en hoe vaak
"""
import json
from datetime import datetime
from collections import Counter

def main():
    # Load changes
    with open('ai/ai_changes.json', 'r', encoding='utf-8') as f:
        changes = json.load(f)
    
    print("="*80)
    print("AI IMPACT ANALYSE - ALLE TOEGEPASTE WIJZIGINGEN")
    print("="*80)
    
    # Count per parameter
    param_counts = Counter([c['param'] for c in changes])
    
    print(f"\n📊 OVERZICHT: {len(changes)} totale wijzigingen toegepast\n")
    print("Parameter                      | Aantal wijzigingen | % van totaal")
    print("-" * 80)
    
    for param, count in param_counts.most_common():
        pct = (count / len(changes)) * 100
        bar = "█" * int(pct / 2)
        print(f"{param:30s} | {count:4d} keer ({pct:5.1f}%) | {bar}")
    
    # Most recent changes
    print(f"\n📅 LAATSTE 10 WIJZIGINGEN:\n")
    recent = sorted(changes, key=lambda x: x['ts'], reverse=True)[:10]
    
    for i, change in enumerate(recent, 1):
        ts = datetime.fromtimestamp(change['ts'])
        param = change['param']
        from_val = change.get('from', '?')
        to_val = change.get('to', '?')
        reason = change.get('reason', 'no reason')
        
        print(f"{i:2d}. [{ts.strftime('%Y-%m-%d %H:%M')}] {param}")
        print(f"    {from_val} → {to_val}")
        print(f"    💡 {reason}\n")
    
    # Analyze patterns
    print("="*80)
    print("🔍 PATRONEN IN AI BESLISSINGEN:")
    print("="*80)
    
    # Group by reason keywords
    reason_keywords = {
        'loss': 0,
        'profit': 0,
        'regime': 0,
        'volatility': 0,
        'exposure': 0,
        'win rate': 0
    }
    
    for change in changes:
        reason = change.get('reason', '').lower()
        for keyword in reason_keywords:
            if keyword in reason:
                reason_keywords[keyword] += 1
    
    print("\nBeslissingen gebaseerd op:")
    for keyword, count in sorted(reason_keywords.items(), key=lambda x: x[1], reverse=True):
        if count > 0:
            print(f"  • {keyword.capitalize():15s}: {count:3d} keer")
    
    # Timeline
    print(f"\n📈 TIMELINE:")
    print("-" * 80)
    
    # Group by date
    dates = {}
    for change in changes:
        date = datetime.fromtimestamp(change['ts']).strftime('%Y-%m-%d')
        dates[date] = dates.get(date, 0) + 1
    
    for date in sorted(dates.keys(), reverse=True)[:10]:
        count = dates[date]
        bar = "█" * min(count, 50)
        print(f"{date}: {bar} ({count} wijzigingen)")
    
    print("\n" + "="*80)
    print("✅ CONCLUSIE: AI is ACTIEF en past regelmatig parameters aan!")
    print("="*80)

if __name__ == '__main__':
    main()
