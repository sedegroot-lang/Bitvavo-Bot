"""Cold-Tier Market Scanner — discover new candidates for the warm tier (WATCHLIST_MARKETS).

The bot scans only WHITELIST_MARKETS every 25s (hot tier, ~18 markets) and
WATCHLIST_MARKETS in micro mode (warm tier). This leaves ~370 EUR markets on
Bitvavo never looked at. This script periodically (cron-friendly) scans ALL
EUR markets via cheap public ticker24h calls (no candles, no orderbook), ranks
candidates on a simple heuristic, and proposes the top-N for warm-tier addition.

Heuristic (per candidate, must NOT be on whitelist/watchlist/blacklist):
  base_score = log10(volume_24h_eur)            # liquidity tier
  + |price_change_24h_pct| / 5                  # momentum (any direction)
  - max(0, |price_change_24h_pct| - 25) / 5     # penalty for extreme dumps (>25%)
  - 5 if volume_24h_eur < MIN_VOLUME_EUR        # hard liquidity floor

Writes proposals to:
  - dry-run (default): print + tmp/cold_tier_proposals.json
  - --apply           : append top-N to WATCHLIST_MARKETS in local config
                        (max additions per run = MAX_PROMOTE_PER_RUN, default 2)

Cron suggestion: hourly. Bitvavo cost: 1× markets() + 1× ticker24h({}) per run.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

_THIS = Path(__file__).resolve()
_ROOT = _THIS.parent.parent
sys.path.insert(0, str(_ROOT))

LOCAL_CONFIG = Path(os.environ.get("LOCALAPPDATA", "")) / "BotConfig" / "bot_config_local.json"
ONEDRIVE_BASE = _ROOT / "config" / "bot_config.json"
ONEDRIVE_OVERRIDES = _ROOT / "config" / "bot_config_overrides.json"
PROPOSALS_PATH = _ROOT / "tmp" / "cold_tier_proposals.json"

# Defaults (overridable by config or CLI)
MIN_VOLUME_EUR = 750_000        # liquidity floor
MAX_PROMOTE_PER_RUN = 2         # conservative: max 2 new warm-tier markets per cron run
TOP_N = 10                      # how many candidates to display
EXTREME_DUMP_PCT = 25.0         # downside considered "knife"
EXTREME_PUMP_PCT = 50.0         # upside considered "FOMO trap"


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as e:
        print(f"WARN: failed reading {path.name}: {e}")
    return default if default is not None else {}


def _gather_excluded() -> Tuple[Set[str], Dict[str, str]]:
    """Build the set of markets to EXCLUDE from cold-tier proposals.

    Returns (excluded_set, source_map) where source_map[market] explains why.
    """
    excluded: Set[str] = set()
    source: Dict[str, str] = {}
    for label, p in [("local", LOCAL_CONFIG), ("base", ONEDRIVE_BASE), ("overrides", ONEDRIVE_OVERRIDES)]:
        cfg = _read_json(p)
        if not isinstance(cfg, dict):
            continue
        for key in ("WHITELIST_MARKETS", "WATCHLIST_MARKETS", "KILL_ZONE_MARKETS",
                    "EXCLUDED_MARKETS", "BLACKLIST_MARKETS", "HODL_MARKETS"):
            for m in (cfg.get(key) or []):
                m_up = str(m).upper()
                if m_up not in source:
                    source[m_up] = f"{label}.{key}"
                excluded.add(m_up)
    return excluded, source


def fetch_eur_markets_with_volume() -> List[Dict[str, Any]]:
    """Public Bitvavo call — returns list of {market, volume_eur, change_24h_pct, price}."""
    try:
        from python_bitvavo_api.bitvavo import Bitvavo
    except ImportError:
        print("ERROR: python_bitvavo_api not installed")
        return []
    bv = Bitvavo({})  # no auth needed for public ticker24h
    try:
        all_tickers = bv.ticker24h({})
    except Exception as e:
        print(f"ERROR: ticker24h failed: {e}")
        return []
    out: List[Dict[str, Any]] = []
    for t in all_tickers or []:
        m = (t.get("market") or "").upper()
        if not m.endswith("-EUR"):
            continue
        try:
            last = float(t.get("last") or 0)
            vol_base = float(t.get("volume") or 0)  # base-currency volume
            vol_eur = last * vol_base if last and vol_base else 0
            open_p = float(t.get("open") or last or 0)
            change_pct = ((last - open_p) / open_p * 100.0) if open_p > 0 else 0.0
        except (TypeError, ValueError):
            continue
        if last <= 0 or vol_eur <= 0:
            continue
        out.append({
            "market": m,
            "price": last,
            "volume_eur": vol_eur,
            "change_24h_pct": change_pct,
        })
    return out


def score_candidate(c: Dict[str, Any]) -> float:
    vol = max(1.0, float(c["volume_eur"]))
    change = float(c["change_24h_pct"])
    abs_ch = abs(change)
    base = math.log10(vol)                       # 6 = €1M, 7 = €10M
    momentum = abs_ch / 5.0                      # 5% move = +1 point
    knife_pen = max(0.0, abs_ch - EXTREME_DUMP_PCT) / 5.0
    fomo_pen = max(0.0, abs_ch - EXTREME_PUMP_PCT) / 5.0
    liq_pen = 5.0 if vol < MIN_VOLUME_EUR else 0.0
    return round(base + momentum - knife_pen - fomo_pen - liq_pen, 3)


def rank_candidates(tickers: List[Dict[str, Any]], excluded: Set[str]) -> List[Dict[str, Any]]:
    out = []
    for t in tickers:
        if t["market"] in excluded:
            continue
        if t["volume_eur"] < MIN_VOLUME_EUR:
            continue
        t = dict(t)
        t["score"] = score_candidate(t)
        out.append(t)
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


def write_proposals(ranked: List[Dict[str, Any]]) -> None:
    PROPOSALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": __import__("time").time(),
        "candidates": ranked[:TOP_N],
    }
    PROPOSALS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def apply_top_n(ranked: List[Dict[str, Any]], n: int) -> List[str]:
    """Append top-N markets to WATCHLIST_MARKETS in LOCAL config only. Returns added list."""
    if not LOCAL_CONFIG.exists():
        print(f"ERROR: local config not found at {LOCAL_CONFIG}")
        return []
    cfg = _read_json(LOCAL_CONFIG, {})
    wl = list(cfg.get("WATCHLIST_MARKETS") or [])
    wl_upper = {str(x).upper() for x in wl}
    added: List[str] = []
    for c in ranked:
        if len(added) >= n:
            break
        m = c["market"]
        if m not in wl_upper:
            wl.append(m)
            wl_upper.add(m)
            added.append(m)
    if not added:
        print("\nNo new markets added (top candidates already on watchlist).")
        return []
    cfg["WATCHLIST_MARKETS"] = wl
    tmp = LOCAL_CONFIG.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    os.replace(tmp, LOCAL_CONFIG)
    print(f"\nApplied {len(added)} additions to LOCAL WATCHLIST_MARKETS:")
    for m in added:
        print(f"  + {m}")
    return added


def print_ranked(ranked: List[Dict[str, Any]], excluded_count: int) -> None:
    print(f"\n{'='*80}")
    print(f"COLD-TIER PROPOSALS  (excluded: {excluded_count}, candidates: {len(ranked)})")
    print(f"{'='*80}")
    print(f"{'Rank':<5}{'Market':<14}{'Score':>7}  {'Vol€':>11}  {'24h%':>7}  Price")
    print(f"{'-'*80}")
    for i, c in enumerate(ranked[:TOP_N], 1):
        print(f"{i:<5}{c['market']:<14}{c['score']:>7.2f}  "
              f"{c['volume_eur']:>11,.0f}  {c['change_24h_pct']:>+6.1f}%  {c['price']:.5f}")
    if not ranked:
        print("  (no candidates passed filters)")


def main() -> None:
    global MIN_VOLUME_EUR
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Add top-N to LOCAL WATCHLIST_MARKETS")
    ap.add_argument("--n", type=int, default=MAX_PROMOTE_PER_RUN, help="Max promotions per run")
    ap.add_argument("--min-volume", type=float, default=MIN_VOLUME_EUR, help="Min 24h volume EUR")
    args = ap.parse_args()

    MIN_VOLUME_EUR = args.min_volume
    print("Cold-Tier Market Scanner")
    print(f"  min_volume_eur:    EUR{int(MIN_VOLUME_EUR):,}")
    print(f"  max_promote/run:   {args.n}")

    excluded, _src = _gather_excluded()
    print(f"  excluded markets:  {len(excluded)}")

    tickers = fetch_eur_markets_with_volume()
    print(f"  EUR markets fetched: {len(tickers)}")
    if not tickers:
        return

    ranked = rank_candidates(tickers, excluded)
    print_ranked(ranked, len(excluded))
    write_proposals(ranked)
    print(f"\nProposals saved to {PROPOSALS_PATH.name}")

    if args.apply:
        apply_top_n(ranked, args.n)


if __name__ == "__main__":
    main()
