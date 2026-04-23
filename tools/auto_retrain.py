"""Utility to trigger AI model retraining on a fixed cadence.

Run this script daily (e.g. via Task Scheduler or cron). It checks the latest
trained timestamp stored in `ai_model_metrics.json` and only launches the
training pipeline when we are past the configured interval and UTC time.

Configuration is sourced from `bot_config.json` using the following keys:
- AI_AUTO_RETRAIN_ENABLED (bool)
- AI_RETRAIN_INTERVAL_DAYS (int, default 7)
- AI_RETRAIN_UTC_HOUR ("HH:MM" string, default "02:00")
- AI_RETRAIN_ARGS (dict with overrides for train_ai_model.py arguments)

Usage:
    python tools/auto_retrain.py            # normal schedule-aware run
    python tools/auto_retrain.py --force    # force retraining regardless of schedule
    python tools/auto_retrain.py --loop     # keep process alive and poll schedule every 15 minutes
    python tools/auto_retrain.py --dry-run  # report next due time without training
"""


from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, time as dt_time, timezone
from pathlib import Path
import atexit
import os

from typing import Dict, Tuple

LOG_DIR = Path(__file__).resolve().parent / 'logs'
LOG_DIR.mkdir(exist_ok=True)
PID_FILE = LOG_DIR / 'auto_retrain.pid'
DEBUG_LOG = LOG_DIR / 'auto_retrain_debug.log'
def debug_log(msg: str):
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')
    try:
        with open(DEBUG_LOG, 'a', encoding='utf-8') as f:
            f.write(f'[{ts}] {msg}\n')
    except Exception:
        pass

# PID-file guard
def pid_guard():
    pid = os.getpid()
    debug_log(f"pid_guard: START pid={pid} cmdline={' '.join(sys.argv)}")
    if PID_FILE.exists():
        try:
            existing = int(PID_FILE.read_text().strip() or '0')
        except Exception:
            existing = 0
        if existing and existing != os.getpid():
            try:
                os.kill(existing, 0)
                debug_log(f"pid_guard: exit, andere auto_retrain actief pid={existing}")
                print(f"[auto_retrain] Andere auto_retrain actief (pid={existing}), exit.")
                sys.exit(0)
            except Exception:
                debug_log(f"pid_guard: oude pid-file gevonden, verwijderen")
        try:
            PID_FILE.unlink()
        except Exception:
            pass
    try:
        PID_FILE.write_text(str(pid))
        debug_log(f"pid_guard: pid-file aangemaakt met pid={pid}")
    except Exception as e:
        debug_log(f"pid_guard: exception bij pid-file aanmaken {e}")
    def _rm():
        try:
            if PID_FILE.exists() and int(PID_FILE.read_text().strip() or '0') == pid:
                PID_FILE.unlink()
                debug_log(f"pid_guard: pid-file verwijderd bij exit")
        except Exception:
            pass
    atexit.register(_rm)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.logging_utils import log

_TOOLS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TOOLS_DIR.parent

CONFIG_PATH = _PROJECT_ROOT / 'config' / 'bot_config.json'
METRICS_PATH = _PROJECT_ROOT / 'ai' / 'ai_model_metrics.json'
# Regular 7-feature trainer that writes to ai/ai_xgb_model.json (the model the bot loads).
# xgb_train_enhanced.py is intentionally NOT used here - it produces a 5-feature
# post-trade model and would break entry-signal predictions.
TRAIN_SCRIPT = _PROJECT_ROOT / 'ai' / 'xgb_walk_forward.py'
TRAIN_DATA_PATH = _PROJECT_ROOT / 'trade_features.csv'
BUILD_FEATURES_SCRIPT = _PROJECT_ROOT / 'scripts' / 'build_trade_features.py'
BACKFILL_SCRIPT = _PROJECT_ROOT / 'scripts' / 'backfill_trade_features.py'
MIN_TRAIN_SAMPLES = 100
DEFAULT_LOOP_SECONDS = 900  # 15 minutes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Schedule-aware AI model retrainer.')
    parser.add_argument('--force', action='store_true', help='Force retraining regardless of schedule.')
    parser.add_argument('--dry-run', action='store_true', help='Only report the next due window without training.')
    parser.add_argument(
        '--loop',
        nargs='?',
        const=DEFAULT_LOOP_SECONDS,
        type=int,
        metavar='SECONDS',
        help='Keep running and check the schedule every N seconds (default 900).'
    )
    return parser.parse_args()


