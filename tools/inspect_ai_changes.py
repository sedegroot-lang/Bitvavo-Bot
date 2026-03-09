#!/usr/bin/env python3
"""Print AI change history from TinyDB (same storage used by dashboard)."""
from __future__ import annotations
import time
from pathlib import Path
import os
import json

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import storage


def main():
    # Ensure migration from JSON -> tinydb has been run so we read the same source
    json_path = Path('ai') / 'ai_changes.json'
    try:
        storage.migrate_json_dataset('ai_changes', str(json_path), table='changes')
    except Exception:
        pass
    try:
        hist = storage.fetch_all('ai_changes', table='changes')
    except Exception as e:
        print('Error reading storage:', e)
        return
    if not hist:
        print('No AI change history found.')
        return
    hist_sorted = sorted(hist, key=lambda e: e.get('ts', 0))
    for e in hist_sorted:
        ts = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(e.get('ts', 0)))
        print(f"[{ts}] {e.get('param')}: {e.get('from')} -> {e.get('to')} ({e.get('reason','')})")
    print('\nTotal entries:', len(hist_sorted))


if __name__ == '__main__':
    main()
