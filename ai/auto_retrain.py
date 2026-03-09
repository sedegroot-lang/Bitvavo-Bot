"""
Automated ML Retraining System
Automatically retrains models weekly or when performance degrades.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import time
from datetime import datetime, timedelta
from typing import Tuple, Dict, Optional
import logging

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')
log = logging.getLogger(__name__)


class AutoRetrain:
    """Manages automatic model retraining."""
    
    def __init__(self):
        self.model_path = Path('ai/ai_xgb_model.json')
        self.metrics_path = Path('ai/ai_model_metrics.json')
        self.bot_log_path = Path('logs')
        self.retrain_interval_days = 7  # Weekly retraining
        self.min_accuracy_threshold = 0.55  # Retrain if below 55%
        self.config_path = Path('config/bot_config.json')
    
    def should_retrain(self) -> Tuple[bool, str]:
        """
        Determine if model needs retraining.
        
        Returns:
            (should_retrain, reason)
        """
        # Check 1: Model exists?
        if not self.model_path.exists():
            return True, "Model file missing"
        
        # Check 2: Model age
        model_age_days = (time.time() - self.model_path.stat().st_mtime) / 86400
        if model_age_days > self.retrain_interval_days:
            return True, f"Model {model_age_days:.0f} days old (>{self.retrain_interval_days}d)"
        
        # Check 3: Recent performance
        recent_accuracy = self._get_recent_ml_accuracy(days=7)
        if recent_accuracy is not None and recent_accuracy < self.min_accuracy_threshold:
            return True, f"Recent accuracy {recent_accuracy:.2%} < {self.min_accuracy_threshold:.0%}"
        
        # Check 4: New data available
        if self._has_significant_new_data():
            return True, "Significant new trade data available (>50 new closed trades)"
        
        return False, "Model OK"
    
    def _get_recent_ml_accuracy(self, days: int = 7) -> Optional[float]:
        """Calculate ML prediction accuracy from recent bot logs."""
        try:
            cutoff_date = datetime.now() - timedelta(days=days)
            correct_predictions = 0
            total_predictions = 0
            
            # Scan recent log files
            log_files = sorted(self.bot_log_path.glob('bot_*.log'), reverse=True)
            
            for log_file in log_files[:10]:  # Check last 10 log files
                try:
                    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                        for line in f:
                            # Look for ML predictions and actual outcomes
                            if '[ML]' in line and 'prediction' in line.lower():
                                # Parse: [ML] Prediction for BTC-EUR: BUY (confidence: 0.75)
                                # Then look for outcome in subsequent lines
                                # This is simplified - actual implementation needs trade correlation
                                total_predictions += 1
                                # Placeholder logic
                                if 'profitable' in line.lower() or 'win' in line.lower():
                                    correct_predictions += 1
                
                except Exception as e:
                    log.warning(f"Error reading log {log_file}: {e}")
                    continue
            
            if total_predictions > 0:
                return correct_predictions / total_predictions
            
            return None
        
        except Exception as e:
            log.warning(f"Error calculating recent accuracy: {e}")
            return None
    
    def _has_significant_new_data(self, threshold: int = 50) -> bool:
        """Check if there are enough new closed trades since last training."""
        try:
            # Load trade log
            trade_log_path = Path('data/trade_log.json')
            if not trade_log_path.exists():
                return False
            
            with open(trade_log_path, 'r') as f:
                data = json.load(f)
            
            closed_trades = data.get('closed', [])
            
            # Get timestamp of last training
            if self.metrics_path.exists():
                with open(self.metrics_path, 'r') as f:
                    metrics = json.load(f)
                    last_training_time = metrics.get('training_timestamp', 0)
            else:
                last_training_time = 0
            
            # Count trades closed after last training
            new_trades = sum(
                1 for trade in closed_trades 
                if trade.get('close_timestamp', 0) > last_training_time
            )
            
            log.info(f"[AUTO_RETRAIN] Found {new_trades} new closed trades since last training")
            return new_trades >= threshold
        
        except Exception as e:
            log.warning(f"Error checking new data: {e}")
            return False
    
    def execute_retrain(self) -> Dict:
        """
        Execute full retraining pipeline:
        1. Extract latest data
        2. Train new model
        3. Backup old model
        4. Save metrics
        """
        log.info("[AUTO_RETRAIN] Starting automated retraining...")
        
        try:
            # Step 1: Backup old model
            if self.model_path.exists():
                backup_path = self.model_path.with_suffix('.json.backup')
                import shutil
                shutil.copy(self.model_path, backup_path)
                log.info(f"[AUTO_RETRAIN] Backed up old model to {backup_path}")
            
            # Step 2: Extract training data
            log.info("[AUTO_RETRAIN] Extracting training data...")
            from scripts.ml.extract_training_data import TrainingDataExtractor
            
            extractor = TrainingDataExtractor()
            df = extractor.load_trade_log()  # Use trade_log (fastest)
            
            if df.empty or len(df) < 50:
                log.warning("[AUTO_RETRAIN] Insufficient training data (<50 samples), aborting")
                return {'success': False, 'error': 'Insufficient data'}
            
            log.info(f"[AUTO_RETRAIN] Extracted {len(df)} samples, win rate: {df['label'].mean():.2%}")
            
            # Save extracted data
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            data_file = Path('ai/training_data') / f'raw_data_{timestamp}.csv'
            data_file.parent.mkdir(exist_ok=True)
            df.to_csv(data_file, index=False)
            
            # Step 3: Train new model
            log.info("[AUTO_RETRAIN] Training new model...")
            from scripts.ml.train_models import MLModelTrainer
            
            trainer = MLModelTrainer(model_save_path=str(self.model_path))
            
            # Quick training (no hyperparameter tuning for auto-retrain)
            # Use existing best parameters from config
            X = df.drop(['label', 'market', 'timestamp', 'close_timestamp'], axis=1, errors='ignore')
            y = df['label']
            
            metrics = trainer.train_xgboost(
                X_train=X,
                y_train=y,
                hyperparameter_tuning=False  # Fast retraining
            )
            
            # Add training timestamp
            metrics['training_timestamp'] = time.time()
            metrics['samples_used'] = len(df)
            metrics['win_rate'] = float(df['label'].mean())
            
            log.info(f"[AUTO_RETRAIN] Training complete!")
            log.info(f"[AUTO_RETRAIN] Accuracy: {metrics['accuracy']:.2%}")
            log.info(f"[AUTO_RETRAIN] ROC-AUC: {metrics['roc_auc']:.2%}")
            
            return {
                'success': True,
                'metrics': metrics,
                'samples': len(df),
                'timestamp': timestamp
            }
        
        except Exception as e:
            log.error(f"[AUTO_RETRAIN] Error during retraining: {e}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'error': str(e)}
    
    def run_check(self) -> Dict:
        """
        Main entry point: Check if retraining needed and execute if yes.
        
        Returns:
            Status dict with results
        """
        log.info("[AUTO_RETRAIN] Checking if retraining is needed...")
        
        should_train, reason = self.should_retrain()
        
        if should_train:
            log.info(f"[AUTO_RETRAIN] Retraining triggered: {reason}")
            result = self.execute_retrain()
            
            if result['success']:
                log.info("[AUTO_RETRAIN] ✅ Retraining successful!")
                return {
                    'action': 'retrained',
                    'reason': reason,
                    'metrics': result.get('metrics', {}),
                    'timestamp': datetime.now().isoformat()
                }
            else:
                log.error(f"[AUTO_RETRAIN] ❌ Retraining failed: {result.get('error')}")
                return {
                    'action': 'failed',
                    'reason': reason,
                    'error': result.get('error'),
                    'timestamp': datetime.now().isoformat()
                }
        else:
            log.info(f"[AUTO_RETRAIN] No retraining needed: {reason}")
            return {
                'action': 'skipped',
                'reason': reason,
                'timestamp': datetime.now().isoformat()
            }


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Automated ML model retraining')
    parser.add_argument('--force', action='store_true', help='Force retraining regardless of checks')
    parser.add_argument('--check-only', action='store_true', help='Only check, do not retrain')
    
    args = parser.parse_args()
    
    retrainer = AutoRetrain()
    
    if args.force:
        log.info("[AUTO_RETRAIN] Force retraining requested")
        result = retrainer.execute_retrain()
        print(json.dumps(result, indent=2))
    elif args.check_only:
        should_train, reason = retrainer.should_retrain()
        print(f"Should retrain: {should_train}")
        print(f"Reason: {reason}")
    else:
        result = retrainer.run_check()
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
