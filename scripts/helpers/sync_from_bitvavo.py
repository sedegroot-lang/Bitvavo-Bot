#!/usr/bin/env python3
"""
Sync open positions from Bitvavo to local trade_log.json.
- Requires BITVAVO_API_KEY and BITVAVO_API_SECRET in environment.
- Makes a backup of trade_log.json before writing.
- Behaviour: for each balance returned by Bitvavo with a non-zero "available" or "balance",
  convert to market SYMBOL-EUR if market exists in markets list, and create minimal open entries
  using current price and amount.
"""
import os
import json
import time
import shutil
from pathlib import Path
import argparse
import signal

from python_bitvavo_api.bitvavo import Bitvavo

from modules.json_compat import write_json_compat
from modules.trade_store import save_snapshot as save_trade_snapshot
from modules.cost_basis import CostBasisResult, derive_cost_basis

ROOT = Path(__file__).resolve().parent
TRADE_LOG = ROOT / 'data' / 'trade_log.json'
# Write backups into archive/ to keep root clean
ARCHIVE_DIR = ROOT / 'archive'
ARCHIVE_DIR.mkdir(exist_ok=True)
BACKUP = ARCHIVE_DIR / f'trade_log.json.bak.{int(time.time())}'

API_KEY = os.getenv('BITVAVO_API_KEY')
API_SECRET = os.getenv('BITVAVO_API_SECRET')
if not API_KEY or not API_SECRET:
    # Try to load a local .env file as a fallback (do not print secrets)
    env_path = ROOT / '.env'
    if env_path.exists():
        try:
            with env_path.open('r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    k, v = line.split('=', 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k and v:
                        # only set if not present to avoid overwriting real env vars
                        os.environ.setdefault(k, v)
        except Exception:
            pass

    API_KEY = os.getenv('BITVAVO_API_KEY')
    API_SECRET = os.getenv('BITVAVO_API_SECRET')
    if not API_KEY or not API_SECRET:
        print('Missing BITVAVO_API_KEY/BITVAVO_API_SECRET environment variables and no valid .env found. Aborting.')
        raise SystemExit(1)

from modules.bitvavo_client import get_bitvavo

bv = get_bitvavo()
if not bv:
    print('Bitvavo client kon niet worden gemaakt (controleer API keys).')
    raise SystemExit(1)
bv_params = {"APIKEY": API_KEY, "APISECRET": API_SECRET}
OPERATOR_ID = os.getenv('BITVAVO_OPERATOR_ID') or None
if OPERATOR_ID:
    bv_params['OPERATORID'] = OPERATOR_ID
bv = Bitvavo(bv_params)

# helper safe call
def safe(f, *args, **kwargs):
    try:
        return f(*args, **kwargs)
    except Exception as e:
        print('Bitvavo API call failed:', e)
        return None

def do_sync():
    print('Fetching balances from Bitvavo...')
    balances = safe(bv.balance, {}) or []
    print(f'Got {len(balances)} balance entries')
    # get markets mapping available on Bitvavo
    print('Fetching markets list...')
    markets = safe(bv.markets, {}) or []
    market_set = set(m.get('market') for m in markets if m.get('market'))

    live_open = {}
    for b in balances:
        symbol = b.get('symbol')
        if not symbol:
            continue
        # look for EUR pair
        market = f"{symbol}-EUR"
        amount = float(b.get('available', 0) or b.get('balance', 0) or 0)
        if amount <= 0:
            continue
        if market not in market_set:
            # skip non-EUR or unknown markets
            continue
        # get ticker price
        tick = safe(bv.tickerPrice, {'market': market})
        price = None
        if tick and isinstance(tick, dict):
            price = float(tick.get('price') or 0)
        # create minimal open entry
        live_open[market] = {
            'buy_price': price,
            'highest_price': price,
            'amount': amount,
            'timestamp': time.time(),
            'tp_levels_done': [False, False],
            'dca_buys': 0,
            'dca_next_price': 0.0,
            'tp_last_time': 0.0
        }

    print('Live open markets from balances:', list(live_open.keys()))

    if TRADE_LOG.exists():
        with TRADE_LOG.open('r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as exc:
                raise SystemExit(f'Kon {TRADE_LOG} niet parsen: {exc}')
    else:
        data = {'open': {}, 'closed': [], 'profits': {}}

    old_open = data.get('open', {}) if isinstance(data, dict) else {}
    old_set = set(old_open.keys())
    new_set = set(live_open.keys())

    basis_map: dict[str, CostBasisResult] = {}

    for market, entry in live_open.items():
        existing_entry = old_open.get(market) if isinstance(old_open, dict) else None
        opened_hint = None
        if isinstance(existing_entry, dict):
            opened_hint = existing_entry.get('opened_ts') or existing_entry.get('timestamp')
        amount = float(entry.get('amount') or 0.0)
        if amount <= 0:
            continue
        try:
            basis = derive_cost_basis(
                bv,
                market,
                amount,
                tolerance=0.02,
                opened_ts=float(opened_hint) if opened_hint else None,
            )
        except Exception as exc:
            print(f"Cost basis voor {market} kon niet worden opgehaald: {exc}")
            continue
        if not basis or basis.invested_eur <= 0:
            print(f"Cost basis voor {market} onbekend; buy_price blijft gebaseerd op ticker.")
            continue
        entry['invested_eur'] = float(basis.invested_eur)
        if basis.avg_price > 0:
            entry['buy_price'] = float(basis.avg_price)
        try:
            current_high = float(entry.get('highest_price') or 0.0)
        except Exception:
            current_high = 0.0
        entry['highest_price'] = max(current_high, float(entry.get('buy_price') or 0.0))
        basis_map[market] = basis
        entry['opened_ts'] = float(basis.earliest_timestamp or entry.get('timestamp') or time.time())
        entry['timestamp'] = float(entry.get('timestamp') or time.time())
        inferred_buys = max(0, basis.buy_order_count)
        print(
            f"Cost basis voor {market}: investeert EUR {entry['invested_eur']:.2f} tegen EUR {entry['buy_price']:.5f} (fills {basis.fills_used}, buy-orders {inferred_buys})."
        )

    added = new_set - old_set
    removed = old_set - new_set

    print('To add:', added)
    print('To remove:', removed)

    # backup
    if TRADE_LOG.exists():
        try:
            shutil.copy2(TRADE_LOG, BACKUP)
        except FileNotFoundError:
            pass
        print('Backup written to', BACKUP)
    else:
        print('No trade_log.json found locally; creating new snapshot from live balances.')

    def _as_int(value: object, default: int = 0) -> int:
        try:
            if value is None:
                return default
            return int(value)
        except Exception:
            return default

    # Apply changes: replace `open` with live_open but preserve any open entries that are in both
    merged_open: dict[str, dict] = {}
    for market, live_entry in live_open.items():
        existing = dict(old_open.get(market, {}))

        merged = existing.copy()

        merged['amount'] = live_entry.get('amount')

        try:
            live_high = float(live_entry.get('highest_price') or 0.0)
        except Exception:
            live_high = 0.0
        try:
            old_high = float(existing.get('highest_price') or 0.0)
        except Exception:
            old_high = 0.0
        merged['highest_price'] = max(live_high, old_high) or live_entry.get('highest_price')

        if live_entry.get('buy_price') is not None:
            merged['buy_price'] = live_entry.get('buy_price')

        if live_entry.get('invested_eur') is not None:
            merged['invested_eur'] = live_entry.get('invested_eur')

        if live_entry.get('opened_ts') is not None:
            merged['opened_ts'] = live_entry.get('opened_ts')

        merged['timestamp'] = live_entry.get('timestamp', time.time())

        # carry over defaults for new entries
        merged.setdefault('tp_levels_done', live_entry.get('tp_levels_done', [False, False]))
        merged.setdefault('dca_next_price', live_entry.get('dca_next_price', 0.0))
        merged.setdefault('tp_last_time', live_entry.get('tp_last_time', 0.0))

        basis_info = basis_map.get(market)
        if basis_info:
            inferred_dca = _as_int(basis_info.buy_order_count - 1)
            merged['dca_buys'] = inferred_dca
        else:
            current_dca = _as_int(existing.get('dca_buys'))
            live_dca = _as_int(live_entry.get('dca_buys'))
            merged['dca_buys'] = max(current_dca, live_dca)

        # Preserve or infer per-trade DCA max (do not let global config changes silently reduce
        # the max for already-open positions). Prefer existing value, then live_entry, then
        # any info from basis; fall back to config file or 3.
        try:
            existing_max = _as_int(existing.get('dca_max'))
        except Exception:
            existing_max = 0
        try:
            live_max = _as_int(live_entry.get('dca_max'))
        except Exception:
            live_max = 0
        inferred_max = 0
        try:
            if basis_info and getattr(basis_info, 'buy_order_count', None) is not None:
                inferred_max = int(getattr(basis_info, 'buy_order_count') or 0)
        except Exception:
            inferred_max = 0
        merged_max = max(existing_max or 0, live_max or 0, inferred_max or 0)
        if not merged_max:
            # try reading bot_config.json for fallback
            try:
                cfg_path = Path(__file__).parent.parent.parent / 'config' / 'bot_config.json'
                if cfg_path.exists():
                    cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
                    merged_max = int(cfg.get('DCA_MAX_BUYS', 3) or 3)
            except Exception:
                merged_max = 3
        merged['dca_max'] = int(merged_max)

        merged_open[market] = merged

    print('Merged open snapshot:')
    for market, entry in merged_open.items():
        print(f"  {market}: buy={entry.get('buy_price')} invested={entry.get('invested_eur')} amount={entry.get('amount')}")

    # Optioneel: sync-verwijdering uitschakelen via config
    config_path = ROOT / 'config' / 'bot_config.json'
    disable_sync_remove = True  # Safe default: don't remove trades
    if config_path.exists():
        with config_path.open('r', encoding='utf-8') as f:
            config = json.load(f)
            disable_sync_remove = config.get('DISABLE_SYNC_REMOVE', True)

    closed = data.get('closed', [])
    timestamp = time.time()
    if not disable_sync_remove:
        for k in removed:
            entry = old_open.get(k)
            closed_entry = {
                'market': k,
                'buy_price': entry.get('buy_price') if entry else None,
                'sell_price': 0.0,
                'amount': entry.get('amount') if entry else None,
                'profit': -10.0,
                'timestamp': timestamp,
                'reason': 'sync_removed'
            }
            closed.append(closed_entry)

    # update data and write back
    data['open'] = merged_open
    data['closed'] = closed
    save_trade_snapshot(data, str(TRADE_LOG), indent=2)

    # update heartbeat
    hb = ROOT / 'data' / 'heartbeat.json'
    hb_data = {'ts': time.time(), 'open_trades': len(merged_open)}
    write_json_compat(str(hb), hb_data)

    print('Sync complete. Open trades now:', len(merged_open))
    print('Added:', added)
    print('Removed (moved to closed):', removed)


def main_loop(interval):
    stop = False

    def _sigint(signum, frame):
        nonlocal stop
        print('\nReceived interrupt, stopping loop after current iteration...')
        stop = True

    signal.signal(signal.SIGINT, _sigint)
    signal.signal(signal.SIGTERM, _sigint)

    while not stop:
        do_sync()
        if stop:
            break
        print(f'Waiting {interval} seconds until next sync...')
        time.sleep(interval)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Sync trade_log.json with Bitvavo balances')
    parser.add_argument('--interval', '-i', type=int, default=60, help='Sync interval in seconds (default 60)')
    parser.add_argument('--once', action='store_true', help='Run sync only once and exit')
    args = parser.parse_args()

    if args.once:
        do_sync()
    else:
        print(f'Starting continuous sync every {args.interval} seconds. Press Ctrl-C to stop.')
        main_loop(args.interval)
