import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.model_selection import train_test_split

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.ai_engine import AIEngine, FEATURE_NAMES
from modules.logging_utils import log

try:
    import xgboost as xgb
except Exception:  # pragma: no cover - xgboost optional but required for training
    xgb = None

FEATURE_ORDER = FEATURE_NAMES
MODEL_PATH = Path('ai_xgb_model.json')
METRICS_PATH = Path('ai_model_metrics.json')


def parse_args():
    parser = argparse.ArgumentParser(description='Train AI model for Bitvavo bot using recent candles.')
    parser.add_argument('--interval', default='1m', help='Bitvavo candle interval (default 1m).')
    parser.add_argument('--limit', type=int, default=500, help='Number of candles to fetch per market (default 500).')
    parser.add_argument('--min-samples', type=int, default=200, help='Minimum samples required to train.')
    parser.add_argument('--lookahead', type=int, default=15, help='Lookahead bars for target (default 15).')
    parser.add_argument('--target-threshold', type=float, default=0.0075,
                        help='Return threshold for positive class (e.g. 0.0075 = 0.75%%).')
    parser.add_argument('--test-size', type=float, default=0.2, help='Holdout size for evaluation.')
    parser.add_argument('--max-models', type=int, default=1,
                        help='How many model versions to keep (oldest pruned). Default 1 (latest only).')
    parser.add_argument('--output-dir', default='models', help='Directory to store versioned models (JSON).')
    return parser.parse_args()


def fetch_samples(engine: AIEngine, markets, interval: str, limit: int, lookahead: int, threshold: float):
    records = []
    for market in markets:
        candles = engine.candles(market, interval, limit)
        if not candles or len(candles) < (lookahead + 120):
            continue
        closes = engine._closes(candles)
        highs = engine._highs(candles)
        lows = engine._lows(candles)
        for idx in range(120, len(candles) - lookahead):
            window = [list(c) for c in candles[max(0, idx - 180):idx + 1]]
            feats = engine.compute_features_from_candles(window)
            if not feats:
                continue
            entry_price = closes[idx]
            future_price = closes[idx + lookahead]
            future_ret = (future_price / entry_price) - 1
            label = 1 if future_ret >= threshold else 0
            record = {
                'market': market,
                'timestamp': int(candles[idx][0] / 1000),
                'future_return': future_ret,
                'label': label
            }
            for f in FEATURE_ORDER:
                record[f] = feats.get(f)
            records.append(record)
    return pd.DataFrame(records)


def train_model(df: pd.DataFrame, test_size: float):
    if df.empty:
        raise ValueError('No training samples collected.')
    X = df[FEATURE_ORDER].values
    y = df['label'].values
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=test_size, stratify=y, random_state=42)

    pos_ratio = max(np.sum(y_train) / max(len(y_train), 1), 1e-3)
    scale_pos_weight = float((1 - pos_ratio) / pos_ratio)

    model = xgb.XGBClassifier(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        objective='binary:logistic',
        eval_metric='auc',
        tree_method='hist',
        scale_pos_weight=scale_pos_weight,
        random_state=42
    )
    model.fit(X_train, y_train)

    probas = model.predict_proba(X_test)[:, 1]
    preds = (probas >= 0.5).astype(int)
    auc = roc_auc_score(y_test, probas)
    report = classification_report(y_test, preds, output_dict=True)

    metrics = {
        'trained_at': int(time.time()),
        'auc': auc,
        'support': len(y),
        'positive_ratio': float(np.mean(y)),
        'classification_report': report,
        'feature_means': df[FEATURE_ORDER].mean().to_dict(),
        'feature_stds': df[FEATURE_ORDER].std().fillna(0).to_dict()
    }
    return model, metrics


def save_versioned_model(model, metrics, output_dir: Path, max_models: int):
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime('%Y%m%dT%H%M%S', time.gmtime())
    model_path = output_dir / f'ai_xgb_model_{timestamp}.json'
    model.save_model(model_path)
    with open(output_dir / f'ai_xgb_metrics_{timestamp}.json', 'w', encoding='utf-8') as fh:
        json.dump(metrics, fh, indent=2)

    # Keep symlink / copy of latest for runtime usage
    model.save_model(MODEL_PATH)
    with open(METRICS_PATH, 'w', encoding='utf-8') as fh:
        json.dump(metrics, fh, indent=2)

    # prune old versions
    versions = sorted(output_dir.glob('ai_xgb_model_*.json'))
    if len(versions) > max_models:
        for old in versions[:-max_models]:
            try:
                old.unlink()
            except Exception:
                pass
            metrics_file = output_dir / f"ai_xgb_metrics_{old.stem.split('_')[-1]}.json"
            if metrics_file.exists():
                try:
                    metrics_file.unlink()
                except Exception:
                    pass


def main():
    args = parse_args()
    if xgb is None:
        raise RuntimeError('xgboost package is required for training. Install it via pip install xgboost.')

    load_dotenv()
    engine = AIEngine()
    markets = engine.get_whitelist()
    if not markets:
        raise RuntimeError('No whitelist markets found in config; cannot train model.')

    df = fetch_samples(engine, markets, args.interval, args.limit, args.lookahead, args.target_threshold)
    if len(df) < args.min_samples:
        raise RuntimeError(f'Collected {len(df)} samples, which is below the minimum of {args.min_samples}. Increase limit or widen threshold.')

    model, metrics = train_model(df, args.test_size)
    save_versioned_model(model, metrics, Path(args.output_dir), args.max_models)

    log(f"Trained AI model with AUC={metrics['auc']:.3f} on {metrics['support']} samples (pos ratio {metrics['positive_ratio']:.3f}).")
    print(json.dumps({'auc': metrics['auc'], 'support': metrics['support'], 'positive_ratio': metrics['positive_ratio']}, indent=2))

if __name__ == '__main__':
    main()
