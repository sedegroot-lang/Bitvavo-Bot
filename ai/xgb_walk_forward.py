"""
Walk-Forward XGBoost Validation
================================
Trains XGBoost on rolling windows and validates on the next period.
This prevents data leakage and gives realistic out-of-sample performance.

Usage:
    python ai/xgb_walk_forward.py
    python ai/xgb_walk_forward.py --window 500 --step 100

Process:
  1. Load trade_features.csv
  2. Split into rolling windows: train on [i..i+window], test on [i+window..i+window+step]
  3. For each fold: train XGB, predict, record accuracy + log-loss
  4. Final model trained on the LAST window (most recent data)
  5. Outputs per-fold metrics + average to metrics/xgb_walkforward.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import accuracy_score, log_loss, precision_score, recall_score

# Allow imports from project root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from modules.config import load_config
    CONFIG = load_config() or {}
except Exception:
    CONFIG = {}

DATA_FILE = ROOT / "trade_features.csv"
MODEL_FILE = CONFIG.get("XGB_MODEL_PATH") or CONFIG.get("MODEL_PATH") or "ai/ai_xgb_model.json"
METRICS_DIR = ROOT / "metrics"


def load_data(path: Path) -> pd.DataFrame:
    """Load feature data. Expected columns: features + 'label'."""
    if not path.exists():
        raise FileNotFoundError(f"No training data at {path}")
    df = pd.read_csv(path)
    if "label" not in df.columns:
        raise ValueError("Missing 'label' column in training data")
    return df


def detect_feature_cols(df: pd.DataFrame) -> List[str]:
    """Auto-detect feature columns (everything except label, timestamp, market)."""
    exclude = {"label", "timestamp", "market", "date", "ts"}
    return [c for c in df.columns if c.lower() not in exclude and df[c].dtype in ("float64", "int64", "float32", "int32")]


def walk_forward(
    df: pd.DataFrame,
    feature_cols: List[str],
    window: int = 500,
    step: int = 100,
    xgb_params: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Run walk-forward validation."""

    if xgb_params is None:
        xgb_params = {
            "n_estimators": int(CONFIG.get("XGB_N_ESTIMATORS", 200)),
            "max_depth": int(CONFIG.get("XGB_MAX_DEPTH", 4)),
            "learning_rate": float(CONFIG.get("XGB_LEARNING_RATE", 0.05)),
            "subsample": float(CONFIG.get("XGB_SUBSAMPLE", 0.8)),
            "colsample_bytree": float(CONFIG.get("XGB_COLSAMPLE", 0.8)),
            "min_child_weight": int(CONFIG.get("XGB_MIN_CHILD_WEIGHT", 5)),
            "eval_metric": "logloss",
            "use_label_encoder": False,
            "random_state": 42,
        }

    X = df[feature_cols].values
    y = df["label"].values
    n = len(df)

    if n < window + step:
        print(f"  WARNING: Only {n} samples, need {window + step}. Training on all data.")
        model = xgb.XGBClassifier(**xgb_params)
        model.fit(X, y)
        model.save_model(str(ROOT / MODEL_FILE))
        return {
            "folds": 0,
            "samples": n,
            "note": "Not enough data for walk-forward, trained on all data",
        }

    folds: List[Dict[str, Any]] = []
    start = 0

    while start + window + step <= n:
        train_end = start + window
        test_end = min(train_end + step, n)

        X_train, y_train = X[start:train_end], y[start:train_end]
        X_test, y_test = X[train_end:test_end], y[train_end:test_end]

        # Skip folds where test set has only one class
        if len(set(y_test)) < 2 or len(set(y_train)) < 2:
            start += step
            continue

        model = xgb.XGBClassifier(**xgb_params)
        model.fit(X_train, y_train, verbose=False)

        preds = model.predict(X_test)
        probs = model.predict_proba(X_test)

        fold_result = {
            "fold": len(folds) + 1,
            "train_range": f"{start}-{train_end}",
            "test_range": f"{train_end}-{test_end}",
            "accuracy": round(float(accuracy_score(y_test, preds)), 4),
            "precision": round(float(precision_score(y_test, preds, zero_division=0)), 4),
            "recall": round(float(recall_score(y_test, preds, zero_division=0)), 4),
            "log_loss": round(float(log_loss(y_test, probs)), 4),
            "train_samples": int(train_end - start),
            "test_samples": int(test_end - train_end),
            "buy_rate_train": round(float(y_train.mean()), 4),
            "buy_rate_test": round(float(y_test.mean()), 4),
        }
        folds.append(fold_result)
        start += step

    # Train final model on the most recent window
    final_start = max(0, n - window)
    X_final, y_final = X[final_start:], y[final_start:]
    final_model = xgb.XGBClassifier(**xgb_params)
    final_model.fit(X_final, y_final, verbose=False)
    final_model.save_model(str(ROOT / MODEL_FILE))

    # Feature importances from final model
    importances = dict(zip(feature_cols, [round(float(x), 4) for x in final_model.feature_importances_]))

    # Summary
    if folds:
        avg_acc = round(np.mean([f["accuracy"] for f in folds]), 4)
        avg_prec = round(np.mean([f["precision"] for f in folds]), 4)
        avg_recall = round(np.mean([f["recall"] for f in folds]), 4)
        avg_logloss = round(np.mean([f["log_loss"] for f in folds]), 4)
        std_acc = round(float(np.std([f["accuracy"] for f in folds])), 4)
    else:
        avg_acc = avg_prec = avg_recall = avg_logloss = std_acc = 0.0

    result = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total_samples": n,
        "window_size": window,
        "step_size": step,
        "num_folds": len(folds),
        "features": feature_cols,
        "feature_importances": importances,
        "avg_accuracy": avg_acc,
        "std_accuracy": std_acc,
        "avg_precision": avg_prec,
        "avg_recall": avg_recall,
        "avg_log_loss": avg_logloss,
        "folds": folds,
        "model_saved": str(ROOT / MODEL_FILE),
        "xgb_params": {k: v for k, v in xgb_params.items() if k != "use_label_encoder"},
    }

    return result


