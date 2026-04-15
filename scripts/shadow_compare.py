"""Shadow Mode Comparison — analyze shadow vs actual trading after N days.

Usage:
    python _shadow_compare.py          # default: last 7 days
    python _shadow_compare.py --days 3 # last 3 days
"""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
LOG_PATH = DATA / "shadow_log.jsonl"
PHANTOM_PATH = DATA / "shadow_phantom.json"
DMS_PATH = DATA / "shadow_dms_watchlist.json"
TRADE_LOG = DATA / "trade_log.json"
ARCHIVE = DATA / "trade_archive.json"

# Simulated investment per phantom trade (same as bot's BASE_AMOUNT_EUR)
PHANTOM_INVEST_EUR = 150.0


def load_shadow_log(cutoff_ts: float) -> list:
    """Load shadow log entries since cutoff."""
    entries = []
    if not LOG_PATH.exists():
        return entries
    with open(str(LOG_PATH), "r", encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line.strip())
                if e.get("ts", 0) >= cutoff_ts:
                    entries.append(e)
            except Exception:
                pass
    return entries


def load_phantoms() -> dict:
    """Load phantom trades."""
    if not PHANTOM_PATH.exists():
        return {}
    try:
        with open(str(PHANTOM_PATH), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_closed_trades(cutoff_ts: float) -> list:
    """Load real closed trades since cutoff from archive + trade_log."""
    trades = []
    for path in [ARCHIVE, TRADE_LOG]:
        try:
            if not path.exists():
                continue
            with open(str(path), "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    trades.extend(data)
                elif isinstance(data, dict):
                    trades.extend(data.values())
        except Exception:
            pass
    return [t for t in trades if float(t.get("timestamp") or t.get("opened_ts") or 0) >= cutoff_ts]


def format_eur(val: float) -> str:
    sign = "+" if val >= 0 else ""
    return f"{sign}€{val:.2f}"


def analyze(days: int = 7):
    cutoff = time.time() - days * 86400
    entries = load_shadow_log(cutoff)
    phantoms = load_phantoms()
    closed = load_closed_trades(cutoff)

    print("=" * 70)
    print(f"  SHADOW MODE ANALYSE — Laatste {days} dagen")
    print("=" * 70)

    if not entries:
        print("\n  Geen shadow data gevonden.")
        print("  Zorg dat SHADOW_MODE_ENABLED=true in config staat en de bot draait.")
        return

    # ── Period info ──
    first_ts = min(e.get("ts", 0) for e in entries)
    last_ts = max(e.get("ts", 0) for e in entries)
    period_days = (last_ts - first_ts) / 86400
    print(f"\n  Periode: {time.strftime('%Y-%m-%d %H:%M', time.localtime(first_ts))}"
          f" → {time.strftime('%Y-%m-%d %H:%M', time.localtime(last_ts))}"
          f" ({period_days:.1f} dagen)")
    print(f"  Evaluaties gelogd: {len(entries):,}")

    # Separate decision entries from "avoided" entries
    decisions = [e for e in entries if e.get("type") != "avoided"]
    avoided_entries = [e for e in entries if e.get("type") == "avoided"]

    # ══════════════════════════════════════════════════════════════
    # 1. TIMING FILTER IMPACT
    # ══════════════════════════════════════════════════════════════
    print("\n" + "─" * 70)
    print("  ⏰ TIMING FILTER (13:00-17:00 UTC blokkade)")
    print("─" * 70)

    timing_avoided = [e for e in avoided_entries if e.get("block_reason") == "block_timing"]

    if timing_avoided:
        # Match with actual trade outcomes
        closed_by_market_ts = {}
        for t in closed:
            m = t.get("market", "")
            ts = float(t.get("opened_ts") or t.get("timestamp") or 0)
            profit = float(t.get("profit") or 0)
            closed_by_market_ts.setdefault(m, []).append((ts, profit))

        matched_pnl = 0.0
        matched_count = 0
        unmatched = 0

        print(f"\n  Trades die bot nam maar shadow zou blokkeren: {len(timing_avoided)}")
        for av in timing_avoided[:15]:  # show first 15
            m = av["market"]
            av_ts = av["ts"]
            # Find matching closed trade (within 5 min)
            best_match = None
            if m in closed_by_market_ts:
                for t_ts, t_profit in closed_by_market_ts[m]:
                    if abs(t_ts - av_ts) < 300:
                        best_match = t_profit
                        break
            if best_match is not None:
                matched_pnl += best_match
                matched_count += 1
                status = format_eur(best_match)
            else:
                unmatched += 1
                status = "(nog open of niet gematched)"

            ts_str = time.strftime("%m-%d %H:%M", time.localtime(av_ts))
            print(f"    {m:<16} {ts_str}  score {av.get('score', 0):.1f}"
                  f" → shadow blokt (adj {av.get('adj_score', 0):.1f})  "
                  f"werkelijk: {status}")

        if len(timing_avoided) > 15:
            print(f"    ... en {len(timing_avoided) - 15} meer")

        print(f"\n  Gematchte trades: {matched_count}, totaal P&L: {format_eur(matched_pnl)}")
        if matched_pnl < 0:
            print(f"  → Timing filter zou {format_eur(abs(matched_pnl))} verlies VOORKOMEN hebben!")
        elif matched_pnl > 0:
            print(f"  → Timing filter zou {format_eur(matched_pnl)} winst GEMIST hebben.")
        if unmatched:
            print(f"  Niet-gematchte entries: {unmatched} (nog open of timing verschil)")
    else:
        print("\n  Geen trades geblokkeerd door timing filter (of geen trades in 13:00-17:00).")

    # ══════════════════════════════════════════════════════════════
    # 2. VELOCITY FILTER IMPACT
    # ══════════════════════════════════════════════════════════════
    print("\n" + "─" * 70)
    print("  📉 VELOCITY FILTER (30-dagen rolling P&L)")
    print("─" * 70)

    velocity_avoided = [e for e in avoided_entries if e.get("block_reason") == "block_velocity"]

    if velocity_avoided:
        closed_by_market_ts = {}
        for t in closed:
            m = t.get("market", "")
            ts = float(t.get("opened_ts") or t.get("timestamp") or 0)
            profit = float(t.get("profit") or 0)
            closed_by_market_ts.setdefault(m, []).append((ts, profit))

        matched_pnl = 0.0
        matched_count = 0

        print(f"\n  Trades die bot nam maar shadow zou blokkeren: {len(velocity_avoided)}")
        for av in velocity_avoided[:15]:
            m = av["market"]
            av_ts = av["ts"]
            best_match = None
            if m in closed_by_market_ts:
                for t_ts, t_profit in closed_by_market_ts[m]:
                    if abs(t_ts - av_ts) < 300:
                        best_match = t_profit
                        break
            if best_match is not None:
                matched_pnl += best_match
                matched_count += 1
                status = format_eur(best_match)
            else:
                status = "(nog open)"

            ts_str = time.strftime("%m-%d %H:%M", time.localtime(av_ts))
            print(f"    {m:<16} {ts_str}  score {av.get('score', 0):.1f}"
                  f" → velocity block  werkelijk: {status}")

        if len(velocity_avoided) > 15:
            print(f"    ... en {len(velocity_avoided) - 15} meer")

        print(f"\n  Gematchte trades: {matched_count}, totaal P&L: {format_eur(matched_pnl)}")
        if matched_pnl < 0:
            print(f"  → Velocity filter zou {format_eur(abs(matched_pnl))} verlies VOORKOMEN hebben!")
    else:
        print("\n  Geen trades geblokkeerd door velocity filter.")

    # ══════════════════════════════════════════════════════════════
    # 3. DMS — DYNAMIC MARKET SCANNER
    # ══════════════════════════════════════════════════════════════
    print("\n" + "─" * 70)
    print("  🔍 DMS — Dynamic Market Scanner (nieuwe markten)")
    print("─" * 70)

    dms_decisions = [d for d in decisions if d.get("dms")]
    dms_buys = [d for d in dms_decisions if d.get("shadow") == "buy"]

    print(f"\n  DMS markten gescand: {len(set(d['market'] for d in dms_decisions if 'market' in d))}")
    print(f"  DMS evaluaties: {len(dms_decisions)}")
    print(f"  DMS phantom buys (shadow zou kopen): {len(dms_buys)}")

    if dms_buys:
        print("\n  Phantom buy signalen:")
        markets_seen = set()
        for d in dms_buys:
            m = d.get("market", "?")
            if m in markets_seen:
                continue
            markets_seen.add(m)
            ts_str = time.strftime("%m-%d %H:%M", time.localtime(d.get("ts", 0)))
            print(f"    {m:<16} {ts_str}  score {d.get('adj_score', 0):.1f}"
                  f"  prijs €{d.get('price', 0):.4f}")

    # Phantom trade results
    open_ph = {k: v for k, v in phantoms.items() if v.get("status") == "open"}
    closed_ph = {k: v for k, v in phantoms.items() if v.get("status", "").startswith("closed")}

    if open_ph or closed_ph:
        print(f"\n  Phantom trades actief: {len(open_ph)}")
        for m, pt in sorted(open_ph.items(), key=lambda x: x[1].get("phantom_pnl_pct", 0), reverse=True):
            pnl_pct = pt.get("phantom_pnl_pct", 0)
            pnl_eur = PHANTOM_INVEST_EUR * pnl_pct / 100
            hold_h = (time.time() - pt.get("entry_ts", time.time())) / 3600
            print(f"    {m:<16} entry €{pt['entry_price']:.4f}  "
                  f"nu €{pt.get('current_price', 0):.4f}  "
                  f"P&L {pnl_pct:+.1f}% ({format_eur(pnl_eur)})  "
                  f"hold {hold_h:.0f}h")

        if closed_ph:
            print(f"\n  Phantom trades gesloten: {len(closed_ph)}")
            total_phantom_pnl_eur = 0.0
            for m, pt in sorted(closed_ph.items(), key=lambda x: x[1].get("final_pnl_pct", 0), reverse=True):
                pnl_pct = pt.get("final_pnl_pct", 0)
                pnl_eur = PHANTOM_INVEST_EUR * pnl_pct / 100
                total_phantom_pnl_eur += pnl_eur
                reason = pt.get("status", "closed").replace("closed_", "")
                print(f"    {m:<16} {pnl_pct:+.1f}% ({format_eur(pnl_eur)})  exit: {reason}")

            print(f"\n  Totaal DMS phantom P&L: {format_eur(total_phantom_pnl_eur)}")
    else:
        print("\n  Nog geen phantom trades geopend (DMS markten moeten score >= threshold halen).")

    # DMS watchlist current
    if DMS_PATH.exists():
        try:
            with open(str(DMS_PATH), "r", encoding="utf-8") as f:
                dms_data = json.load(f)
            wl = dms_data.get("markets", [])
            if wl:
                print(f"\n  Huidige DMS watchlist (top 10 van {len(wl)}):")
                for d in wl[:10]:
                    print(f"    {d['market']:<16} opp={d['opportunity']:.0f}"
                          f"  vol=€{d['volume_eur']:,.0f}"
                          f"  volatility={d['volatility_pct']:.1f}%")
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════
    # 4. COMBINED IMPACT SUMMARY
    # ══════════════════════════════════════════════════════════════
    print("\n" + "═" * 70)
    print("  📊 GECOMBINEERD SCHATTING")
    print("═" * 70)

    # Actual bot P&L
    actual_pnl = sum(float(t.get("profit") or 0) for t in closed)
    actual_count = len(closed)
    actual_per_week = actual_pnl / max(period_days / 7, 0.01)

    # Timing savings
    timing_savings = 0.0
    for av in timing_avoided:
        m = av["market"]
        av_ts = av["ts"]
        for t in closed:
            if t.get("market") == m:
                t_ts = float(t.get("opened_ts") or t.get("timestamp") or 0)
                if abs(t_ts - av_ts) < 300:
                    p = float(t.get("profit") or 0)
                    if p < 0:
                        timing_savings += abs(p)
                    else:
                        timing_savings -= p  # missed profit
                    break

    # Velocity savings
    velocity_savings = 0.0
    for av in velocity_avoided:
        m = av["market"]
        av_ts = av["ts"]
        for t in closed:
            if t.get("market") == m:
                t_ts = float(t.get("opened_ts") or t.get("timestamp") or 0)
                if abs(t_ts - av_ts) < 300:
                    p = float(t.get("profit") or 0)
                    if p < 0:
                        velocity_savings += abs(p)
                    else:
                        velocity_savings -= p
                    break

    # DMS phantom P&L
    dms_pnl = 0.0
    for pt in phantoms.values():
        pnl_pct = pt.get("final_pnl_pct") or pt.get("phantom_pnl_pct", 0)
        dms_pnl += PHANTOM_INVEST_EUR * pnl_pct / 100

    shadow_pnl = actual_pnl + timing_savings + velocity_savings + dms_pnl
    shadow_per_week = shadow_pnl / max(period_days / 7, 0.01)

    print(f"\n  Bot werkelijk P&L:         {format_eur(actual_pnl)} ({actual_count} trades)")
    print(f"  Timing filter impact:      {format_eur(timing_savings)}")
    print(f"  Velocity filter impact:    {format_eur(velocity_savings)}")
    print(f"  DMS phantom P&L:           {format_eur(dms_pnl)}")
    print(f"  ─────────────────────────────────────")
    print(f"  Shadow geschatte P&L:      {format_eur(shadow_pnl)}")
    print(f"\n  Per week:")
    print(f"    Bot werkelijk:  {format_eur(actual_per_week)}/week")
    print(f"    Shadow schat:   {format_eur(shadow_per_week)}/week")
    improvement = shadow_per_week - actual_per_week
    print(f"    Verschil:       {format_eur(improvement)}/week")

    print(f"\n  ⚠️  Let op: shadow P&L is theoretisch.")
    print(f"      DMS phantom trades gebruiken vereenvoudigde trailing stops.")
    print(f"      Timing/velocity vermeden trades: alleen gesloten trades meegeteld.")

    # ── Hourly breakdown ──
    print("\n" + "─" * 70)
    print("  📈 EVALUATIES PER UUR (UTC)")
    print("─" * 70)

    hourly_buys = defaultdict(int)
    hourly_blocks = defaultdict(int)
    for d in decisions:
        hour = int(time.strftime("%H", time.gmtime(d.get("ts", 0))))
        if d.get("bot") == "buy":
            hourly_buys[hour] += 1
        if d.get("shadow") in ("block_timing", "block_velocity"):
            hourly_blocks[hour] += 1

    print(f"\n  {'Uur':>4}  {'Bot buys':>10}  {'Shadow blocks':>14}")
    for h in range(24):
        b = hourly_buys.get(h, 0)
        bl = hourly_blocks.get(h, 0)
        bar_b = "█" * min(b, 30)
        bar_bl = "▒" * min(bl, 30)
        if b or bl:
            print(f"  {h:02d}:00  {b:>10}  {bl:>14}  {bar_b}{bar_bl}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Shadow Mode Comparison")
    parser.add_argument("--days", type=int, default=7, help="Days to analyze (default: 7)")
    args = parser.parse_args()
    analyze(args.days)
