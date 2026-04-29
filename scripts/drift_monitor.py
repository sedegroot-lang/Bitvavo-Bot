"""Feature drift monitor.

Compares the recent distribution of trading features (last N closed trades)
to a baseline. Alerts when any feature drifts more than `Z_THRESHOLD` standard
deviations from baseline mean.

Usage:
    python -m scripts.drift_monitor --baseline data/feature_baseline.json --recent 50
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List

from ai.features import feature_names

PROJECT_ROOT = Path(__file__).resolve().parent.parent
Z_THRESHOLD_DEFAULT = 3.0


def _load_recent_features(archive_path: Path, n: int) -> List[Dict[str, float]]:
    if not archive_path.exists():
        return []
    raw = json.loads(archive_path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        for k in ("trades", "closed"):
            if isinstance(raw.get(k), list):
                raw = raw[k]
                break
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, float]] = []
    # Iterate from newest to oldest until we have n records with ml_info
    for t in reversed(raw):
        ml = t.get("ml_info") if isinstance(t, dict) else None
        if not isinstance(ml, dict):
            continue
        rec: Dict[str, float] = {}
        for fname in feature_names():
            v = ml.get(fname)
            try:
                rec[fname] = float(v) if v is not None else math.nan
            except Exception:
                rec[fname] = math.nan
        out.append(rec)
        if len(out) >= n:
            break
    return out


def _summary(records: List[Dict[str, float]]) -> Dict[str, Dict[str, float]]:
    """Return {feature: {mean, std, n}} ignoring NaN."""
    summary: Dict[str, Dict[str, float]] = {}
    for fname in feature_names():
        vals = [r[fname] for r in records if fname in r and not math.isnan(r[fname])]
        if not vals:
            summary[fname] = {"mean": 0.0, "std": 0.0, "n": 0}
            continue
        m = statistics.fmean(vals)
        s = statistics.pstdev(vals) if len(vals) >= 2 else 0.0
        summary[fname] = {"mean": m, "std": s, "n": len(vals)}
    return summary


def detect_drift(baseline: Dict[str, Dict[str, float]],
                 recent: Dict[str, Dict[str, float]],
                 z_threshold: float) -> List[Dict[str, Any]]:
    alerts = []
    for fname, recent_stats in recent.items():
        base = baseline.get(fname)
        if not base or base.get("std", 0) <= 0 or recent_stats.get("n", 0) == 0:
            continue
        z = (recent_stats["mean"] - base["mean"]) / base["std"]
        if abs(z) >= z_threshold:
            alerts.append({
                "feature": fname,
                "z_score": round(z, 3),
                "baseline_mean": round(base["mean"], 4),
                "baseline_std": round(base["std"], 4),
                "recent_mean": round(recent_stats["mean"], 4),
                "recent_n": recent_stats["n"],
            })
    return alerts


def main() -> int:
    ap = argparse.ArgumentParser(description="Detect feature drift vs baseline.")
    ap.add_argument("--archive", default=str(PROJECT_ROOT / "data" / "trade_archive.json"))
    ap.add_argument("--baseline", default=str(PROJECT_ROOT / "data" / "feature_baseline.json"),
                    help="Baseline JSON (auto-created from older trades if missing)")
    ap.add_argument("--recent", type=int, default=50, help="N most recent closed trades")
    ap.add_argument("--baseline-recent", type=int, default=300, help="Used to seed baseline if missing")
    ap.add_argument("--z", type=float, default=Z_THRESHOLD_DEFAULT)
    ap.add_argument("--update-baseline", action="store_true",
                    help="Overwrite baseline using --baseline-recent trades")
    args = ap.parse_args()

    archive = Path(args.archive)
    baseline_path = Path(args.baseline)

    if args.update_baseline or not baseline_path.exists():
        baseline_records = _load_recent_features(archive, args.baseline_recent)
        baseline_summary = _summary(baseline_records)
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(baseline_summary, indent=2), encoding="utf-8")
        print(f"[drift_monitor] baseline saved: {baseline_path} ({len(baseline_records)} trades)")
        if args.update_baseline:
            return 0

    baseline_summary = json.loads(baseline_path.read_text(encoding="utf-8"))
    recent_records = _load_recent_features(archive, args.recent)
    if not recent_records:
        print("[drift_monitor] no recent records — nothing to check")
        return 0
    recent_summary = _summary(recent_records)
    alerts = detect_drift(baseline_summary, recent_summary, args.z)
    out = {
        "checked_features": len(recent_summary),
        "z_threshold": args.z,
        "recent_n": len(recent_records),
        "alerts": alerts,
    }
    print(json.dumps(out, indent=2))
    return 1 if alerts else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
