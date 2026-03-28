"""Local state guard — mirrors critical state files outside OneDrive.

OneDrive can revert files to older versions when syncing across devices.
This module keeps a local copy of critical state files at
%LOCALAPPDATA%/BotConfig/state/ which is OUTSIDE OneDrive.

On save: writes to both OneDrive path AND local path.
On load: compares both, returns the one with the highest _save_ts.

Protected files:
  - data/trade_log.json  (open positions, DCA state, profits)
  - data/bot_state.json  (runtime state: timestamps, flags)
  - data/trade_archive.json (historical closed trades)
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

_log = logging.getLogger("local_state")

# Local state directory — OUTSIDE OneDrive, never synced/reverted
LOCAL_STATE_DIR = Path(
    os.environ.get('LOCALAPPDATA', os.path.expanduser('~'))
) / 'BotConfig' / 'state'


def _ensure_dir() -> None:
    """Create local state directory if it doesn't exist."""
    LOCAL_STATE_DIR.mkdir(parents=True, exist_ok=True)


def _local_path(filename: str) -> Path:
    """Get the local mirror path for a given filename.

    Accepts both 'trade_log.json' and 'data/trade_log.json'.
    """
    return LOCAL_STATE_DIR / Path(filename).name


def mirror_to_local(filename: str, data: Dict[str, Any]) -> None:
    """Save a copy of data to the local state directory.

    Adds/updates _save_ts in the data to track which copy is newest.
    Non-blocking: failures are logged but never raised.
    """
    try:
        _ensure_dir()
        local = _local_path(filename)
        # Stamp the data so we can compare freshness
        data_copy = dict(data)
        data_copy['_save_ts'] = time.time()
        tmp = str(local) + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data_copy, f, indent=2)
        os.replace(tmp, str(local))
    except Exception as exc:
        _log.warning("local_state: mirror_to_local(%s) failed: %s", filename, exc)


def load_local(filename: str) -> Optional[Dict[str, Any]]:
    """Load data from the local state directory.

    Returns None if file doesn't exist or can't be read.
    """
    try:
        local = _local_path(filename)
        if local.exists():
            with open(local, 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as exc:
        _log.warning("local_state: load_local(%s) failed: %s", filename, exc)
    return None


def load_freshest(
    filename: str,
    onedrive_data: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compare OneDrive and local copies, return the freshest one.

    Uses _save_ts field embedded by mirror_to_local(). If only one exists,
    returns that one. If neither exists, returns empty dict.

    Args:
        filename: The filename (e.g. 'trade_log.json')
        onedrive_data: Data loaded from the OneDrive path (may be None)

    Returns:
        The freshest data dict (with _save_ts stripped).
    """
    local_data = load_local(filename)

    od_ts = 0.0
    local_ts = 0.0

    if onedrive_data and isinstance(onedrive_data, dict):
        od_ts = float(onedrive_data.get('_save_ts', 0) or 0)

    if local_data and isinstance(local_data, dict):
        local_ts = float(local_data.get('_save_ts', 0) or 0)

    # Pick the one with the highest _save_ts
    if local_ts > od_ts and local_data:
        _log.info(
            "local_state: using LOCAL copy of %s (local_ts=%.0f > od_ts=%.0f, delta=%.0fs)",
            filename, local_ts, od_ts, local_ts - od_ts,
        )
        result = dict(local_data)
        result.pop('_save_ts', None)
        return result
    elif onedrive_data and isinstance(onedrive_data, dict):
        result = dict(onedrive_data)
        result.pop('_save_ts', None)
        return result
    elif local_data:
        # OneDrive has nothing, local has something
        result = dict(local_data)
        result.pop('_save_ts', None)
        return result

    return {}


def stamp_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Add _save_ts to data before writing to OneDrive path.

    This allows load_freshest() to compare ages even when
    the file was only written to OneDrive.
    """
    data['_save_ts'] = time.time()
    return data
