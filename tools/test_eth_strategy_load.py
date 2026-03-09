"""
Test script to verify ETH strategy loads in dashboard
"""
import sys
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
from tools.dashboard_flask.app import PROJECT_ROOT

# Test loading ETH strategy
eth_config_path = PROJECT_ROOT / 'config' / 'grid_strategy_eth.json'

print(f"PROJECT_ROOT: {PROJECT_ROOT}")
print(f"Looking for: {eth_config_path}")
print(f"File exists: {eth_config_path.exists()}")

if eth_config_path.exists():
    with open(eth_config_path, 'r', encoding='utf-8') as f:
        eth_strategy = json.load(f)
    
    print(f"\n✅ ETH Strategy Loaded:")
    print(f"   Market: {eth_strategy.get('market')}")
    print(f"   Investment: €{eth_strategy.get('investment', {}).get('total_eur')}")
    print(f"   Grid Levels: {eth_strategy.get('grid_settings', {}).get('num_grids')}")
    print(f"   Mode: {eth_strategy.get('mode')}")
    print(f"\n   Strategy will show in template: {bool(eth_strategy)}")
else:
    print("\n❌ File not found!")
