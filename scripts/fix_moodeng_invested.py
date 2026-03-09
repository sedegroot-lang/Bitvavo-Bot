"""Fix MOODENG initial_invested_eur to correct €250 value"""
import json
import shutil
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
TRADE_LOG_PATH = PROJECT_ROOT / "data" / "trade_log.json"

# Backup
backup_path = TRADE_LOG_PATH.parent / f"trade_log_manual_fix_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
shutil.copy(TRADE_LOG_PATH, backup_path)
print(f"💾 Backup: {backup_path}")

# Load
with open(TRADE_LOG_PATH, 'r') as f:
    data = json.load(f)

# Fix MOODENG
trade = data['open']['MOODENG-EUR']
initial_buy_price = 0.06067660186755018  # Van logs
amount = 4120.039559
initial_invested = initial_buy_price * amount

print(f"\n✅ Initial invested berekend: €{initial_invested:.2f}")
print(f"   (buy_price {initial_buy_price:.8f} × amount {amount:.2f})")

trade['initial_invested_eur'] = float(initial_invested)
trade['total_invested_eur'] = float(trade.get('invested_eur', 283.21))
if 'dca_events' not in trade:
    trade['dca_events'] = []

print(f"\n📝 Updated:")
print(f"   initial_invested_eur: €{trade['initial_invested_eur']:.2f}")
print(f"   total_invested_eur: €{trade['total_invested_eur']:.2f}")
print(f"   invested_eur (avg): €{trade['invested_eur']:.2f}")

# Save
with open(TRADE_LOG_PATH, 'w') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"\n✅ trade_log.json GEÜPDATET!")
print(f"\n🔄 Herstart bot om nieuwe waardes te laden:")
print(f"   & 'scripts\\restart_bot_stack.ps1'")
