"""
Build trade_features.csv from trade_archive.json + trade_log.json (FIX #044)

The regular XGBoost model (`ai/ai_xgb_model.json`) expects 7 features in this
exact order: rsi, macd, sma_short, sma_long, volume, bb_position, stochastic_k.

Archived trades record `rsi_at_entry`, `macd_at_entry`, `sma_short_at_entry`,
`sma_long_at_entry`, `volume_24h_eur`. They do NOT record `bb_position` or
`stochastic_k`, so we use neutral defaults (0.5, 50.0) — same defaults as
`modules.ml.feature_engineering()` does for missing keys.

Label: 1 if profit > 0 else 0.

Output: ./trade_features.csv (root of project) — consumed by xgb_walk_forward.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRADE_LOG_PATH = PROJECT_ROOT / "data" / "trade_log.json"
TRADE_ARCHIVE_PATH = PROJECT_ROOT / "data" / "trade_archive.json"
BACKFILL_PATH = PROJECT_ROOT / "data" / "trade_features_backfill.json"
OUTPUT_CSV = PROJECT_ROOT / "trade_features.csv"


def _load_backfill() -> dict:
    if not BACKFILL_PATH.exists():
        return {}
    try:
        return json.loads(BACKFILL_PATH.read_text(encoding="utf-8")) or {}
    except Exception as e:
        print(f"  WARN: could not read {BACKFILL_PATH.name}: {e}")
        return {}


def _trade_key(t: dict) -> str:
    return f"{t.get('market')}|{int(t.get('opened_ts') or t.get('timestamp') or 0)}|{t.get('sell_order_id') or ''}"


_BACKFILL_CACHE: dict = {}


def _load_all_closed():
    closed = []
    if TRADE_LOG_PATH.exists():
        try:
            with TRADE_LOG_PATH.open(encoding="utf-8") as f:
                data = json.load(f)
            closed.extend(data.get("closed", []) or [])
        except Exception as e:
            print(f"  WARN: could not read {TRADE_LOG_PATH}: {e}")
    if TRADE_ARCHIVE_PATH.exists():
        try:
            with TRADE_ARCHIVE_PATH.open(encoding="utf-8") as f:
                arc = json.load(f)
            closed.extend(arc.get("trades", []) if isinstance(arc, dict) else (arc or []))
        except Exception as e:
            print(f"  WARN: could not read {TRADE_ARCHIVE_PATH}: {e}")
    # Dedupe
    seen = set()
    out = []
    for t in closed:
        key = (t.get("market"), t.get("opened_ts") or t.get("timestamp"), t.get("sell_order_id"))
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def _row_from_trade(t: dict) -> dict | None:
    profit = t.get("profit")
    if profit is None:
        return None
    # Fold backfill snapshot into trade dict if the trade is missing real data.
    bf = _BACKFILL_CACHE.get(_trade_key(t)) if _BACKFILL_CACHE else None
    if isinstance(bf, dict) and 'rsi_at_entry' in bf:
        for k, v in bf.items():
            t.setdefault(k, v)
    try:
        rsi = float(t.get("rsi_at_entry", t.get("rsi_at_buy", 50.0)) or 50.0)
        macd = float(t.get("macd_at_entry", t.get("macd_at_buy", 0.0)) or 0.0)
        sma_short = float(t.get("sma_short_at_entry", 0.0) or 0.0)
        sma_long = float(t.get("sma_long_at_entry", 0.0) or 0.0)
        volume = float(t.get("volume_24h_eur", t.get("volume_avg_at_entry", 0.0)) or 0.0)
        bb_position = float(t.get("bb_position_at_entry", t.get("bb_position", 0.5)) or 0.5)
        stochastic_k = float(t.get("stochastic_k_at_entry", t.get("stochastic_k", 50.0)) or 50.0)
        label = 1 if float(profit) > 0 else 0
        ts = t.get("opened_ts") or t.get("timestamp") or 0
    except Exception:
        return None
    return {
        "timestamp": ts,
        "market": t.get("market"),
        "rsi": rsi,
        "macd": macd,
        "sma_short": sma_short,
        "sma_long": sma_long,
        "volume": volume,
        "bb_position": bb_position,
        "stochastic_k": stochastic_k,
        "label": label,
    }


def main() -> int:
    global _BACKFILL_CACHE
    _BACKFILL_CACHE = _load_backfill()
    if _BACKFILL_CACHE:
        print(f"Loaded backfill cache with {len(_BACKFILL_CACHE)} entries")
    closed = _load_all_closed()
    print(f"Loaded {len(closed)} unique closed trades")
    rows = [r for r in (_row_from_trade(t) for t in closed) if r is not None]
    if not rows:
        print("ERROR: no usable rows extracted")
        return 1
    df = pd.DataFrame(rows)
    df = df.sort_values("timestamp").reset_index(drop=True)
    # Keep only rows where the entry indicator snapshot was actually recorded.
    # Older trades (pre-snapshot logging) have rsi=50 + sma_short=0 defaults — useless.
    has_snapshot = (df["rsi"] != 50.0) | (df["sma_short"] != 0.0) | (df["macd"] != 0.0)
    dropped = int((~has_snapshot).sum())
    df = df[has_snapshot].reset_index(drop=True)
    print(f"Rows with real entry snapshot: {len(df)} (dropped {dropped} default-only)")
    if df.empty:
        print("ERROR: no rows with real indicator snapshot — wait until more entries accumulate")
        return 2
    print(f"Label balance: {df['label'].value_counts().to_dict()}")
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"Wrote {len(df)} rows -> {OUTPUT_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