def load_config() -> Dict:
    # Use the project's 3-layer config loader (base + overrides + LOCAL),
    # so settings in %LOCALAPPDATA%/BotConfig/bot_config_local.json are honored.
    # Falls back to reading the base file if the loader is unavailable.
    try:
        from modules.config import load_config as _load_config
        cfg = _load_config() or {}
        if cfg:
            return cfg
    except Exception as exc:  # pragma: no cover - defensive
        log(f'auto_retrain: kon modules.config.load_config niet gebruiken ({exc}); val terug op base config.', level='warning')
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f'Config file not found at {CONFIG_PATH}')
    with CONFIG_PATH.open('r', encoding='utf-8') as fh:
        return json.load(fh)


def load_metrics() -> Tuple[int, Dict]:
    if not METRICS_PATH.exists():
        return 0, {}
    try:
        with METRICS_PATH.open('r', encoding='utf-8') as fh:
            metrics = json.load(fh)
            last_ts = int(metrics.get('trained_at', 0) or 0)
            return last_ts, metrics
    except Exception as exc:  # pragma: no cover - defensive
        log(f'auto_retrain: kon metrics niet lezen ({exc}), treat as due.', level='warning')
        return 0, {}


def parse_target_time(cfg: Dict) -> dt_time:
    raw = cfg.get('AI_RETRAIN_UTC_HOUR', '02:00')
    try:
        hour_str, minute_str = str(raw).split(':', maxsplit=1)
        hour = max(0, min(23, int(hour_str)))
        minute = max(0, min(59, int(minute_str)))
        return dt_time(hour=hour, minute=minute, tzinfo=timezone.utc)
    except Exception:
        return dt_time(hour=2, minute=0, tzinfo=timezone.utc)


def compute_due_time(last_ts: int, interval_days: int, target_time: dt_time) -> datetime:
    """Return the next datetime (UTC) at which retraining should occur."""
    interval_days = max(1, interval_days)
    now = datetime.now(timezone.utc)
    interval = timedelta(days=interval_days)
    if last_ts:
        last_dt = datetime.fromtimestamp(last_ts, timezone.utc)
    else:
        # treat as very old so that we train immediately when enabled
        last_dt = now - interval * 2

    candidate_date = (last_dt + interval).date()
    due_dt = datetime.combine(candidate_date, target_time)
    if due_dt.tzinfo is None:
        due_dt = due_dt.replace(tzinfo=timezone.utc)
    if due_dt <= last_dt:
        due_dt = datetime.combine(candidate_date + interval, target_time)
        if due_dt.tzinfo is None:
            due_dt = due_dt.replace(tzinfo=timezone.utc)
    return due_dt


def build_train_command(cfg_args: Dict) -> list:
    # xgb_walk_forward.py supports --window/--step; defaults are sensible.
    cmd = [sys.executable, str(TRAIN_SCRIPT)]
    try:
        if isinstance(cfg_args, dict):
            window = cfg_args.get('window')
            step = cfg_args.get('step')
            if window:
                cmd += ['--window', str(int(window))]
            if step:
                cmd += ['--step', str(int(step))]
    except Exception:
        pass
    return cmd


