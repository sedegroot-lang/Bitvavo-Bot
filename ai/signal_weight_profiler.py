"""Per-market signal-score profile builder.

Reads ``data/trade_archive.json`` and produces per-market multipliers that
nudge the entry threshold up or down based on historical expectancy.

Why a multiplier and not per-provider weights?
  The archive only persists the *aggregate* score per trade, not the
  per-provider breakdown. Learning per-provider weights would require either
  (a) re-running the replay engine on historical candles for every trade,
  which is expensive, or (b) starting to log per-provider scores at entry
  (a separate, easy follow-up). Until then, a per-market score multiplier
  is the highest-signal-to-noise lever the data can support.

Output format (``ai/signal_weights.json``)::

    {
      "version": 1,
      "generated_at": "2026-05-06T20:30:00+00:00",
      "default": {"score_multiplier": 1.0, "min_score_override": null},
      "markets": {
        "BTC-EUR": {
            "score_multiplier": 1.10,
            "min_score_override": null,
            "n": 42, "wr": 0.71, "expectancy_eur": 4.20
        },
        "BAD-EUR": {
            "score_multiplier": 0.70,
            "min_score_override": 22.0,
            "n": 18, "wr": 0.33, "expectancy_eur": -1.80
        }
      }
    }

The bot can ignore this file (default behaviour) or load it via
``modules.signals.set_market_weights(load_signal_weights(...))``.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = PROJECT_ROOT / "data" / "trade_archive.json"
WEIGHTS_PATH = PROJECT_ROOT / "ai" / "signal_weights.json"

# ── Tunable defaults ──
DEFAULTS: Dict[str, Any] = {
    "MIN_TRADES": 8,                # need at least this many to compute a profile
    "MULTIPLIER_FLOOR": 0.60,
    "MULTIPLIER_CEIL": 1.30,
    "STRONG_BAD_EXPECTANCY": -1.0,  # below this, also raise min_score
    "STRONG_BAD_OVERRIDE": 22.0,    # min_score for very bad markets
    "EXPECTANCY_NORMAL": 2.0,       # EUR/trade that maps to multiplier 1.0
    "MAX_MARKETS": 200,
}


# ---------- I/O ----------

def _load_trades(path: Path = ARCHIVE) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception:
        return []
    if isinstance(data, dict):
        return list(data.get("trades") or data.get("closed") or [])
    if isinstance(data, list):
        return list(data)
    return []


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        f = float(v)
        if f != f:
            return default
        return f
    except (TypeError, ValueError):
        return default


# ---------- Profile computation ----------

def compute_profiles(
    trades: Iterable[Dict[str, Any]],
    *,
    min_trades: int = DEFAULTS["MIN_TRADES"],
    multiplier_floor: float = DEFAULTS["MULTIPLIER_FLOOR"],
    multiplier_ceil: float = DEFAULTS["MULTIPLIER_CEIL"],
    strong_bad_expectancy: float = DEFAULTS["STRONG_BAD_EXPECTANCY"],
    strong_bad_override: float = DEFAULTS["STRONG_BAD_OVERRIDE"],
    expectancy_normal: float = DEFAULTS["EXPECTANCY_NORMAL"],
) -> Dict[str, Any]:
    """Return ``{market: {score_multiplier, min_score_override, n, wr, expectancy_eur}}``."""
    by_market: Dict[str, List[float]] = defaultdict(list)
    for t in trades:
        m = str(t.get("market") or "").strip()
        if not m:
            continue
        by_market[m].append(_safe_float(t.get("profit")))

    out: Dict[str, Any] = {}
    for market, pnls in by_market.items():
        n = len(pnls)
        if n < min_trades:
            continue
        wins = sum(1 for p in pnls if p > 0)
        win_rate = wins / n
        expectancy = statistics.mean(pnls)

        # Map expectancy to a multiplier centred on 1.0.
        # Linear: expectancy_normal EUR/trade → 1.0; 0 EUR → 0.85; -expectancy_normal → 0.70.
        # Above expectancy_normal, scale into [1.0 .. ceil].
        if expectancy >= 0:
            mult = 1.0 + (expectancy / expectancy_normal) * (multiplier_ceil - 1.0) * 0.5
        else:
            mult = 1.0 + (expectancy / expectancy_normal) * (1.0 - multiplier_floor) * 0.5
        mult = max(multiplier_floor, min(multiplier_ceil, round(mult, 3)))

        override: Optional[float] = None
        if expectancy <= strong_bad_expectancy:
            override = float(strong_bad_override)

        out[market] = {
            "score_multiplier": mult,
            "min_score_override": override,
            "n": n,
            "wr": round(win_rate, 4),
            "expectancy_eur": round(expectancy, 4),
        }
    return out


def build(
    trades_path: Path = ARCHIVE,
    out_path: Path = WEIGHTS_PATH,
    *,
    max_markets: int = DEFAULTS["MAX_MARKETS"],
) -> Dict[str, Any]:
    """Compute profiles, write JSON atomically, return the document."""
    trades = _load_trades(trades_path)
    profiles = compute_profiles(trades)

    # Cap to top N by trade count to keep the file small
    if len(profiles) > max_markets:
        ranked = sorted(profiles.items(), key=lambda kv: kv[1]["n"], reverse=True)[:max_markets]
        profiles = dict(ranked)

    doc = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_trades_total": len(trades),
        "n_markets": len(profiles),
        "default": {"score_multiplier": 1.0, "min_score_override": None},
        "markets": profiles,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    tmp.replace(out_path)
    return doc


# ---------- Public loader for runtime consumption ----------

def load_signal_weights(path: Path = WEIGHTS_PATH) -> Dict[str, Any]:
    """Return the parsed weights document, or an empty default if missing."""
    if not path.exists():
        return {"default": {"score_multiplier": 1.0, "min_score_override": None}, "markets": {}}
    try:
        with path.open("r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {"default": {"score_multiplier": 1.0, "min_score_override": None}, "markets": {}}


def market_profile(weights: Mapping[str, Any], market: str) -> Tuple[float, Optional[float]]:
    """Resolve ``(score_multiplier, min_score_override)`` for a market."""
    markets = weights.get("markets") or {}
    default = weights.get("default") or {}
    entry = markets.get(market) or default
    mult = float(entry.get("score_multiplier", 1.0))
    override = entry.get("min_score_override")
    if override is not None:
        try:
            override = float(override)
        except (TypeError, ValueError):
            override = None
    return mult, override


# ---------- CLI ----------

def _main() -> int:
    ap = argparse.ArgumentParser(description="Build per-market signal score profiles")
    ap.add_argument("--archive", default=str(ARCHIVE))
    ap.add_argument("--out", default=str(WEIGHTS_PATH))
    ap.add_argument("--top", type=int, default=20, help="print top N markets")
    args = ap.parse_args()

    doc = build(Path(args.archive), Path(args.out))
    print(f"wrote: {args.out}")
    print(f"trades scanned: {doc['n_trades_total']}, markets profiled: {doc['n_markets']}")

    rows = [(m, p["n"], p["wr"], p["expectancy_eur"], p["score_multiplier"], p["min_score_override"])
            for m, p in doc["markets"].items()]
    rows.sort(key=lambda r: r[3], reverse=True)
    print()
    print(f"{'market':<14} {'n':>4} {'wr':>6} {'exp':>8} {'mult':>6} override")
    for r in rows[:args.top]:
        ov = "-" if r[5] is None else f"{r[5]:.0f}"
        print(f"{r[0]:<14} {r[1]:>4d} {r[2]*100:>5.0f}% €{r[3]:>+6.2f} {r[4]:>6.2f} {ov:>5}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
