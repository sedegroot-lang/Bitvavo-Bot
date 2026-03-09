#!/usr/bin/env python3
"""Format the AI change history newest-first and print human-friendly lines.

Rules:
- Sort by timestamp descending (newest first).
- For entries with identical timestamps, preserve reverse insertion order so batched changes (same ts) appear in the desired order (the last-applied first).
"""
from __future__ import annotations
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules import storage


def main():
    storage.migrate_json_dataset('ai_changes', 'ai_changes.json', table='changes')
    hist = storage.fetch_all('ai_changes', table='changes') or []
    # Keep original insertion index
    for i, e in enumerate(hist):
        e['_orig_idx'] = i
    # Sort by ts desc, and for equal ts sort by orig_idx desc to reverse insertion order
    hist_sorted = sorted(hist, key=lambda e: (float(e.get('ts', 0)), int(e.get('_orig_idx', 0))), reverse=True)
    for e in hist_sorted:
        ts = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(float(e.get('ts', 0))))
        param = e.get('param')
        frm = e.get('from')
        to = e.get('to')
        reason = e.get('reason', '')
        print(f"[{ts}] {param}: {frm} -> {to} ({reason})\n")

if __name__ == '__main__':
    main()