def _training_data_ready() -> Tuple[bool, str]:
    """Check whether enough labelled feature data exists to safely (re)train.

    Returns (ready, reason). When not ready, the caller should SKIP training
    rather than break the running bot's model.
    """
    if not TRAIN_DATA_PATH.exists():
        return False, f'no training data at {TRAIN_DATA_PATH.name}'
    try:
        with TRAIN_DATA_PATH.open('r', encoding='utf-8') as fh:
            # subtract 1 for header
            rows = sum(1 for _ in fh) - 1
        if rows < MIN_TRAIN_SAMPLES:
            return False, f'only {rows} rows in {TRAIN_DATA_PATH.name} (need >= {MIN_TRAIN_SAMPLES})'
    except Exception as exc:
        return False, f'cannot read {TRAIN_DATA_PATH.name}: {exc}'
    return True, ''


def maybe_retrain(args: argparse.Namespace) -> Dict[str, object]:
    cfg = load_config()
    enabled = bool(cfg.get('AI_AUTO_RETRAIN_ENABLED', False)) or args.force
    if not enabled:
        log('auto_retrain: retraining uitgeschakeld (AI_AUTO_RETRAIN_ENABLED = false).')
        return {'ran': False, 'next_due': None, 'last_trained': None}

    interval_days = int(cfg.get('AI_RETRAIN_INTERVAL_DAYS', 7) or 7)
    target_time = parse_target_time(cfg)
    last_ts, metrics = load_metrics()
    due_dt = compute_due_time(last_ts, interval_days, target_time)
    now_dt = datetime.now(timezone.utc)
    trained = False

    if args.dry_run:
        status = 'due' if now_dt >= due_dt else 'upcoming'
        log(f'auto_retrain (dry-run): laatste training {datetime.fromtimestamp(last_ts, timezone.utc).isoformat() if last_ts else "unknown"}, next window {due_dt.isoformat()} UTC ({status}).')
        return {'ran': False, 'next_due': due_dt, 'last_trained': last_ts}

    if not args.force and now_dt < due_dt:
        human_last = datetime.fromtimestamp(last_ts, timezone.utc).isoformat() if last_ts else 'never'
        level = 'info' if not getattr(args, 'loop', 0) else 'debug'
        log(f'auto_retrain: skipping (last={human_last}, next_due={due_dt.isoformat()} UTC).', level=level)
        return {'ran': False, 'next_due': due_dt, 'last_trained': last_ts}

    train_args = cfg.get('AI_RETRAIN_ARGS', {}) if isinstance(cfg.get('AI_RETRAIN_ARGS'), dict) else {}

    # Always regenerate trade_features.csv from the latest trade_log + archive
    # before evaluating data-readiness or training.
    if BACKFILL_SCRIPT.exists():
        try:
            log(f'auto_retrain: backfilling missing entry snapshots via {BACKFILL_SCRIPT.name} (incremental).')
            subprocess.run([sys.executable, str(BACKFILL_SCRIPT), '--sleep', '80'], check=False)
        except Exception as exc:
            log(f'auto_retrain: backfill_trade_features failed: {exc}', level='warning')
    if BUILD_FEATURES_SCRIPT.exists():
        try:
            log(f'auto_retrain: rebuilding {TRAIN_DATA_PATH.name} from trade history.')
            subprocess.run([sys.executable, str(BUILD_FEATURES_SCRIPT)], check=False)
        except Exception as exc:
            log(f'auto_retrain: build_trade_features failed: {exc}', level='warning')
    else:
        log(f'auto_retrain: {BUILD_FEATURES_SCRIPT.name} ontbreekt — sla feature-rebuild over.', level='warning')

    # Safety: only train when there is enough labelled data. This protects the
    # currently-loaded production model from being overwritten by a model that
    # was trained on dummy/insufficient data (which would break entry signals).
    ready, reason = _training_data_ready()
    if not ready:
        log(f'auto_retrain: SKIPPING XGBoost training: {reason}. '
            f'Existing model {cfg.get("XGB_MODEL_PATH", "ai/ai_xgb_model.json")} kept.', level='warning')
    else:
        cmd = build_train_command(train_args)
        log(f'auto_retrain: running XGBoost training pipeline (cmd: {cmd}).')
        try:
            subprocess.run(cmd, check=True)
            trained = True
        except subprocess.CalledProcessError as exc:
            log(f'auto_retrain: XGBoost training failed with exit code {exc.returncode}', level='error')
            raise

    # Also train LSTM if enabled (only when training script exists)
    if cfg.get('USE_LSTM', False):
        lstm_script = _PROJECT_ROOT / 'scripts' / 'train_lstm_model.py'
        if not lstm_script.exists():
            log(f'auto_retrain: SKIPPING LSTM training: {lstm_script.name} not found. '
                f'Existing model models/lstm_price_model.h5 kept.', level='warning')
        else:
            lstm_cmd = [sys.executable, str(lstm_script)]
            log(f'auto_retrain: running LSTM training pipeline (cmd: {lstm_cmd}).')
            try:
                subprocess.run(lstm_cmd, check=True)
                log('auto_retrain: LSTM training completed successfully.')
            except subprocess.CalledProcessError as exc:
                log(f'auto_retrain: LSTM training failed with exit code {exc.returncode}', level='warning')
                # Don't raise - LSTM failure shouldn't block XGBoost success

    # Update metrics to mark this run; fallback to current time if file missing
    last_ts, metrics = load_metrics()
    trained_at = metrics.get('trained_at') if metrics else int(time.time())
    due_dt = compute_due_time(last_ts, interval_days, target_time)
    log(f'auto_retrain: completed training at {trained_at}.')
    return {'ran': trained, 'next_due': due_dt, 'last_trained': last_ts}


