"""bot.path_utils — Path resolution + throttled logging + JSONL append helpers.

Extracted from `trailing_bot.py` during road-to-10 #066. Pure stdlib; the only
dependency is `bot.shared.state` for log function and `PROJECT_ROOT`.

Public API:
- log_throttled(key, msg, interval, level)
- ensure_parent_dir(path)
- resolve_path(path_like)
- append_trade_pnl_jsonl(closed_entry)
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Union

from bot.shared import state

# Module-private throttle memory
_log_throttle_ts: Dict[str, float] = {}


def _log(msg: str, level: str = 'info') -> None:
    try:
        state.log(msg, level=level)
    except Exception:
        pass


def log_throttled(key: str, msg: str, interval: float = 60.0, level: str = 'info') -> bool:
    """Log a message at most once per `interval` seconds for the given key.

    Returns True when the message was actually logged, False otherwise.
    """
    now = time.time()
    last = _log_throttle_ts.get(key, 0.0)
    if now - last >= interval:
        _log_throttle_ts[key] = now
        _log(msg, level=level)
        return True
    return False


def reset_throttle() -> None:
    """Test helper — clear throttle memory."""
    _log_throttle_ts.clear()


def ensure_parent_dir(path: Union[str, Path]) -> None:
    try:
        parent = Path(path).parent
        if parent:
            parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        _log(f"[ERROR] Failed to create parent directory for {path}: {e}", level='error')


def resolve_path(path_like: Union[str, Path]) -> Path:
    path_obj = Path(path_like)
    if not path_obj.is_absolute():
        root = getattr(state, 'PROJECT_ROOT', None) or Path(__file__).resolve().parent.parent
        path_obj = Path(root) / path_obj
    return path_obj


def append_trade_pnl_jsonl(closed_entry: Dict[str, Any], target_path: Union[str, Path, None] = None) -> bool:
    """Persist per-trade PnL to JSONL for PF/winrate analysis. Returns True on success."""
    try:
        if target_path is None:
            target_path = state.CONFIG.get('TRADE_PNL_HISTORY_FILE', 'data/trade_pnl_history.jsonl')
        path = resolve_path(target_path)
        ensure_parent_dir(path)

        opened_ts = closed_entry.get('opened_ts') or closed_entry.get('timestamp_open')
        closed_ts = closed_entry.get('timestamp') or closed_entry.get('closed_ts')
        hold_seconds = None
        try:
            if opened_ts is not None and closed_ts is not None:
                hold_seconds = max(0.0, float(closed_ts) - float(opened_ts))
        except Exception:
            hold_seconds = None

        record = {
            'ts': time.time(),
            'market': closed_entry.get('market'),
            'profit_eur': closed_entry.get('profit'),
            'profit_pct': closed_entry.get('profit_pct'),
            'invested_eur': closed_entry.get('invested_eur'),
            'amount': closed_entry.get('amount'),
            'buy_price': closed_entry.get('buy_price'),
            'sell_price': closed_entry.get('sell_price'),
            'opened_ts': opened_ts,
            'closed_ts': closed_ts,
            'hold_seconds': hold_seconds,
            'reason': closed_entry.get('reason'),
            'trailing_used': closed_entry.get('trailing_used'),
            'dca_buys': closed_entry.get('dca_buys'),
        }

        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=True) + '\n')
        return True
    except Exception as e:
        _log(f"PnL export failed: {e}", level='debug')
        return False
