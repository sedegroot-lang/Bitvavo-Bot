import sys
import os
from pathlib import Path

# Add dashboard_flask directory to path
dashboard_path = Path(__file__).parent.parent / 'tools' / 'dashboard_flask'
sys.path.insert(0, str(dashboard_path))
os.chdir(dashboard_path)

# Import PROJECT_ROOT from dashboard app
try:
    from app import PROJECT_ROOT  # type: ignore
except ImportError:
    # Fallback: calculate PROJECT_ROOT manually
    PROJECT_ROOT = Path(__file__).parent.parent
import json

eth_config_path = PROJECT_ROOT / 'config' / 'grid_strategy_eth.json'

print(f"Working Directory: {os.getcwd()}")
print(f"PROJECT_ROOT: {PROJECT_ROOT}")
print(f"ETH Config Path: {eth_config_path}")
print(f"File Exists: {eth_config_path.exists()}")

if eth_config_path.exists():
    with open(eth_config_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    print(f"\n✅ Loaded successfully!")
    print(f"   Market: {data.get('market')}")
    print(f"   Investment: €{data.get('investment', {}).get('total_eur')}")
else:
    print("\n❌ File NOT found!")
    print(f"   Expected at: {eth_config_path.absolute()}")