def main():
    parser = argparse.ArgumentParser(description="Walk-Forward XGBoost Validation")
    parser.add_argument("--window", type=int, default=500, help="Training window size")
    parser.add_argument("--step", type=int, default=100, help="Step/test size per fold")
    args = parser.parse_args()

    print("╔══════════════════════════════════════════╗")
    print("║  Walk-Forward XGBoost Validation          ║")
    print("╠══════════════════════════════════════════╣")
    print(f"║  Window: {args.window:>6}  Step: {args.step:>6}           ║")
    print("╚══════════════════════════════════════════╝")

    df = load_data(DATA_FILE)
    feature_cols = detect_feature_cols(df)
    print(f"\n  Samples: {len(df)}")
    print(f"  Features: {feature_cols}")
    print(f"  Buy rate: {df['label'].mean():.2%}")

    result = walk_forward(df, feature_cols, args.window, args.step)

    # Save metrics
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    metrics_path = METRICS_DIR / "xgb_walkforward.json"
    with open(metrics_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"\n  ═══ RESULTS ═══")
    print(f"  Folds:          {result.get('num_folds', 0)}")
    print(f"  Avg Accuracy:   {result.get('avg_accuracy', 0):.2%} ± {result.get('std_accuracy', 0):.2%}")
    print(f"  Avg Precision:  {result.get('avg_precision', 0):.2%}")
    print(f"  Avg Recall:     {result.get('avg_recall', 0):.2%}")
    print(f"  Avg Log Loss:   {result.get('avg_log_loss', 0):.4f}")
    print(f"  Feature Imp:    {result.get('feature_importances', {})}")
    print(f"\n  Model saved: {result.get('model_saved')}")
    print(f"  Metrics: {metrics_path}")


if __name__ == "__main__":
    main()
