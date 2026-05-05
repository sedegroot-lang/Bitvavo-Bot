"""Auto-Blacklist Learner — periodically scan trade archive, suggest blacklist/whitelist updates.

Reads `data/trade_archive.json`, computes per-market rolling 60-day stats,
and suggests:
  - Markets to ADD to KILL_ZONE_MARKETS  (Wilson lower bound win-rate <40% AND n>=10)
  - Markets to ADD to KILL_ZONE_WHITELIST (Wilson lower bound >=70% AND n>=15 AND profitable)
  - Markets to REMOVE from blacklist (recovered: Wilson >=55%)

Output modes:
  --dry-run (default): print suggestions, no changes
  --apply           : write updates to %LOCALAPPDATA%/BotConfig/bot_config_local.json
  --notify          : send Telegram notification of changes (if configured)

Designed to run as a daily cron / Windows scheduled task.
Conservative by default — only adds, never removes whitelist entries automatically.
"""
from __future__ import annotations
import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Tuple

# Ensure project root on path
_THIS = Path(__file__).resolve()
_ROOT = _THIS.parent.parent
sys.path.insert(0, str(_ROOT))

ARCHIVE = _ROOT / "data" / "trade_archive.json"
LOCAL_CONFIG = Path(os.environ.get("LOCALAPPDATA", "")) / "BotConfig" / "bot_config_local.json"

ROLLING_DAYS = 60
MIN_N_BLACKLIST = 10
MIN_N_WHITELIST = 15
WILSON_BLACKLIST_MAX = 0.40
WILSON_WHITELIST_MIN = 0.70
WILSON_RECOVERY_MIN = 0.55  # to remove from blacklist

# Markets that should NEVER be auto-removed from blacklist (manual override)
PROTECTED_BLACKLIST = {"USDC-EUR"}


def wilson_lower(p: float, n: int, z: float = 1.96) -> float:
    if n == 0:
        return 0.0
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return (centre - margin) / denom


def load_recent_trades(days: int = ROLLING_DAYS):
    if not ARCHIVE.exists():
        print(f"ERROR: {ARCHIVE} not found")
        return []
    data = json.loads(ARCHIVE.read_text(encoding="utf-8"))
    trades = data.get("trades") if isinstance(data, dict) else data
    import time
    cutoff = time.time() - days * 86400
    out = []
    for t in trades or []:
        ts = t.get("timestamp")
        if not isinstance(ts, (int, float)) or ts < cutoff:
            continue
        out.append(t)
    return out


def analyze(trades) -> dict:
    """Return per-market stats."""
    by_mkt: dict[str, dict] = {}
    for t in trades:
        m = t.get("market")
        p = t.get("profit")
        if not m or p is None:
            continue
        try:
            p = float(p)
        except (TypeError, ValueError):
            continue
        d = by_mkt.setdefault(m, {"n": 0, "wins": 0, "pnl": 0.0})
        d["n"] += 1
        if p > 0:
            d["wins"] += 1
        d["pnl"] += p
    for m, d in by_mkt.items():
        d["win_rate"] = d["wins"] / d["n"] if d["n"] > 0 else 0.0
        d["wilson"] = wilson_lower(d["win_rate"], d["n"])
        d["avg_pnl"] = d["pnl"] / d["n"] if d["n"] > 0 else 0.0
    return by_mkt


def suggest(stats: dict, current_blacklist: set, current_whitelist: set) -> Tuple[list, list, list]:
    add_blacklist = []
    add_whitelist = []
    remove_blacklist = []
    for m, s in stats.items():
        if s["n"] < MIN_N_BLACKLIST:
            continue
        # Suggest blacklist add
        if (s["wilson"] < WILSON_BLACKLIST_MAX or s["avg_pnl"] < -0.5) and m not in current_blacklist:
            add_blacklist.append((m, s))
        # Suggest whitelist add
        if (s["n"] >= MIN_N_WHITELIST and s["wilson"] >= WILSON_WHITELIST_MIN
                and s["avg_pnl"] > 0 and m not in current_whitelist):
            add_whitelist.append((m, s))
        # Suggest blacklist removal (recovered)
        if (m in current_blacklist and m not in PROTECTED_BLACKLIST
                and s["wilson"] >= WILSON_RECOVERY_MIN and s["avg_pnl"] > 0):
            remove_blacklist.append((m, s))
    return add_blacklist, add_whitelist, remove_blacklist


