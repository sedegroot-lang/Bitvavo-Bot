"""Sync EUR deposit history from Bitvavo into config/deposits.json.

Run manually or from the scheduler. Writes total + per-deposit list. Idempotent
— safe to re-run, fully overwrites the file with the latest snapshot.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Make project root importable when executed directly
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from modules.bitvavo_client import get_bitvavo  # noqa: E402

OUT = ROOT / "config" / "deposits.json"


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def fetch_deposits(symbol: str = "EUR") -> list[dict]:
    bv = get_bitvavo()
    if bv is None:
        raise SystemExit("No Bitvavo API credentials available (set BITVAVO_API_KEY/SECRET).")
    raw = bv.depositHistory({"symbol": symbol})
    if isinstance(raw, dict) and "errorCode" in raw:
        raise SystemExit(f"Bitvavo error: {raw}")
    if not isinstance(raw, list):
        raise SystemExit(f"Unexpected response: {type(raw).__name__}")
    return raw


def normalize(entries: list[dict]) -> list[dict]:
    out: list[dict] = []
    for e in entries:
        try:
            amount = float(e.get("amount", 0) or 0)
            ts_ms = int(e.get("timestamp", 0) or 0)
        except (TypeError, ValueError):
            continue
        if amount <= 0:
            continue
        status = (e.get("status") or "").lower()
        if status and status not in ("completed", "success", "settled"):
            # only count completed deposits
            continue
        ts_sec = ts_ms / 1000.0
        iso = datetime.fromtimestamp(ts_sec, tz=timezone.utc).isoformat()
        out.append({
            "amount": round(amount, 2),
            "timestamp": ts_ms,
            "date": iso,
            "txId": e.get("txId") or e.get("address") or "",
            "note": e.get("note", ""),
        })
    out.sort(key=lambda r: r["timestamp"])
    return out


def main() -> int:
    raw = fetch_deposits("EUR")
    deposits = normalize(raw)
    total = round(sum(d["amount"] for d in deposits), 2)
    payload = {
        "total_deposited_eur": total,
        "currency": "EUR",
        "count": len(deposits),
        "last_synced": datetime.now(timezone.utc).isoformat(),
        "sync_source": "bitvavo_api",
        "deposits": deposits,
    }
    _atomic_write(OUT, payload)
    print(f"[sync_deposits] wrote {len(deposits)} deposits, total €{total:.2f} → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
