"""
ML Model Training Pipeline
Train XGBoost models with hyperparameter tuning and evaluation.
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
import json
from datetime import datetime
from typing import Dict

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import xgboost as xgb
from sklearn.model_selection import train_test_split, GridSearchCV, cross_val_score
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score, confusion_matrix
from modules.logging_utils import log


class MLModelTrainer:
    """Train and evaluate ML models for trading signals."""
    
    def __init__(self, model_save_path: str = "ai/ai_xgboost_model.json",
                 metrics_path: str = "ai/ai_model_metrics.json"):
        self.model_save_path = Path(model_save_path)
        self.metrics_path = Path(metrics_path)
        self.model = None
        self.feature_names = []
    
    def train_xgboost(self, X: pd.DataFrame, y: pd.Series, 
                     hyperparameter_tuning: bool = True) -> Dict:
        """
        Train XGBoost model with optional hyperparameter tuning.
        
        Returns:
            Dictionary with metrics
        """
        log(f"[TRAIN] Starting XGBoost training with {len(X)} samples...")
        
        # Store feature names
        self.feature_names = list(X.columns) if hasattr(X, 'columns') else [f'feature_{i}' for i in range(X.shape[1])]
        
        # Train/test split
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )
        
        log(f"[TRAIN] Train: {len(X_train)}, Test: {len(X_test)}")
        log(f"[TRAIN] Train win rate: {y_train.mean():.2%}, Test win rate: {y_test.mean():.2%}")
        
        # Hyperparameter tuning
        if hyperparameter_tuning:
            log("[TRAIN] Running hyperparameter tuning (this may take a while)...")
            best_params = self._hyperparameter_tuning(X_train, y_train)
        else:
            best_params = {
                'max_depth': 5,
                'learning_rate': 0.1,
                'n_estimators': 200,
                'min_child_weight': 3,
                'subsample': 0.8,
                'colsample_bytree': 0.8
            }
        
        # Train final model
        log(f"[TRAIN] Training final model with params: {best_params}")
        self.model = xgb.XGBClassifier(
            use_label_encoder=False,
            eval_metric='logloss',
            **best_params
        )
        self.model.fit(X_train, y_train)
        
        # Evaluate
        metrics = self._evaluate_model(X_test, y_test)
        metrics['best_params'] = best_params
        metrics['feature_count'] = len(self.feature_names)
        metrics['train_samples'] = len(X_train)
        metrics['test_samples'] = len(X_test)
        metrics['train_win_rate'] = float(y_train.mean())
        metrics['test_win_rate'] = float(y_test.mean())
        
        # Save model
        self.save_model()
        self.save_metrics(metrics)
        
        log(f"[TRAIN] Training complete. Accuracy: {metrics['accuracy']:.2%}")
        return metrics
    
    def _hyperparameter_tuning(self, X_train, y_train) -> Dict:
        """Perform hyperparameter tuning with GridSearchCV."""
        param_grid = {
            'max_depth': [3, 5, 7],
            'learning_rate': [0.01, 0.1, 0.3],
            'n_estimators': [100, 200, 500],
            'min_child_weight': [1, 3, 5],
            'subsample': [0.8, 0.9, 1.0],
            'colsample_bytree': [0.8, 0.9, 1.0]
        }
        
        xgb_model = xgb.XGBClassifier(use_label_encoder=False, eval_metric='logloss')
        
        grid_search = GridSearchCV(
            xgb_model,
            param_grid,
            cv=5,
            scoring='f1',
            n_jobs=-1,
            verbose=1
        )
        
        grid_search.fit(X_train, y_train)
        
        log(f"[TRAIN] Best params: {grid_search.best_params_}")
        log(f"[TRAIN] Best CV score: {grid_search.best_score_:.4f}")
        
        return grid_search.best_params_
    
    def _evaluate_model(self, X_test, y_test) -> Dict:
        """Evaluate model on test set."""
        y_pred = self.model.predict(X_test)
        y_pred_proba = self.model.predict_proba(X_test)[:, 1]
        
        metrics = {
            'accuracy': float(accuracy_score(y_test, y_pred)),
            'precision': float(precision_score(y_test, y_pred, zero_division=0)),
            'recall': float(recall_score(y_test, y_pred, zero_division=0)),
            'f1_score': float(f1_score(y_test, y_pred, zero_division=0)),
            'roc_auc': float(roc_auc_score(y_test, y_pred_proba)),
            'confusion_matrix': confusion_matrix(y_test, y_pred).tolist(),
            'timestamp': datetime.now().isoformat()
        }
        
        # Feature importances
        if hasattr(self.model, 'feature_importances_'):
            importances = self.model.feature_importances_
            feature_importance = dict(zip(self.feature_names, importances.tolist()))
            # Get top 10 features
            sorted_features = sorted(feature_importance.items(), key=lambda x: x[1], reverse=True)
            metrics['top_10_features'] = dict(sorted_features[:10])
        
        return metrics
    
    def save_model(self):
        """Save trained model to disk."""
        self.model_save_path.parent.mkdir(parents=True, exist_ok=True)
        self.model.save_model(str(self.model_save_path))
        log(f"[TRAIN] Model saved to {self.model_save_path}")
    
    def save_metrics(self, metrics: Dict):
        """Save training metrics to JSON."""
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.metrics_path, 'w') as f:
            json.dump(metrics, f, indent=2)
        log(f"[TRAIN] Metrics saved to {self.metrics_path}")
    
    def cross_validate(self, X, y, cv=5) -> Dict:
        """Perform cross-validation."""
        log(f"[TRAIN] Running {cv}-fold cross-validation...")
        
        if self.model is None:
            self.model = xgb.XGBClassifier(use_label_encoder=False, eval_metric='logloss')
        
        cv_scores = cross_val_score(self.model, X, y, cv=cv, scoring='f1')
        
        metrics = {
            'cv_mean': float(cv_scores.mean()),
            'cv_std': float(cv_scores.std()),
            'cv_scores': cv_scores.tolist()
        }
        
        log(f"[TRAIN] CV F1 Score: {metrics['cv_mean']:.4f} (+/- {metrics['cv_std']:.4f})")
        return metrics


def main():
    """CLI entry point for model training."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Train ML models for trading')
    parser.add_argument('--data', type=str, required=True, help='Path to training data CSV')
    parser.add_argument('--tune', action='store_true', help='Enable hyperparameter tuning')
    parser.add_argument('--cv', type=int, default=5, help='Cross-validation folds')
    parser.add_argument('--output', type=str, default='ai/ai_xgb_model.json', help='Model output path')
    
    args = parser.parse_args()
    
    # Load data
    print(f"Loading data from {args.data}...")
    df = pd.DataFrame(pd.read_csv(args.data))
    
    # Separate features and labels
    label_col = 'label'
    if label_col not in df.columns:
        print(f"Error: '{label_col}' column not found in data")
        return
    
    y = df[label_col]
    X = df.drop(columns=[label_col, 'market', 'timestamp', 'profit'], errors='ignore')
    
    print(f"Features: {X.shape[1]}, Samples: {len(X)}, Win rate: {y.mean():.2%}")
    
    # Train model
    trainer = MLModelTrainer(model_save_path=args.output)
    metrics = trainer.train_xgboost(X, y, hyperparameter_tuning=args.tune)
    
    # Cross-validation
    if args.cv > 1:
        cv_metrics = trainer.cross_validate(X, y, cv=args.cv)
        metrics.update(cv_metrics)
    
    # Print results
    print("\n=== Training Complete ===")
    print(f"Accuracy: {metrics['accuracy']:.2%}")
    print(f"Precision: {metrics['precision']:.2%}")
    print(f"Recall: {metrics['recall']:.2%}")
    print(f"F1 Score: {metrics['f1_score']:.2%}")
    print(f"ROC AUC: {metrics['roc_auc']:.4f}")
    
    if 'top_10_features' in metrics:
        print("\nTop 10 Features:")
        for feat, importance in metrics['top_10_features'].items():
            print(f"  {feat}: {importance:.4f}")
    
    print(f"\nModel saved to: {args.output}")


if __name__ == "__main__":
    main()
