"""Model registry — read/write metadata next to model artefacts.

For each model file (e.g. `ai/ai_xgb_model.json`) we maintain a sibling
`{model}.meta.json` with version, training date, sample size, feature schema,
and validation metrics. This makes models reproducible and enables safe
rollback.

Usage:
    from ai.model_registry import register_model, latest_model_metadata
    register_model("ai/ai_xgb_model.json", n_train=2000, val_metric=0.62, ...)
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from ai.features import FEATURE_STORE_VERSION, schema_metadata

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _meta_path(model_path: str | Path) -> Path:
    p = Path(model_path)
    return p.with_suffix(p.suffix + ".meta.json") if p.suffix else p.with_suffix(".meta.json")


def register_model(
    model_path: str | Path,
    *,
    n_train: int,
    val_metric: float,
    metric_name: str = "accuracy",
    algo: str = "xgboost",
    notes: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> Path:
    """Write a `.meta.json` next to the model. Returns its path."""
    model_path = Path(model_path)
    meta = {
        "model_path": str(model_path),
        "algo": algo,
        "trained_at_ts": time.time(),
        "trained_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_train": int(n_train),
        "metric_name": metric_name,
        "val_metric": float(val_metric),
        "feature_store_version": FEATURE_STORE_VERSION,
        "feature_schema": schema_metadata(),
        "git_commit": _git_head(),
        "notes": notes,
    }
    if extra:
        meta["extra"] = extra
    meta_path = _meta_path(model_path)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = meta_path.with_suffix(meta_path.suffix + ".tmp")
    tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    os.replace(tmp, meta_path)
    return meta_path


def read_metadata(model_path: str | Path) -> Optional[Dict[str, Any]]:
    p = _meta_path(model_path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def latest_model_metadata(models_dir: str | Path = "ai") -> Optional[Dict[str, Any]]:
    """Return the most recently-trained model's metadata in the directory."""
    d = Path(models_dir)
    if not d.exists():
        return None
    metas = []
    for meta_file in d.glob("*.meta.json"):
        try:
            data = json.loads(meta_file.read_text(encoding="utf-8"))
            metas.append((float(data.get("trained_at_ts", 0)), data))
        except Exception:
            continue
    if not metas:
        return None
    metas.sort(reverse=True, key=lambda x: x[0])
    return metas[0][1]


def _git_head() -> str:
    try:
        head_file = _PROJECT_ROOT / ".git" / "HEAD"
        if not head_file.exists():
            return ""
        ref = head_file.read_text(encoding="utf-8").strip()
        if ref.startswith("ref:"):
            ref_path = _PROJECT_ROOT / ".git" / ref[5:].strip()
            if ref_path.exists():
                return ref_path.read_text(encoding="utf-8").strip()[:12]
        return ref[:12]
    except Exception:
        return ""


__all__ = ["register_model", "read_metadata", "latest_model_metadata"]
