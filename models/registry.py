"""Model registry — scans `models/` for trained model + metric pairs and produces a registry index.

Each entry: { model_path, metrics_path, trained_at, auc, support, positive_ratio, version }.

Pure / read-only — never mutates models, never raises (returns empty list on error).
Run via:
    python -m models.registry           # writes models/registry.json
    python -m models.registry --print   # stdout only
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

MODELS_DIR = Path(__file__).resolve().parent
REGISTRY_PATH = MODELS_DIR / "registry.json"

# Filename patterns: ai_xgb_model_<ts>.json + ai_xgb_metrics_<ts>.json
_MODEL_RE = re.compile(r"^(?P<family>ai_xgb)_model_(?P<ts>\d{8}T\d{6})\.json$")
_METRICS_SUFFIX = "_metrics_"


def _safe_read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def scan_models() -> List[Dict[str, Any]]:
    """Return list of model entries with metadata, newest first."""
    entries: List[Dict[str, Any]] = []
    if not MODELS_DIR.exists():
        return entries
    for model_path in sorted(MODELS_DIR.glob("ai_xgb_model_*.json")):
        m = _MODEL_RE.match(model_path.name)
        if not m:
            continue
        ts = m.group("ts")
        family = m.group("family")
        metrics_path = MODELS_DIR / f"{family}_metrics_{ts}.json"
        meta = _safe_read_json(metrics_path) or {}
        entry: Dict[str, Any] = {
            "family": family,
            "version_ts": ts,
            "model_path": model_path.name,
            "metrics_path": metrics_path.name if metrics_path.exists() else None,
            "trained_at": meta.get("trained_at"),
            "auc": meta.get("auc"),
            "support": meta.get("support"),
            "positive_ratio": meta.get("positive_ratio"),
            "size_bytes": model_path.stat().st_size,
        }
        entries.append(entry)
    # Newest first by version_ts
    entries.sort(key=lambda e: e.get("version_ts") or "", reverse=True)
    return entries


def write_registry() -> Dict[str, Any]:
    entries = scan_models()
    payload = {
        "generated_at": int(time.time()),
        "model_count": len(entries),
        "latest": entries[0] if entries else None,
        "models": entries,
    }
    try:
        tmp = REGISTRY_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(REGISTRY_PATH)
    except Exception:
        pass
    return payload


def latest_model() -> Optional[Dict[str, Any]]:
    entries = scan_models()
    return entries[0] if entries else None


if __name__ == "__main__":
    payload = scan_models()
    if "--print" in sys.argv:
        print(json.dumps({"models": payload, "count": len(payload)}, indent=2))
    else:
        result = write_registry()
        print(f"Wrote {REGISTRY_PATH} ({result['model_count']} models)")
