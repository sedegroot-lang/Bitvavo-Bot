#!/usr/bin/env python3
"""Quick PnL analyzer for data/trade_pnl_history.jsonl.

Computes profit factor (PF), win rate, and basic aggregates overall, per-market,
and (optionally) per score bucket when a `score` field is present in the records.

Usage:
  python tools/analyze_pnl_history.py --file data/trade_pnl_history.jsonl --score-bucket 1
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Tuple

Record = Dict[str, object]


def _fmt_pct(value: float) -> str:
    return f"{value*100:.1f}%" if math.isfinite(value) else "n/a"


def _profit_factor(pnls: List[float]) -> float:
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    if not losses:
        return float("inf") if wins else 0.0
    return abs(sum(wins)) / abs(sum(losses)) if sum(losses) != 0 else float("inf")


def _summary(records: List[Record]) -> Dict[str, float]:
    pnls = [float(r.get("profit_eur", 0) or 0) for r in records]
    pct = [float(r.get("profit_pct", 0) or 0) for r in records if r.get("profit_pct") is not None]
    holds = [float(r.get("hold_seconds", 0) or 0) for r in records if r.get("hold_seconds") is not None]
    trades = len(pnls)
    wins = sum(1 for p in pnls if p > 0)
    pf = _profit_factor(pnls) if pnls else 0.0
    avg_pnl = statistics.mean(pnls) if pnls else 0.0
    avg_pct = statistics.mean(pct) if pct else 0.0
    med_hold = statistics.median(holds) if holds else 0.0
    return {
        "trades": trades,
        "win_rate": wins / trades if trades else 0.0,
        "profit_factor": pf,
        "total_pnl": sum(pnls),
        "avg_pnl": avg_pnl,
        "avg_profit_pct": avg_pct,
        "median_hold_s": med_hold,
    }


def _group(records: Iterable[Record], key_fn: Callable[[Record], str | None]) -> Dict[str, List[Record]]:
    groups: Dict[str, List[Record]] = defaultdict(list)
    for rec in records:
        k = key_fn(rec)
        if k is None:
            continue
        groups[k].append(rec)
    return groups


def _print_section(title: str, summary: Dict[str, float]) -> None:
    print(f"\n== {title} ==")
    print(
        f"trades={summary['trades']} | win_rate={_fmt_pct(summary['win_rate'])} | "
        f"PF={summary['profit_factor']:.2f} | total_pnl={summary['total_pnl']:.2f} EUR | "
        f"avg_pnl={summary['avg_pnl']:.2f} EUR | avg_pct={_fmt_pct(summary['avg_profit_pct']/100)} | "
        f"median_hold={summary['median_hold_s']:.0f}s"
    )


def _print_top_groups(title: str, grouped: Dict[str, List[Record]], limit: int = 10) -> None:
    ranked: List[Tuple[str, Dict[str, float]]] = []
    for key, recs in grouped.items():
        ranked.append((key, _summary(recs)))
    ranked.sort(key=lambda kv: kv[1]["trades"], reverse=True)
    print(f"\n== {title} (top {min(limit, len(ranked))}) ==")
    for key, stats in ranked[:limit]:
        print(
            f"{key}: trades={stats['trades']}, win_rate={_fmt_pct(stats['win_rate'])}, PF={stats['profit_factor']:.2f}, "
            f"avg_pnl={stats['avg_pnl']:.2f} EUR, total_pnl={stats['total_pnl']:.2f} EUR"
        )


def load_records(path: Path, limit: int | None = None) -> List[Record]:
    if not path.exists():
        print(f"File not found: {path}")
        return []
    records: List[Record] = []
    with path.open("r", encoding="utf-8") as fh:
        for idx, line in enumerate(fh):
            if limit and idx >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if isinstance(rec, dict):
                    records.append(rec)
            except json.JSONDecodeError:
                continue
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze trade PnL history JSONL")
    parser.add_argument("--file", default="data/trade_pnl_history.jsonl", help="Path to JSONL PnL history")
    parser.add_argument("--score-bucket", type=int, default=1, help="Bucket width for score grouping (if present)")
    parser.add_argument("--limit", type=int, default=None, help="Only process first N records")
    parser.add_argument("--top", type=int, default=10, help="Show top N groups")
    args = parser.parse_args()

    path = Path(args.file)
    records = load_records(path, limit=args.limit)
    if not records:
        print("No records found.")
        return

    overall = _summary(records)
    _print_section("Overall", overall)

    by_market = _group(records, lambda r: str(r.get("market")) if r.get("market") else None)
    if by_market:
        _print_top_groups("Per Market", by_market, limit=args.top)

    # Optional score bucketing when score available
    def score_bucket(rec: Record) -> str | None:
        score_val = rec.get("score")
        if score_val is None:
            return None
        try:
            score = float(score_val)
        except Exception:
            return None
        width = max(1, int(args.score_bucket))
        lower = math.floor(score / width) * width
        upper = lower + width
        return f"{lower:.0f}-{upper:.0f}"

    by_score = _group(records, score_bucket)
    if by_score:
        _print_top_groups("Score Buckets", by_score, limit=args.top)


if __name__ == "__main__":
     main()
