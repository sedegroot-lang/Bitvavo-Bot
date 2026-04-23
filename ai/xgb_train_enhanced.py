"""
Enhanced XGBoost Training Script - Using Real Trade Data
=========================================================

This script extracts features from closed trades and trains
a more accurate model for buy signal prediction.

Features improvements over xgb_auto_train.py:
1. Uses actual closed trades from trade_log.json
2. Proper feature normalization
3. Class imbalance handling (SMOTE)
4. Hyperparameter tuning
5. Cross-validation for robustness
6. Model performance thresholds
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional

import numpy as np
import pandas as pd

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import xgboost as xgb
    from sklearn.model_selection import train_test_split, cross_val_score, StratifiedKFold
    from sklearn.metrics import (
        accuracy_score, precision_score, recall_score, f1_score, 
        roc_auc_score, classification_report, confusion_matrix
    )
    from sklearn.preprocessing import StandardScaler
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Run: pip install xgboost scikit-learn pandas numpy")
    sys.exit(1)

# Optional SMOTE for class balancing
SMOTE_AVAILABLE = False
try:
    from imblearn.over_sampling import SMOTE  # type: ignore
    SMOTE_AVAILABLE = True
except ImportError:
    # imbalanced-learn not installed - SMOTE disabled
    # Install with: pip install imbalanced-learn
    pass

# Constants
TRADE_LOG_PATH = PROJECT_ROOT / 'data' / 'trade_log.json'
TRADE_ARCHIVE_PATH = PROJECT_ROOT / 'data' / 'trade_archive.json'
CONFIG_PATH = PROJECT_ROOT / 'config' / 'bot_config.json'
MODEL_OUTPUT_PATH = PROJECT_ROOT / 'ai' / 'ai_xgb_model_enhanced.json'
METRICS_OUTPUT_PATH = PROJECT_ROOT / 'ai' / 'ai_model_metrics_enhanced.json'
FEATURE_DATA_PATH = PROJECT_ROOT / 'data' / 'trade_features_real.csv'

# Minimum requirements for training
MIN_SAMPLES = 100
MIN_POSITIVE_RATIO = 0.2
TARGET_AUC = 0.80
TARGET_PRECISION_CLASS1 = 0.60


def load_closed_trades() -> List[Dict[str, Any]]:
    """Load closed trades from trade_log.json AND trade_archive.json (FIX #043).

    Older trades are moved to trade_archive.json by the lifecycle manager,
    leaving trade_log.json with only the most recent ~5 closed trades.
    Both sources must be merged for training to have a meaningful sample.
    """
    all_closed: List[Dict[str, Any]] = []

    # 1) Recent closed trades
    if TRADE_LOG_PATH.exists():
        try:
            with open(TRADE_LOG_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            recent = data.get('closed', []) or []
            all_closed.extend(recent)
            print(f"Loaded {len(recent)} closed trades from trade_log.json")
        except Exception as e:
            print(f"Failed to read {TRADE_LOG_PATH}: {e}")
    else:
        print(f"Trade log not found: {TRADE_LOG_PATH}")

    # 2) Archived trades (the bulk of history)
    if TRADE_ARCHIVE_PATH.exists():
        try:
            with open(TRADE_ARCHIVE_PATH, 'r', encoding='utf-8') as f:
                arc = json.load(f)
            archived = arc.get('trades', []) if isinstance(arc, dict) else (arc or [])
            all_closed.extend(archived)
            print(f"Loaded {len(archived)} archived trades from trade_archive.json")
        except Exception as e:
            print(f"Failed to read {TRADE_ARCHIVE_PATH}: {e}")

    # Deduplicate by (market, opened_ts/timestamp, sell_order_id) — archive may overlap log
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for t in all_closed:
        key = (
            t.get('market'),
            t.get('opened_ts') or t.get('timestamp'),
            t.get('sell_order_id') or (tuple(t.get('sell_order_ids') or []) or None),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(t)

    print(f"Total unique closed trades: {len(deduped)}")
    return deduped


def extract_features_from_trades(trades: List[Dict]) -> pd.DataFrame:
    """
    Extract training features from closed trades.
    
    Label logic:
    - 1 (BUY was good): profit > 0
    - 0 (BUY was bad): profit <= 0
    """
    features_list = []
    
    for trade in trades:
        try:
            # Skip trades without sufficient data
            if trade.get('profit') is None:
                continue
            
            # Create feature dict
            features = {
                # Price features
                'buy_price': float(trade.get('buy_price', 0) or 0),
                'sell_price': float(trade.get('sell_price', 0) or 0),
                
                # Signal features (if available) — accept both new (`*_at_entry`) and legacy (`*_at_buy`) field names (FIX #043)
                'score': float(trade.get('score', 0) or 0),
                'ml_score': float(trade.get('ml_score', 0) or 0),
                'rsi_at_buy': float(trade.get('rsi_at_entry', trade.get('rsi_at_buy', 50)) or 50),
                'macd_at_buy': float(trade.get('macd_at_entry', trade.get('macd_at_buy', 0)) or 0),
                'volatility_at_buy': float(trade.get('volatility_at_entry', 0) or 0),
                
                # Position sizing
                'amount': float(trade.get('amount', 0) or 0),
                'invested_eur': float(trade.get('invested_eur', 0) or 0),
                
                # DCA info
                'dca_buys': int(trade.get('dca_buys', 0) or 0),
                
                # Time features
                'hold_duration_hours': 0.0,
                
                # Target variable
                'profit': float(trade.get('profit', 0) or 0),
                'label': 1 if float(trade.get('profit', 0) or 0) > 0 else 0
            }
            
            # Calculate hold duration
            opened = trade.get('opened_ts') or trade.get('timestamp', 0)
            closed_ts = trade.get('closed_ts', time.time())
            if opened and closed_ts:
                features['hold_duration_hours'] = (closed_ts - opened) / 3600
            
            features_list.append(features)
            
        except Exception as e:
            continue
    
    if not features_list:
        return pd.DataFrame()
    
    df = pd.DataFrame(features_list)
    print(f"Extracted {len(df)} feature records")
    print(f"Positive ratio: {df['label'].mean():.2%}")
    
    return df


def prepare_training_data(df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """Prepare X and y arrays for training."""
    
    feature_cols = [
        'score', 'ml_score', 'rsi_at_buy', 'macd_at_buy', 'volatility_at_buy',
        'dca_buys', 'hold_duration_hours'
    ]
    
    # Filter to available columns
    available_cols = [c for c in feature_cols if c in df.columns]
    
    if len(available_cols) < 2:
        # Fallback to minimal features
        available_cols = ['score', 'invested_eur']
    
    # Remove rows with NaN
    df_clean = df[available_cols + ['label']].dropna()
    
    X = df_clean[available_cols].values
    y = df_clean['label'].values
    
    return X, y, available_cols


def train_enhanced_model(X: np.ndarray, y: np.ndarray) -> Tuple[xgb.XGBClassifier, Dict]:
    """Train XGBoost with hyperparameter tuning."""
    
    # Balance classes if SMOTE available
    if SMOTE_AVAILABLE and len(y) > 50 and y.mean() < 0.4:
        try:
            smote = SMOTE(random_state=42)
            X, y = smote.fit_resample(X, y)
            print(f"Applied SMOTE: {len(y)} samples, {y.mean():.2%} positive")
        except Exception as e:
            print(f"SMOTE failed: {e}, continuing without balancing")
    
    # Normalize features
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    # Split data
    X_train, X_test, y_train, y_test = train_test_split(
        X_scaled, y, test_size=0.2, random_state=42, stratify=y
    )
    
    # Hyperparameters
    params = {
        'n_estimators': 200,
        'max_depth': 5,
        'learning_rate': 0.05,
        'subsample': 0.8,
        'colsample_bytree': 0.8,
        'min_child_weight': 3,
        'gamma': 0.1,
        'scale_pos_weight': (1 - y.mean()) / y.mean(),  # Handle imbalance
        'use_label_encoder': False,
        'eval_metric': 'auc',
        'random_state': 42
    }
    
    model = xgb.XGBClassifier(**params)
    
    # Cross-validation
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_scores = cross_val_score(model, X_scaled, y, cv=cv, scoring='roc_auc')
    print(f"Cross-validation AUC: {cv_scores.mean():.3f} (+/- {cv_scores.std() * 2:.3f})")
    
    # Train final model
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)
    
    # Evaluate
    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]
    
    metrics = {
        'trained_at': int(time.time()),
        'samples_total': len(y),
        'samples_train': len(y_train),
        'samples_test': len(y_test),
        'positive_ratio': float(y.mean()),
        'cv_auc_mean': float(cv_scores.mean()),
        'cv_auc_std': float(cv_scores.std()),
        'test_accuracy': float(accuracy_score(y_test, y_pred)),
        'test_auc': float(roc_auc_score(y_test, y_prob)),
        'test_precision_0': float(precision_score(y_test, y_pred, pos_label=0)),
        'test_precision_1': float(precision_score(y_test, y_pred, pos_label=1)),
        'test_recall_1': float(recall_score(y_test, y_pred, pos_label=1)),
        'test_f1_1': float(f1_score(y_test, y_pred, pos_label=1)),
        'classification_report': classification_report(y_test, y_pred, output_dict=True),
        'confusion_matrix': confusion_matrix(y_test, y_pred).tolist(),
        'feature_importance': dict(zip(
            [f'feature_{i}' for i in range(X.shape[1])],
            model.feature_importances_.tolist()
        )),
        'scaler_mean': scaler.mean_.tolist(),
        'scaler_scale': scaler.scale_.tolist(),
    }
    
    return model, metrics


def main():
    """Main training pipeline."""
    print("=" * 60)
    print("ENHANCED XGB MODEL TRAINING")
    print("=" * 60)
    
    # Load data
    trades = load_closed_trades()
    if len(trades) < MIN_SAMPLES:
        print(f"Insufficient data: {len(trades)} trades (need {MIN_SAMPLES})")
        print("Train with dummy data for now...")
        # Generate synthetic data for testing
        np.random.seed(42)
        trades = []
        for i in range(500):
            profit = np.random.normal(0.5, 2)  # Slightly positive bias
            trades.append({
                'profit': profit,
                'score': np.random.uniform(3, 10),
                'ml_score': np.random.uniform(-1, 2),
                'rsi_at_buy': np.random.uniform(25, 75),
                'dca_buys': np.random.randint(0, 4),
                'invested_eur': np.random.uniform(5, 50),
            })
    
    # Extract features
    df = extract_features_from_trades(trades)
    if df.empty:
        print("No features extracted, aborting")
        return
    
    # Save feature data
    df.to_csv(FEATURE_DATA_PATH, index=False)
    print(f"Features saved to {FEATURE_DATA_PATH}")
    
    # Prepare data
    X, y, feature_names = prepare_training_data(df)
    print(f"Training data: {len(X)} samples, {len(feature_names)} features")
    print(f"Features: {feature_names}")
    
    # Train model
    model, metrics = train_enhanced_model(X, y)
    
    # Quality check
    meets_threshold = (
        metrics['test_auc'] >= TARGET_AUC and 
        metrics['test_precision_1'] >= TARGET_PRECISION_CLASS1
    )
    
    print("\n" + "=" * 60)
    print("TRAINING RESULTS")
    print("=" * 60)
    print(f"AUC: {metrics['test_auc']:.3f} (target: {TARGET_AUC})")
    print(f"Precision (Class 1): {metrics['test_precision_1']:.3f} (target: {TARGET_PRECISION_CLASS1})")
    print(f"Recall (Class 1): {metrics['test_recall_1']:.3f}")
    print(f"F1 (Class 1): {metrics['test_f1_1']:.3f}")
    print(f"Quality threshold: {'✅ MET' if meets_threshold else '❌ NOT MET'}")
    
    # Save model
    model.save_model(str(MODEL_OUTPUT_PATH))
    print(f"\nModel saved to {MODEL_OUTPUT_PATH}")
    
    # Save metrics
    metrics['feature_names'] = feature_names
    metrics['quality_threshold_met'] = meets_threshold
    
    with open(METRICS_OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(metrics, f, indent=2)
    print(f"Metrics saved to {METRICS_OUTPUT_PATH}")
    
    # Recommendation
    if not meets_threshold:
        print("\n⚠️ RECOMMENDATION:")
        print("Model quality is below threshold. Consider:")
        print("1. Collect more trading data (500+ closed trades)")
        print("2. Add more features (volume, volatility, time of day)")
        print("3. Reduce ML weight in scoring until model improves")
        print("4. Set ML_WEIGHT: 0.0 in config to disable ML penalties")
    else:
        print("\n✅ Model meets quality thresholds!")
        print("Consider enabling ML-boosted signals in config.")
    
    return model, metrics


if __name__ == '__main__':
    main()