def run_loop(args: argparse.Namespace, poll_seconds: int) -> None:
    poll_seconds = max(60, int(poll_seconds))
    log(f'auto_retrain: loop mode geactiveerd (interval {poll_seconds} seconden).')
    try:
        while True:
            start = time.time()
            try:
                result = maybe_retrain(args)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                log(f'auto_retrain: fout tijdens retrain-check ({exc}); probeert later opnieuw.', level='error')
                result = None

            if getattr(args, 'dry_run', False):
                break

            sleep_for = poll_seconds
            next_due = None
            if result:
                next_due = result.get('next_due')
            if next_due:
                now = datetime.now(timezone.utc)
                delta = (next_due - now).total_seconds()
                if result and result.get('ran') and delta > poll_seconds:
                    sleep_for = int(delta)
                elif delta > 0:
                    sleep_for = min(poll_seconds, max(60, int(delta)))
            sleep_for = max(60, int(sleep_for))
            log_msg = f'auto_retrain: volgende check over {sleep_for}s'
            if next_due:
                log_msg += f' (next_due={next_due.isoformat()} UTC)'
            log(log_msg + '.', level='debug')
            elapsed = time.time() - start
            time.sleep(max(5.0, float(sleep_for) - elapsed))
    except KeyboardInterrupt:
        log('auto_retrain: loop onderbroken door gebruiker, stoppen.')
    


def main():  # pragma: no cover - entry point
    args = parse_args()
    if args.dry_run and args.loop:
        log('auto_retrain: --dry-run negeert loop-modus; voer enkele check uit.')
    if args.dry_run:
        maybe_retrain(args)
        return
    if args.loop:
        run_loop(args, args.loop)
    else:
        maybe_retrain(args)


if __name__ == '__main__':  # pragma: no cover
    # Single-instance check + PID guard using Windows Mutex
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts' / 'helpers'))
        from single_instance import ensure_single_instance_or_exit
        ensure_single_instance_or_exit('auto_retrain.py', allow_claim=True)
    except ImportError:
        pass  # single_instance module not available, skip check
    
    pid_guard()
    main()
