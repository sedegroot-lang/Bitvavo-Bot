"""Continuous shadow rotation observer.

Runs forever, evaluating shadow rotations every SHADOW_OBSERVE_INTERVAL_MIN
(default 15) and backfilling outcomes for entries older than 6h. Designed
to run as a separate Python process alongside the main bot so a silent
crash in the bot doesn't kill the observer (and vice-versa).

Launch:
    .\\.venv\\Scripts\\python.exe scripts/run_shadow_periodic.py

Stop with Ctrl+C.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from python_bitvavo_api.bitvavo import Bitvavo  # noqa: E402

import bot.api as _api  # noqa: E402
from bot import shadow_rotation  # noqa: E402
from modules.config import load_config  # noqa: E402

CFG = load_config()
INTERVAL_MIN = float(CFG.get("SHADOW_OBSERVE_INTERVAL_MIN", 15))
BACKFILL_AGE_H = float(CFG.get("SHADOW_BACKFILL_MIN_AGE_HOURS", 6))


def _make_client() -> Bitvavo:
    return Bitvavo({
        "APIKEY": os.getenv("BITVAVO_API_KEY"),
        "APISECRET": os.getenv("BITVAVO_API_SECRET"),
    })


def _load_open_trades() -> dict:
    p = PROJECT_ROOT / "data" / "trade_log.json"
    if not p.exists():
        return {}
    try:
        with p.open("r", encoding="utf-8") as f:
            doc = json.load(f)
        return doc.get("open", {}) if isinstance(doc, dict) else {}
    except Exception:
        return {}


def _load_candidates() -> list:
    p = PROJECT_ROOT / "data" / "ai_suggestions.json"
    if not p.exists():
        return []
    try:
        with p.open("r", encoding="utf-8") as f:
            doc = json.load(f)
        out = []
        for i in doc.get("insights") or []:
            if isinstance(i, dict) and i.get("market"):
                out.append({
                    "market": i.get("market"),
                    "score": float(i.get("score", 0) or 0),
                    "expected_pct": float(i.get("expected_pct", 0) or 0),
                })
        return out
    except Exception:
        return []


def _now_price(bv: Bitvavo, market: str):
    try:
        r = _api.safe_call(bv.tickerPrice, {"market": market})
        if isinstance(r, dict) and "price" in r:
            return float(r["price"])
    except Exception:
        return None
    return None


def _historical_price(bv: Bitvavo, market: str, ts: float):
    """Best-effort historical price from 1m candles."""
    try:
        end_ms = int(ts * 1000) + 60_000
        start_ms = int(ts * 1000) - 60_000
        r = _api.safe_call(
            bv.candles,
            market, "1m",
            {"start": start_ms, "end": end_ms, "limit": 5},
        )
        if isinstance(r, list) and r:
            row = r[0]
            if isinstance(row, list) and len(row) >= 5:
                return float(row[4])  # close price
    except Exception:
        return None
    return None


def main() -> None:
    bv = _make_client()
    _api.init(bv, CFG)
    print(f"[shadow_periodic] starting — interval={INTERVAL_MIN}min backfill_age={BACKFILL_AGE_H}h")
    while True:
        try:
            cfg = load_config()
            cfg["SHADOW_FORCE_OBSERVE"] = True
            opens = _load_open_trades()
            cands = _load_candidates()
            max_open = int(cfg.get("MAX_OPEN_TRADES", 4))
            prices = {}
            for m in list(opens.keys()) + [c.get("market") for c in cands[:5]]:
                if not m or m in prices:
                    continue
                p = _now_price(bv, m)
                if p:
                    prices[m] = p
            sugg = shadow_rotation.evaluate(
                opens, cands,
                max_open_trades=max_open,
                current_prices=prices,
                config=cfg,
            )
            updated = shadow_rotation.backfill_outcomes(
                fetch_price_now=lambda m: _now_price(bv, m),
                fetch_price_at=lambda m, t: _historical_price(bv, m, t),
                min_age_hours=BACKFILL_AGE_H,
                fees_pct=float(cfg.get("ROTATE_FEES_PCT_ROUNDTRIP", 0.5)),
            )
            ts_str = time.strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{ts_str}] suggestions={len(sugg)} backfilled={updated} candidates={len(cands)} opens={len(opens)}")
        except KeyboardInterrupt:
            print("[shadow_periodic] stopping (ctrl+c)")
            return
        except Exception as exc:
            print(f"[shadow_periodic] error: {exc}")
        time.sleep(max(60.0, INTERVAL_MIN * 60.0))


if __name__ == "__main__":
    main()
