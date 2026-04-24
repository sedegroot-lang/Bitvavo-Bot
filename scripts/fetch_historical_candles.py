"""
Fetch historical 1h candles for top markets via Bitvavo public API.
Saves to data/historical_candles/<MARKET>_1h.csv

Usage:
    python scripts/fetch_historical_candles.py --markets BTC-EUR ETH-EUR ... --days 365
"""
from __future__ import annotations
import argparse, csv, os, sys, time
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from python_bitvavo_api.bitvavo import Bitvavo

OUT_DIR = ROOT / "data" / "historical_candles"
OUT_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_MARKETS = [
    "BTC-EUR", "ETH-EUR", "SOL-EUR", "DOGE-EUR", "XRP-EUR",
    "ADA-EUR", "AVAX-EUR", "LINK-EUR", "MATIC-EUR", "DOT-EUR",
    "UNI-EUR", "AAVE-EUR", "ATOM-EUR", "LTC-EUR", "BCH-EUR",
    "ARB-EUR", "INJ-EUR", "FET-EUR", "RENDER-EUR", "NEAR-EUR",
    "POL-EUR", "OP-EUR", "APT-EUR", "ALGO-EUR", "FIL-EUR",
]

INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


def fetch_candles(bv: Bitvavo, market: str, interval: str, days: int) -> list[list]:
    """Page through historical candles (Bitvavo returns max 1440 per call)."""
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 86_400_000
    step_ms = INTERVAL_MS[interval]
    all_candles: list[list] = []
    seen = set()
    cursor_end = end_ms

    while cursor_end > start_ms:
        page_start = max(start_ms, cursor_end - 1440 * step_ms)
        try:
            resp = bv.candles(market, interval, {"limit": 1440, "start": page_start, "end": cursor_end})
        except Exception as e:
            print(f"  ! err {market} {interval}: {e}")
            break
        if not resp or not isinstance(resp, list) or not isinstance(resp[0], list):
            break
        new_rows = []
        for r in resp:
            ts = int(r[0])
            if ts in seen:
                continue
            seen.add(ts)
            new_rows.append([ts, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])])
        all_candles.extend(new_rows)
        if len(resp) < 50:
            break
        oldest = min(int(r[0]) for r in resp)
        if oldest <= page_start + step_ms:
            break
        cursor_end = oldest
        time.sleep(0.15)
    all_candles.sort(key=lambda r: r[0])
    return all_candles


def write_csv(path: Path, candles: list[list]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts_ms", "open", "high", "low", "close", "volume"])
        for r in candles:
            w.writerow(r[:6])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--markets", nargs="+", default=DEFAULT_MARKETS)
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--days", type=int, default=365)
    args = ap.parse_args()

    bv = Bitvavo({"APIKEY": os.getenv("BITVAVO_API_KEY", ""), "APISECRET": os.getenv("BITVAVO_API_SECRET", "")})

    for m in args.markets:
        out = OUT_DIR / f"{m}_{args.interval}.csv"
        print(f"[{m}] fetching {args.days}d {args.interval} ...", end=" ", flush=True)
        try:
            candles = fetch_candles(bv, m, args.interval, args.days)
        except Exception as e:
            print(f"FAIL: {e}")
            continue
        if not candles:
            print("EMPTY")
            continue
        write_csv(out, candles)
        days_actual = (candles[-1][0] - candles[0][0]) / 86_400_000
        print(f"{len(candles)} bars ({days_actual:.0f}d) -> {out.name}")


if __name__ == "__main__":
    main()
