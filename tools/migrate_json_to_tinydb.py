"""Idempotent migration helper to port chosen JSON datasets to TinyDB using modules.storage.

This script migrates a set of known JSON files into per-dataset tinydb files under the
`data/` storage root used by `modules.storage.StorageManager`. It will skip migration if
a target TinyDB table already has rows (safe to run repeatedly). Use --force to overwrite.

Usage:
    python tools/migrate_json_to_tinydb.py [--force]

The script writes backups of each JSON file to `tools/backups/` before migration.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from modules import storage
from modules.logging_utils import log

ROOT = Path(__file__).resolve().parents[1]
BACKUP_DIR = ROOT / 'tools' / 'backups'
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

# Mapping: dataset name -> json_path relative to repo root
DATASETS = {
    'pending_saldo': 'pending_saldo.json',
    'price_cache': 'price_cache.json',
    'sync_raw_markets': 'sync_raw_markets.json',
    'sync_raw_balances': 'sync_raw_balances.json',
    'sync_removed_cache': 'sync_removed_cache.json',
    'ai_changes': 'ai_changes.json',
    'ai_suggestions': 'ai_suggestions.json',
    'ai_heartbeat': 'ai_heartbeat.json',
    'heartbeat': 'heartbeat.json',
    'top30_markets': 'top30_eur_markets.json',
    'top50_markets': 'top50_eur_markets.json',
}


def backup_file(src: Path) -> Path | None:
    if not src.exists():
        return None
    dst = BACKUP_DIR / f"{src.name}.{int(src.stat().st_mtime)}.bak"
    try:
        dst.write_text(src.read_text(encoding='utf-8'), encoding='utf-8')
        return dst
    except Exception as exc:
        log(f"Backup failed for {src}: {exc}", level='warning')
        return None


def migrate(force: bool = False) -> None:
    for name, rel in DATASETS.items():
        src = ROOT / rel
        if not src.exists():
            log(f"Skipping {rel}: source not found", level='debug')
            continue
        backup = backup_file(src)
        try:
            storage.migrate_json_dataset(name, str(src), force=force)
            log(f"Migrated {rel} -> dataset '{name}' (backup: {backup})")
        except Exception as exc:
            log(f"Migration failed for {rel}: {exc}", level='error')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--force', action='store_true', help='Force re-import even if target non-empty')
    args = p.parse_args()
    migrate(force=args.force)