def print_suggestions(add_b, add_w, rm_b):
    if add_b:
        print("\n>>> ADD TO BLACKLIST:")
        for m, s in add_b:
            print(f"   - {m:<14s}  n={s['n']:>3d}  wilson={s['wilson']*100:>5.1f}%  "
                  f"wr={s['win_rate']*100:>5.1f}%  avg_pnl={s['avg_pnl']:+.2f}EUR")
    if add_w:
        print("\n>>> ADD TO WHITELIST:")
        for m, s in add_w:
            print(f"   - {m:<14s}  n={s['n']:>3d}  wilson={s['wilson']*100:>5.1f}%  "
                  f"wr={s['win_rate']*100:>5.1f}%  avg_pnl={s['avg_pnl']:+.2f}EUR")
    if rm_b:
        print("\n>>> REMOVE FROM BLACKLIST (recovered):")
        for m, s in rm_b:
            print(f"   - {m:<14s}  n={s['n']:>3d}  wilson={s['wilson']*100:>5.1f}%  "
                  f"avg_pnl={s['avg_pnl']:+.2f}EUR")
    if not (add_b or add_w or rm_b):
        print("\n  No changes suggested. Current lists look optimal.")


def apply_changes(add_b, add_w, rm_b) -> bool:
    if not LOCAL_CONFIG.exists():
        print(f"ERROR: local config not found at {LOCAL_CONFIG}")
        return False
    cfg = json.loads(LOCAL_CONFIG.read_text(encoding="utf-8-sig"))
    bl = list(cfg.get("KILL_ZONE_MARKETS", []))
    wl = list(cfg.get("KILL_ZONE_WHITELIST", []))
    changed = False
    for m, _ in add_b:
        if m not in bl:
            bl.append(m)
            changed = True
    for m, _ in add_w:
        if m not in wl:
            wl.append(m)
            changed = True
    for m, _ in rm_b:
        if m in bl:
            bl.remove(m)
            changed = True
    if not changed:
        print("\nNo config changes needed.")
        return False
    cfg["KILL_ZONE_MARKETS"] = bl
    cfg["KILL_ZONE_WHITELIST"] = wl
    # Atomic write
    tmp = LOCAL_CONFIG.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    os.replace(tmp, LOCAL_CONFIG)
    print(f"\nApplied changes to {LOCAL_CONFIG}")
    print(f"  KILL_ZONE_MARKETS:   {bl}")
    print(f"  KILL_ZONE_WHITELIST: {wl}")
    return True


def maybe_notify(add_b, add_w, rm_b) -> None:
    try:
        import notifier  # type: ignore
    except Exception:
        return
    if not (add_b or add_w or rm_b):
        return
    msg_parts = ["[Auto-Blacklist Learner]"]
    if add_b:
        msg_parts.append("➕ Blacklist: " + ", ".join(m for m, _ in add_b))
    if add_w:
        msg_parts.append("⭐ Whitelist: " + ", ".join(m for m, _ in add_w))
    if rm_b:
        msg_parts.append("➖ Removed (recovered): " + ", ".join(m for m, _ in rm_b))
    try:
        notifier.send_telegram("\n".join(msg_parts))
    except Exception as e:
        print(f"Notify failed: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Apply suggestions to local config")
    ap.add_argument("--notify", action="store_true", help="Send Telegram notification")
    ap.add_argument("--days", type=int, default=ROLLING_DAYS, help="Lookback window")
    args = ap.parse_args()

    trades = load_recent_trades(args.days)
    print(f"Auto-Blacklist Learner — {len(trades)} trades in last {args.days}d")
    if not trades:
        return
    stats = analyze(trades)
    print(f"Markets analyzed: {len(stats)}")

    # Read current config
    current_bl: set = set()
    current_wl: set = set()
    if LOCAL_CONFIG.exists():
        cfg = json.loads(LOCAL_CONFIG.read_text(encoding="utf-8-sig"))
        current_bl = {str(m).upper() for m in (cfg.get("KILL_ZONE_MARKETS") or [])}
        current_wl = {str(m).upper() for m in (cfg.get("KILL_ZONE_WHITELIST") or [])}

    add_b, add_w, rm_b = suggest(stats, current_bl, current_wl)
    print_suggestions(add_b, add_w, rm_b)

    if args.apply:
        if apply_changes(add_b, add_w, rm_b) and args.notify:
            maybe_notify(add_b, add_w, rm_b)
    elif args.notify:
        maybe_notify(add_b, add_w, rm_b)


if __name__ == "__main__":
    main()
