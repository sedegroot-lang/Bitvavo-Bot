import os
import shutil
import time
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_OLD = ROOT / 'archive' / 'old'
ARCHIVE_OLD.mkdir(parents=True, exist_ok=True)

# Files/patterns to archive (non-critical diagnostics/logs/backups)
PATTERNS = [
    'bot_log.txt',
    'param_log.txt',
    'heartbeat.json',
    'trade_log.json.bak.*',
    'sync_raw_*.json',
    'pending_saldo.json',
    'price_cache.json',
    'trade_log.json.bak.*',
]

# Subfolders to keep tidy
SUBFOLDERS = [
    ROOT / 'archive',
    ROOT / 'logs',
]

CONFIG_FILE = ROOT / 'bot_config.json'

LOW_RETENTION = {
    'LOG_LEVEL': 'INFO',
    'LOG_MAX_BYTES': 262_144,  # 256 KB
    'LOG_BACKUP_COUNT': 2,
    'TEST_MODE': True,
    'STOP_AFTER_SECONDS': 20
}


def move_matches_to_archive_old():
    moved = []
    for pattern in PATTERNS:
        for path in ROOT.glob(pattern):
            try:
                # Skip anything already inside archive/old
                try:
                    if Path(path).is_relative_to(ARCHIVE_OLD):
                        continue
                except AttributeError:
                    # Fallback for very old Python (not expected here)
                    if str(ARCHIVE_OLD) in str(path):
                        continue
                # Skip if it's the active trade_log.json (don't move main ledger)
                if path.name == 'trade_log.json':
                    continue
                dest = ARCHIVE_OLD / f"{path.name}"
                # add timestamp to avoid collisions for backups
                if dest.exists():
                    dest = ARCHIVE_OLD / f"{path.stem}.{int(time.time())}{path.suffix}"
                shutil.move(str(path), str(dest))
                moved.append((path.name, dest.name))
            except Exception as e:
                print(f"Failed moving {path}: {e}")
    return moved


def move_subfolder_files():
    moved = []
    for folder in SUBFOLDERS:
        if not folder.exists() or not folder.is_dir():
            continue
        for path in folder.rglob('*'):
            if path.is_dir():
                continue
            try:
                # Skip anything already under archive/old to avoid infinite nesting
                try:
                    if path.is_relative_to(ARCHIVE_OLD):
                        continue
                except AttributeError:
                    if str(ARCHIVE_OLD) in str(path):
                        continue
                # Recreate subpath under archive/old to avoid flattening
                rel = path.relative_to(ROOT)
                dest = ARCHIVE_OLD / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                # If destination exists, add timestamp suffix
                if dest.exists():
                    dest = dest.with_name(f"{dest.stem}.{int(time.time())}{dest.suffix}")
                shutil.move(str(path), str(dest))
                moved.append((str(rel), str(dest.relative_to(ARCHIVE_OLD))))
            except Exception as e:
                print(f"Failed moving {path}: {e}")
    return moved


def ensure_low_log_retention():
    if not CONFIG_FILE.exists():
        print('bot_config.json not found; skipping retention update')
        return False
    try:
        with CONFIG_FILE.open('r', encoding='utf-8') as f:
            cfg = json.load(f)
    except Exception as e:
        print(f'Cannot read bot_config.json: {e}')
        return False
    changed = False
    for k, v in LOW_RETENTION.items():
        if cfg.get(k) != v:
            cfg[k] = v
            changed = True
    if changed:
        tmp = CONFIG_FILE.with_suffix('.json.tmp')
        with tmp.open('w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2)
        os.replace(tmp, CONFIG_FILE)
    return changed


def run_sanity_dry_run():
    # Run the bot for a short dry-run; let trailing_bot read TEST_MODE+STOP_AFTER_SECONDS from config
    import subprocess
    try:
        result = subprocess.run(
            ['python', str(ROOT / 'trailing_bot.py')],
            cwd=str(ROOT),
            capture_output=True,
            text=False,  # capture as bytes to avoid Windows cp1252 decode issues with emojis
            timeout=180
        )
        out = (result.stdout or b'')[-4000:].decode('utf-8', errors='ignore')
        err = (result.stderr or b'')[-4000:].decode('utf-8', errors='ignore')
        if out:
            print(out)
        if result.returncode != 0:
            print('Dry-run exited with non-zero code:', result.returncode)
            if err:
                print(err)
            return False
        return True
    except subprocess.TimeoutExpired:
        print('Dry-run timed out')
        return False
    except Exception as e:
        print('Dry-run failed:', e)
        return False


def main():
    print('== Reset workspace: clean, archive, verify ==')
    moved = move_matches_to_archive_old()
    moved2 = move_subfolder_files()
    print(f'Moved {len(moved) + len(moved2)} items to archive/old')
    changed = ensure_low_log_retention()
    print('Config retention updated' if changed else 'Config retention unchanged')
    ok = run_sanity_dry_run()
    print('Dry-run OK' if ok else 'Dry-run FAILED')


if __name__ == '__main__':
    main()
