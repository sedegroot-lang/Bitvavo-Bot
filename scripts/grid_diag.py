"""Grid diagnostic script - check state and find issues."""
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRID_FILE = os.path.join(BASE, 'data', 'grid_states.json')
LOG_FILE = os.path.join(BASE, 'logs', 'bot_log.txt.rotation.log')

print("=" * 60)
print("GRID DIAGNOSTIC")
print("=" * 60)

# 1. Grid states
if os.path.exists(GRID_FILE):
    d = json.load(open(GRID_FILE, encoding='utf-8-sig'))
    for market, state in d.items():
        print(f"\n--- {market} ---")
        cfg = state.get('config', {})
        print(f"  Status:     {state.get('status')}")
        print(f"  Range:      {cfg.get('lower_price')} - {cfg.get('upper_price')}")
        print(f"  Investment: {cfg.get('total_investment')}")
        print(f"  Num grids:  {cfg.get('num_grids')}")
        print(f"  Enabled:    {cfg.get('enabled')}")
        print(f"  Trades:     {state.get('total_trades')}")
        print(f"  Profit:     {state.get('total_profit')}")
        
        levels = state.get('levels', [])
        status_counts = {}
        for l in levels:
            s = l.get('status', '?')
            status_counts[s] = status_counts.get(s, 0) + 1
        print(f"  Levels:     {len(levels)} total - {status_counts}")
        
        # Show error details
        for l in levels:
            if l.get('error_msg'):
                print(f"    Level {l.get('level_id')}: {l.get('side')} @ {l.get('price')} "
                      f"status={l.get('status')} err={l.get('error_msg')[:100]}")
else:
    print("No grid_states.json found!")

# 2. Recent grid log entries
print("\n" + "=" * 60)
print("RECENT GRID LOG ENTRIES")
print("=" * 60)
if os.path.exists(LOG_FILE):
    grid_lines = []
    with open(LOG_FILE, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            if '[Grid]' in line or 'grid' in line.lower():
                grid_lines.append(line.rstrip())
    for line in grid_lines[-30:]:
        print(line)
else:
    print("No log file found!")
    # Try other log locations
    for name in os.listdir(os.path.join(BASE, 'logs')):
        print(f"  Found: {name}")
