"""Backfill historical entry-snapshot features for closed trades.

For each closed trade in trade_log.json + trade_archive.json, fetches the 60
1m candles ending at the trade's opened_ts from Bitvavo and computes the
7-feature snapshot expected by the regular XGB model
(rsi, macd, sma_short, sma_long, volume, bb_position, stochastic_k).

Writes results into <PROJECT_ROOT>/data/trade_features_backfill.json keyed by
a stable trade key, so we can resume across runs and avoid re-fetching.

The companion build_trade_features.py reads this backfill file when a trade is
missing real entry-snapshot fields.

Usage:
    python scripts/backfill_trade_features.py [--limit N] [--sleep MS]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / '.env')

from python_bitvavo_api.bitvavo import Bitvavo  # noqa: E402

import bot.api as _api  # noqa: E402
from modules.config import load_config  # noqa: E402
from core.indicators import (  # noqa: E402
    close_prices,
    volumes,
    sma,
    rsi,
    macd as macd_fn,
    bb_position as bb_pos_fn,
    stochastic,
)

ARCHIVE = PROJECT_ROOT / 'data' / 'trade_archive.json'
TRADE_LOG = PROJECT_ROOT / 'data' / 'trade_log.json'
OUT_PATH = PROJECT_ROOT / 'data' / 'trade_features_backfill.json'


def _trade_key(t: dict) -> str:
    return f"{t.get('market')}|{int(t.get('opened_ts') or t.get('timestamp') or 0)}|{t.get('sell_order_id') or ''}"


def _load_trades() -> List[dict]:
    out: List[dict] = []
    for path in (TRADE_LOG, ARCHIVE):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except Exception as e:
            print(f"WARN: kan {path.name} niet lezen: {e}")
            continue
        if isinstance(data, list):
            out.extend(t for t in data if isinstance(t, dict))
        elif isinstance(data, dict):
            # trade_log.json: {"closed": [...]} ; trade_archive.json: {"trades": [...]}
            for key in ('closed', 'trades'):
                lst = data.get(key)
                if isinstance(lst, list):
                    out.extend(t for t in lst if isinstance(t, dict))
            # also consider any dict-of-trades shape
            if not any(k in data for k in ('closed', 'trades')):
                out.extend(t for t in data.values() if isinstance(t, dict))
    seen, unique = set(), []
    for t in out:
        k = _trade_key(t)
        if k in seen:
            continue
        seen.add(k)
        unique.append(t)
    return unique


def _has_real_snapshot(t: dict) -> bool:
    """Return True when the trade already has a usable entry snapshot."""
    rsi_v = t.get('rsi_at_entry')
    sma_s = t.get('sma_short_at_entry')
    macd_v = t.get('macd_at_entry')
    if rsi_v is None and sma_s is None and macd_v is None:
        return False
    # The bot historically defaulted rsi=50 / sma=0 when indicators were
    # unavailable. Treat those as missing.
    return not (
        (rsi_v in (None, 50, 50.0))
        and (not sma_s)
        and (not macd_v)
    )


def _compute_snapshot(candles: list) -> dict | None:
    closes = close_prices(candles)
    vols = volumes(candles)
    if len(closes) < 26:
        return None
    rsi_v = rsi(closes, 14)
    macd_line, _macd_sig, macd_hist = macd_fn(closes)
    sma_short = sma(closes, 7)
    sma_long = sma(closes, min(25, len(closes)))
    bb_pos = bb_pos_fn(closes, min(20, len(closes)), 2.0)
    stoch = stochastic(closes, 14)
    avg_vol = sum(vols[-20:]) / max(1, len(vols[-20:])) if vols else 0.0
    if rsi_v is None or sma_short is None or sma_long is None:
        return None
    return {
        'rsi_at_entry': float(rsi_v),
        'macd_at_entry': float(macd_hist) if macd_hist is not None else 0.0,
        'macd_line_at_entry': float(macd_line) if macd_line is not None else 0.0,
        'sma_short_at_entry': float(sma_short),
        'sma_long_at_entry': float(sma_long),
        'bb_position_at_entry': float(bb_pos) if bb_pos is not None else 0.5,
        'stochastic_k_at_entry': float(stoch) if stoch is not None else 50.0,
        'volume_avg_at_entry': float(avg_vol),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=0, help='cap number of trades to process (0=all)')
    parser.add_argument('--sleep', type=int, default=120, help='ms to sleep between API calls')
    args = parser.parse_args()

    cfg = load_config() or {}
    api_key = os.getenv('BITVAVO_API_KEY') or os.getenv('BITVAVO_APIKEY') or cfg.get('BITVAVO_APIKEY', '')
    api_secret = os.getenv('BITVAVO_API_SECRET') or os.getenv('BITVAVO_APISECRET') or cfg.get('BITVAVO_APISECRET', '')
    if not api_key or not api_secret:
        print('ERROR: BITVAVO_APIKEY/SECRET ontbreken in .env')
        return 2
    bv = Bitvavo({'APIKEY': api_key, 'APISECRET': api_secret})
    _api.init(bv, cfg)

    trades = _load_trades()
    print(f"Loaded {len(trades)} unique trades from log+archive")

    cache: Dict[str, dict] = {}
    if OUT_PATH.exists():
        try:
            cache = json.loads(OUT_PATH.read_text(encoding='utf-8'))
        except Exception:
            cache = {}
    print(f"Existing backfill cache: {len(cache)} entries")

    todo = []
    for t in trades:
        if _has_real_snapshot(t):
            continue
        k = _trade_key(t)
        if k in cache:
            continue
        opened = int(t.get('opened_ts') or t.get('timestamp') or 0)
        if opened <= 0 or not t.get('market'):
            continue
        todo.append(t)
    if args.limit > 0:
        todo = todo[: args.limit]
    print(f"Will fetch candles for {len(todo)} trades")

    sleep_s = max(0.0, args.sleep / 1000.0)
    ok, fail = 0, 0
    for i, t in enumerate(todo, 1):
        market = t['market']
        opened_ms = int(t.get('opened_ts') or t.get('timestamp') or 0) * 1000
        # Use a 3h window so we always get >=26 candles even on illiquid pairs.
        start_ms = opened_ms - 3 * 60 * 60 * 1000
        try:
            candles = bv.candles(market, '1m', {'limit': 200, 'start': start_ms, 'end': opened_ms})
        except Exception as e:
            print(f"  [{i}/{len(todo)}] {market} fetch error: {e}")
            fail += 1
            time.sleep(sleep_s)
            continue
        if not candles or len(candles) < 26:
            fail += 1
            cache[_trade_key(t)] = {'error': 'insufficient_candles', 'n': len(candles or [])}
            time.sleep(sleep_s)
            continue
        # Bitvavo returns newest-first; indicators expect oldest-first.
        try:
            ts0 = int(candles[0][0])
            tsN = int(candles[-1][0])
            if ts0 > tsN:
                candles = list(reversed(candles))
        except Exception:
            pass
        snap = _compute_snapshot(candles)
        if not snap:
            fail += 1
            cache[_trade_key(t)] = {'error': 'compute_failed'}
        else:
            ok += 1
            cache[_trade_key(t)] = snap
        if i % 25 == 0:
            OUT_PATH.write_text(json.dumps(cache, indent=2), encoding='utf-8')
            print(f"  progress {i}/{len(todo)}  ok={ok}  fail={fail}")
        time.sleep(sleep_s)

    OUT_PATH.write_text(json.dumps(cache, indent=2), encoding='utf-8')
    print(f"Done: ok={ok} fail={fail} total_cache={len(cache)} -> {OUT_PATH}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
