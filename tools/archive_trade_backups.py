#!/usr/bin/env python3
"""Utility to move old trade_log backups into an archive directory with optional compression."""

import argparse
import gzip
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterable, List

DEFAULT_PATTERN = "trade_log.json.bak*"
DEFAULT_KEEP = 5
DEFAULT_ARCHIVE = Path("archive/logs/trade_log")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Archive old trade_log backups to keep workspace lean.")
    parser.add_argument("--pattern", default=DEFAULT_PATTERN, help="Glob pattern to select backup files.")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP, help="How many recent backups to keep in place.")
    parser.add_argument(
        "--archive-dir",
        default=str(DEFAULT_ARCHIVE),
        help="Directory to move (or compress) archived backups into.",
    )
    parser.add_argument("--compress", action="store_true", help="Compress archived files with gzip.")
    parser.add_argument("--compression-level", type=int, default=6, help="Gzip compression level when --compress is used.")
    parser.add_argument("--dry-run", action="store_true", help="Only report actions without modifying files.")
    parser.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Project root that contains the trade logs.",
    )
    return parser.parse_args()


def resolve_files(root: Path, pattern: str) -> List[Path]:
    # Sorting newest first makes it easy to keep the freshest backups in place.
    files = sorted(root.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return [p for p in files if p.is_file()]


def ensure_archive_dir(path: Path, dry_run: bool) -> None:
    if path.exists():
        return
    if dry_run:
        print(f"[archive] Would create directory: {path}")
        return
    path.mkdir(parents=True, exist_ok=True)


def compress_file(source: Path, destination: Path, level: int, dry_run: bool) -> None:
    if dry_run:
        print(f"[archive] Would compress {source} -> {destination}")
        return
    with source.open("rb") as src, gzip.open(destination, "wb", compresslevel=level) as gz:
        shutil.copyfileobj(src, gz)


def move_file(source: Path, destination: Path, dry_run: bool) -> None:
    if dry_run:
        print(f"[archive] Would move {source} -> {destination}")
        return
    shutil.move(str(source), str(destination))


def unique_destination(base: Path) -> Path:
    """Avoid overwriting archived files by appending a timestamp when necessary."""
    if not base.exists():
        return base
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    return base.with_name(f"{base.name}.{timestamp}")


def archive_backups(files: Iterable[Path], keep: int, archive_dir: Path, compress: bool, level: int, dry_run: bool) -> None:
    survivors = list(files)
    if len(survivors) <= keep:
        print(f"[archive] {len(survivors)} backups found; nothing to archive (keep={keep}).")
        return

    ensure_archive_dir(archive_dir, dry_run)
    to_archive = survivors[keep:]

    for entry in to_archive:
        archive_target = archive_dir / entry.name
        if compress:
            archive_target = archive_target.with_suffix(archive_target.suffix + ".gz")
            archive_target = unique_destination(archive_target)
            compress_file(entry, archive_target, level, dry_run)
            if not dry_run:
                entry.unlink()
        else:
            archive_target = unique_destination(archive_target)
            move_file(entry, archive_target, dry_run)

    kept = [p.name for p in survivors[:keep]]
    archived = [p.name for p in to_archive]
    print(f"[archive] Kept: {', '.join(kept) if kept else 'no files'}")
    if archived:
        print(f"[archive] Archived: {', '.join(archived)}")
    else:
        print("[archive] No files archived.")


def main() -> None:
    args = parse_args()
    root = Path(args.root).resolve()
    files = resolve_files(root, args.pattern)

    if not files:
        print(f"[archive] Geen bestanden gevonden voor patroon: {args.pattern}")
        return

    archive_dir = Path(args.archive_dir)
    if not archive_dir.is_absolute():
        archive_dir = root / archive_dir

    archive_backups(files, args.keep, archive_dir, args.compress, args.compression_level, args.dry_run)


if __name__ == "__main__":
    main()
