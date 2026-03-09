import json, time, shutil, sys
from pathlib import Path

# Ensure project root is on sys.path so `modules` package imports work
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from modules.bitvavo_client import get_bitvavo
from modules.json_compat import write_json_compat

TRADE_LOG = Path('data/trade_log.json')
BACKUP_DIR = Path('backups')
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

# Load config for DCA defaults
cfg_path = Path('config/bot_config.json')
config = {}
if cfg_path.exists():
    try:
        config = json.loads(cfg_path.read_text(encoding='utf-8'))
    except Exception:
        config = {}

bv = get_bitvavo(config)
if not bv:
    print('NO_CLIENT')
    raise SystemExit(1)

# Get LINK balance
bals = bv.balance({})
link_amount = 0.0
for b in (bals or []):
    if str(b.get('symbol') or '').upper() == 'LINK':
        try:
            link_amount = float(b.get('available') or b.get('balance') or 0.0)
        except Exception:
            link_amount = 0.0
        break

# Get current price
price = 0.0
try:
    t = bv.tickerPrice({'market': 'LINK-EUR'})
    if isinstance(t, dict):
        price = float(t.get('price') or 0.0)
    elif isinstance(t, list) and t:
        price = float(t[0].get('price') or 0.0)
except Exception:
    price = 0.0

if link_amount <= 0:
    print('NO_BALANCE')
    raise SystemExit(2)

# Prepare new open entry
now = time.time()
dca_drop = float(config.get('DCA_DROP_PCT', 0.06) or 0.06)
dca_max = int(config.get('DCA_MAX_BUYS', 2) or 2)
next_price = price * (1 - dca_drop) if price > 0 else None
invested = price * link_amount if price > 0 else None

new_entry = {
    'market': 'LINK-EUR',
    'buy_price': price,
    'highest_price': price,
    'amount': link_amount,
    'timestamp': now,
    'tp_levels_done': [False, False],
    'dca_buys': 0,
    'dca_max': dca_max,
    'dca_next_price': next_price,
    'tp_last_time': 0.0,
    'invested_eur': invested,
    'opened_ts': now,
    'trailing_activated': False,
    'activation_price': None,
    'highest_since_activation': None,
    'last_dca_price': price,
}

# Read existing trade log
if not TRADE_LOG.exists():
    base = {'open': {}, 'closed': []}
else:
    try:
        base = json.loads(TRADE_LOG.read_text(encoding='utf-8'))
    except Exception:
        base = {'open': {}, 'closed': []}

open_dict = base.get('open') if isinstance(base.get('open'), dict) else {}

if 'LINK-EUR' in open_dict:
    print('ALREADY_OPEN')
    raise SystemExit(3)

# Backup
bak_name = BACKUP_DIR / f"trade_log.json.bak.{int(time.time())}.json"
shutil.copy2(TRADE_LOG, bak_name)
print(f'BACKUP_CREATED {bak_name}')

# Insert
open_dict['LINK-EUR'] = new_entry
base['open'] = open_dict

# Persist safely
write_json_compat(str(TRADE_LOG), base, indent=2)
print('RESTORED')
print(json.dumps(new_entry, indent=2))
