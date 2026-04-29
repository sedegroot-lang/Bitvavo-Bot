"""scripts/scheduled_ml_jobs.py — Run drift_monitor + walk_forward backtest.

Designed to be invoked daily (Windows Task Scheduler / cron). Both checks
are non-fatal: bot trading continues even if these fail. Output:

    * On drift > threshold: writes alert to logs/ml_drift_alert.txt + Telegram
      (when TELEGRAM_TOKEN/CHAT_ID set) and exits 1.
    * Walk-forward results appended to data/walk_forward_history.jsonl.

Usage:
    python scripts/scheduled_ml_jobs.py
    python scripts/scheduled_ml_jobs.py --skip-drift
    python scripts/scheduled_ml_jobs.py --skip-walkforward
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOGS_DIR = ROOT / 'logs'
DATA_DIR = ROOT / 'data'
LOGS_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)


def _send_telegram(msg: str) -> bool:
    try:
        from modules.config import load_config
        from modules import telegram_handler as tg
        cfg = load_config()
        tg.init(cfg)
        return bool(tg.send_message(msg))
    except Exception as exc:
        print(f"telegram send failed: {exc}", file=sys.stderr)
        return False


def run_drift_check() -> int:
    """Returns 0 = ok, 1 = drift detected."""
    try:
        # Lazy import — drift_monitor uses scipy/numpy only when called
        from scripts import drift_monitor  # type: ignore
    except Exception as exc:
        print(f"[drift] import failed (non-fatal): {exc}")
        return 0
    try:
        baseline = DATA_DIR / 'feature_baseline.json'
        if not baseline.exists():
            print("[drift] no baseline yet — run with --update-baseline once")
            return 0
        # call monitor function if available
        result = None
        for fname in ('check_drift', 'main', 'detect_drift'):
            fn = getattr(drift_monitor, fname, None)
            if callable(fn):
                try:
                    result = fn()
                    break
                except SystemExit as se:
                    return int(se.code or 0)
                except Exception as exc:
                    print(f"[drift] {fname} failed: {exc}")
        if result is None:
            print("[drift] no callable entry-point found — skipping")
            return 0
        if isinstance(result, dict) and result.get('drift_detected'):
            alert = (
                f"⚠️ ML feature drift detected at {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"Features over 3σ: {result.get('drifted_features', [])}\n"
                f"Max z-score: {result.get('max_z', 0):.2f}"
            )
            (LOGS_DIR / 'ml_drift_alert.txt').write_text(alert, encoding='utf-8')
            _send_telegram(alert)
            return 1
    except Exception as exc:
        print(f"[drift] unexpected error: {exc}")
    return 0


def run_walk_forward() -> int:
    try:
        from backtest.walk_forward import run_walk_forward as wf_run, WalkForwardConfig
    except Exception as exc:
        print(f"[wf] import failed (non-fatal): {exc}")
        return 0
    trades_path = DATA_DIR / 'trade_log.json'
    if not trades_path.exists():
        print("[wf] no trade_log yet")
        return 0
    try:
        cfg = WalkForwardConfig(train_days=14, test_days=7, step_days=7)
        result = wf_run(str(trades_path), cfg)
        out = {
            'ts': time.time(),
            'iso': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'config': {'train_days': 14, 'test_days': 7, 'step_days': 7},
            'result': result if isinstance(result, (dict, list)) else str(result),
        }
        with open(DATA_DIR / 'walk_forward_history.jsonl', 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(out, default=str) + '\n')
        print(f"[wf] result appended: {len(str(result))} bytes")
    except Exception as exc:
        print(f"[wf] failed: {exc}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--skip-drift', action='store_true')
    ap.add_argument('--skip-walkforward', action='store_true')
    args = ap.parse_args()

    rc = 0
    if not args.skip_drift:
        rc |= run_drift_check()
    if not args.skip_walkforward:
        rc |= run_walk_forward()
    return rc


if __name__ == '__main__':
    sys.exit(main())
