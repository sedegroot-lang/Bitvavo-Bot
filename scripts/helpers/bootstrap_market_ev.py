# -*- coding: utf-8 -*-
"""Bootstrap core.market_expectancy from clean trade archive (March-April 2026).

Skips operational error reasons (saldo_error, sync_removed, manual_close) and
trades from before 2026-03-01 (when the bot was not yet stable).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.market_expectancy import market_ev, MarketExpectancy, DEFAULT_DATA_FILE  # noqa: E402

EXCLUDE_REASONS = {
    'saldo_error', 'sync_removed', 'manual_close',
    'reconstructed', 'dust_cleanup',
}
START_TS = datetime(2026, 3, 1, tzinfo=timezone.utc).timestamp()


def _close_ts(t: dict) -> float:
    return float(t.get('closed_ts') or t.get('sell_ts') or t.get('timestamp') or 0)


def main() -> int:
    archive_path = ROOT / 'data' / 'trade_archive.json'
    if not archive_path.exists():
        print(f"archive not found: {archive_path}", file=sys.stderr)
        return 1
    blob = json.loads(archive_path.read_text(encoding='utf-8'))
    trades = blob.get('trades', []) if isinstance(blob, dict) else blob

    # Reset to a fresh estimator so re-running the bootstrap doesn't double-count.
    fresh = MarketExpectancy(data_file=DEFAULT_DATA_FILE)
    fresh._stats.clear()
    fresh._global = {'n': 0, 'sum_pnl': 0.0}

    n = 0
    for t in trades:
        try:
            if t.get('profit') is None:
                continue
            if (t.get('reason') or '').lower() in EXCLUDE_REASONS:
                continue
            if _close_ts(t) < START_TS:
                continue
            fresh.record_trade(t['market'], float(t['profit']))
            n += 1
        except Exception:
            continue

    fresh.force_save()
    snap = fresh.snapshot()
    print(f"seeded {n} trades into {DEFAULT_DATA_FILE}")
    print(f"global: n={snap['global']['n']} avg_ev=EUR {snap['global']['avg_ev']:+.4f}")
    print("\ntop 8 markets by size_multiplier:")
    rows = sorted(snap['per_market'].items(),
                  key=lambda kv: -kv[1]['size_multiplier'])
    for m, info in rows[:8]:
        print(f"  {m:14s} n={info['n']:3d}  shrunk_ev=EUR{info['shrunk_ev']:+5.2f}  mult={info['size_multiplier']:.2f}")
    print("\nbottom 8 markets by size_multiplier:")
    for m, info in rows[-8:]:
        print(f"  {m:14s} n={info['n']:3d}  shrunk_ev=EUR{info['shrunk_ev']:+5.2f}  mult={info['size_multiplier']:.2f}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
