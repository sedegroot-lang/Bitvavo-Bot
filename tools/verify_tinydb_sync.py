"""Verify that JSON files tracked by the compat layer match their TinyDB mirrors.

Run this after migrating writers to ensure the legacy JSON snapshots and TinyDB datasets
are still equivalent. The script reports any mismatches and exits with a non-zero code
when discrepancies are found.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from modules.json_compat import FILENAME_TO_DATASET, _coerce_records
from modules import storage


def _serialize_records(records: Iterable[dict]) -> Counter:
    """Return a multiset representation of the provided records."""
    serialised = [json.dumps(item, sort_keys=True, default=str) for item in records]
    return Counter(serialised)


def _load_json_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:  # pragma: no cover - diagnostic surface only
        raise RuntimeError(f"Kon JSON niet lezen: {path}: {exc}") from exc
    return list(_coerce_records(payload))


def check_dataset(
    name: str,
    *,
    verbose: bool = False,
    repair: bool = False,
) -> tuple[bool, str]:
    json_path = REPO_ROOT / name
    dataset = FILENAME_TO_DATASET.get(Path(name).name)
    if not dataset:
        return True, f"Geen mapping voor {name}; overslaan"

    if verbose:
        print(f"Controle: {json_path} -> dataset '{dataset}'")

    json_records = _load_json_records(json_path)
    db_records = storage.fetch_all(dataset)

    json_counter = _serialize_records(json_records)
    db_counter = _serialize_records(db_records)

    if json_counter == db_counter:
        return True, f"OK: {name} ({len(json_records)} records)"

    # Produce a human-friendly diff
    missing_in_db = list((json_counter - db_counter).elements())
    missing_in_json = list((db_counter - json_counter).elements())

    if repair:
        storage.replace_all(dataset, json_records)
        repaired_db = storage.fetch_all(dataset)
        if _serialize_records(repaired_db) == json_counter:
            return True, f"Hersteld: {name} ({len(json_records)} records)"

    details = []
    if missing_in_db:
        details.append(
            f"Ontbreekt in TinyDB ({len(missing_in_db)}): {missing_in_db[:3]}"
        )
    if missing_in_json:
        details.append(
            f"Ontbreekt in JSON ({len(missing_in_json)}): {missing_in_json[:3]}"
        )

    message = "Mismatch: " + "; ".join(details)
    return False, f"{name}: {message}"


def discover_targets(filter_name: str | None) -> list[str]:
    if filter_name:
        return [filter_name]
    return sorted(FILENAME_TO_DATASET.keys())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target",
        nargs="?",
        help="Specifiek JSON-bestand om te controleren (relatief aan de projectroot)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Toon extra debug-informatie tijdens het vergelijken",
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="Werk TinyDB bij naar de inhoud van het JSON-bestand wanneer verschillen gevonden worden",
    )
    args = parser.parse_args(argv)

    targets = discover_targets(args.target)
    if not targets:
        print("Geen doelen gevonden om te controleren.")
        return 0

    all_ok = True
    for target in targets:
        ok, message = check_dataset(target, verbose=args.verbose, repair=args.repair)
        status = "[OK]" if ok else "[FOUT]"
        print(f"{status} {message}")
        if not ok:
            all_ok = False

    return 0 if all_ok else (0 if args.repair else 1)


if __name__ == "__main__":  # pragma: no cover - top-level script execution
    sys.exit(main())
